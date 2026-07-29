"""Native host façade over the cognitive core.

Fail-open: unexpected Twin errors become ``ok=False`` results — they must
not crash the host hook process. Orphan / out-of-order events follow an
explicit policy (documented on each branch below).
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

# Soft latency budgets (wall-clock, ms) for pack assembly on the native hot
# path. These do NOT interrupt work mid-flight — the pack is assembled, then
# dropped from the host response if it blew the budget (domain/binding state
# already persisted stays). Keeps hooks responsive; the pack recovers on the
# next injection-capable turn or via MCP. Override via ``cfg.native_pack_budget_ms``.
_PACK_BUDGET_MS: dict[str, float] = {
    "session_start": 300.0,
    "user_message": 500.0,
}

_PROTO_DENY_EXTRAS = frozenset({
    "traceback", "traceback_tail", "stack", "error_class",
})

from ...cognition.host_session import (
    BindingScopeError,
    NativeSessionStart,
    bind_and_start,
    end_host_session,
    maybe_enqueue_domain_resolve,
    maybe_upgrade_domain_and_pack,
    observe_host_event,
    recommend_intervention,
    request_context_pack,
    resolve_active_binding,
)
from ...config import Config
from ...memory.embeddings import Embedder
from ...memory.models import HostSessionBinding, InterventionRecommendation
from ...memory.store.base import MemoryStore
from .events import ALLOWED_HOST_EVENT_KINDS, PACK_EMIT_KINDS, HostEvent

logger = logging.getLogger("twin.interfaces.native")


@dataclass
class NativeEventResult:
    ok: bool = True
    binding: Optional[HostSessionBinding] = None
    session_id: Optional[str] = None
    context_pack: Optional[str] = None
    sources: list[dict[str, Any]] = field(default_factory=list)
    interventions: list[InterventionRecommendation] = field(default_factory=list)
    error: Optional[str] = None
    error_id: Optional[str] = None
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, include_pack: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": self.ok}
        if self.error:
            out["error"] = self.error
        if self.error_id:
            out["error_id"] = self.error_id
        if self.binding is not None:
            out["binding_id"] = self.binding.id
            out["host_type"] = self.binding.host_type
            out["external_session_id"] = self.binding.external_session_id
            out["occurrence"] = self.binding.occurrence
            out["domain"] = self.binding.domain
            out["project_id"] = self.binding.project_id
        if self.session_id:
            out["session_id"] = self.session_id
        if include_pack and self.context_pack is not None:
            out["context_pack"] = self.context_pack
            out["sources"] = self.sources
        if self.interventions:
            out["interventions"] = [i.model_dump() for i in self.interventions]
        if self.extras:
            for k, v in self.extras.items():
                if k in _PROTO_DENY_EXTRAS:
                    continue
                out[k] = v
        return out


class NativeHostService:
    """Thin host façade — pack/session logic stays in cognition."""

    def __init__(self, store: MemoryStore, cfg: Config, embedder: Embedder):
        self.store = store
        self.cfg = cfg
        self.embedder = embedder

    def _pack_budget_ms(self, kind: str) -> float:
        """Soft pack budget for a hot-path event kind (0 disables)."""
        override = getattr(self.cfg, "native_pack_budget_ms", None)
        if isinstance(override, dict) and kind in override:
            try:
                return float(override[kind])
            except (TypeError, ValueError):
                pass
        return _PACK_BUDGET_MS.get(kind, 0.0)

    def _capabilities(self, binding: Optional[HostSessionBinding], *, host_type: str = "") -> "HostCapabilities":
        """Resolve declared HostCapabilities from binding metadata.

        Adapters stash ``host_capabilities`` on the binding at session_start.
        Missing declaration falls back to conservative per-host defaults —
        never a provider-name branch in the hot path.
        """
        from .events import CLAUDE_CODE_CAPABILITIES, HostCapabilities
        meta = (binding.metadata or {}) if binding is not None else {}
        raw = meta.get("host_capabilities")
        if isinstance(raw, dict):
            try:
                return HostCapabilities(**raw)
            except Exception:  # malformed declaration → conservative default
                logger.warning("ignoring malformed host_capabilities on binding")
        ht = host_type or (getattr(binding, "host_type", "") if binding else "")
        if ht == "claude-code":
            return CLAUDE_CODE_CAPABILITIES
        return HostCapabilities()

    def handle(self, event: HostEvent) -> NativeEventResult:
        try:
            return self._handle(event)
        except (ValueError, BindingScopeError) as exc:
            return NativeEventResult(ok=False, error=str(exc))
        except Exception:  # fail-open for host hooks
            error_id = uuid.uuid4().hex[:12]
            # Diagnostics stay in the logger / stderr — never on host stdout.
            logger.exception(
                "native observation failed error_id=%s kind=%s host=%s",
                error_id, getattr(event, "kind", "?"), getattr(event, "host_type", "?"),
            )
            return NativeEventResult(
                ok=False,
                error="native observation failed",
                error_id=error_id,
            )

    def _handle(self, event: HostEvent) -> NativeEventResult:
        kind = (event.kind or "").strip()
        if kind not in ALLOWED_HOST_EVENT_KINDS:
            return NativeEventResult(
                ok=False,
                error=f"unsupported_host_event: {kind}",
                extras={"kind": kind},
            )
        if kind == "unsupported_host_event":
            return NativeEventResult(
                ok=False,
                error="unsupported_host_event",
                extras={"rejected": True},
            )
        if not (event.external_session_id or "").strip():
            return NativeEventResult(ok=False, error="external_session_id required")

        if kind in ("session_start", "pack_request"):
            return self._start_or_pack(event, observe_start=(kind == "session_start"))

        if kind == "session_end":
            # Contract gate (fail-closed): a host that declared it never ends
            # sessions must not send session_end. Reject without crashing.
            gate = resolve_active_binding(
                self.store,
                host_type=event.host_type,
                external_session_id=event.external_session_id,
            )
            if gate is not None and not self._capabilities(gate).supports_session_end:
                return NativeEventResult(
                    ok=False,
                    error="host declared no session_end support",
                    extras={"rejected": True, "capability": "supports_session_end"},
                )
            # Orphan SessionEnd → idempotent no-op (warning logged in end_host_session)
            binding = end_host_session(
                self.store, self.cfg, self.embedder,
                host_type=event.host_type,
                external_session_id=event.external_session_id,
                summary=event.summary or event.text,
                abandoned=event.abandoned,
            )
            if binding is None:
                return NativeEventResult(
                    ok=True,
                    extras={"ended": False, "orphan_session_end": True},
                )
            return NativeEventResult(
                binding=binding,
                session_id=binding.cognitive_session_id,
                extras={"ended": True, "ended_at": binding.ended_at},
            )

        if kind == "intervene_check":
            binding = resolve_active_binding(
                self.store,
                host_type=event.host_type,
                external_session_id=event.external_session_id,
            )
            if binding is None:
                return NativeEventResult(
                    ok=False, error="no active binding for intervene_check",
                )
            if not self._capabilities(binding).display_intervention:
                # Host cannot surface interventions — don't spend an LLM call.
                return NativeEventResult(
                    binding=binding,
                    session_id=binding.cognitive_session_id,
                    extras={"intervention_suppressed": "display_intervention"},
                )
            recs = recommend_intervention(
                self.store,
                session_id=binding.cognitive_session_id,
                draft_text=event.text,
            )
            # Parallel workspace tick: confidence-aware spontaneous recall.
            # Silent when nothing clears the bar; blocked stay ids-only.
            try:
                from ...cognition.workspace import workspace_tick
                tick = workspace_tick(
                    self.store, self.cfg, self.embedder, event.text or "",
                    session_id=binding.cognitive_session_id,
                    target_domain=binding.domain,
                    interpret=False,
                )
                for sug in tick.suggestions:
                    recs.append(InterventionRecommendation(
                        type="info",
                        reason=(
                            f"Spontaneous recall: {sug.get('summary') or sug.get('memory_id')}"
                        ),
                        urgency="low",
                        session_id=binding.cognitive_session_id,
                        supported_actions=["display"],
                        requires_confirmation=False,
                        metadata={
                            "stage": "suggestion",
                            "memory_id": sug.get("memory_id"),
                            "confidence": sug.get("confidence"),
                            "salience": sug.get("salience"),
                            "why_relevant": sug.get("why_relevant"),
                            "silent": tick.silent,
                        },
                    ))
                extras = {
                    "workspace_silent": tick.silent,
                    "workspace_blocked_count": len(tick.blocked),
                    "workspace_stages": list(tick.stages),
                }
            except Exception as exc:  # fail-open: recall must not break host
                logger.warning("workspace tick on intervene_check failed: %s", exc)
                extras = {"workspace_tick_error": type(exc).__name__}
            return NativeEventResult(
                binding=binding,
                session_id=binding.cognitive_session_id,
                interventions=recs,
                extras=extras,
            )

        # Contract gate (fail-closed): a host that declared no turn-end support
        # must not emit turn_completed. Reject the contract breach, don't crash.
        if kind == "turn_completed":
            gate = resolve_active_binding(
                self.store,
                host_type=event.host_type,
                external_session_id=event.external_session_id,
            )
            if gate is not None and not self._capabilities(gate).supports_turn_end:
                return NativeEventResult(
                    ok=False,
                    error="host declared no turn_completed support",
                    extras={"rejected": True, "capability": "supports_turn_end"},
                )

        # Observations require an active binding — never invent one from cwd.
        # After SessionEnd: reject (do not attach to closed occurrence).
        result = observe_host_event(
            self.store,
            host_type=event.host_type,
            external_session_id=event.external_session_id,
            event_kind=kind,
            note=event.text,
            ref=event.ref,
            event_id=event.event_id,
            delivery_id=event.delivery_id,
            sequence=event.sequence,
            tool_call_id=event.tool_call_id,
            tool_phase=event.tool_phase,
            extra=event.metadata or None,
            redacted=event.redacted,
            redaction_categories=event.redaction_categories,
        )
        extras: dict[str, Any] = {"duplicated": result.duplicated}

        # Host may open without semantic input → unclassified empty pack.
        # First semantic user event: hot path is search-vote only.
        # If still unclassified, enqueue background LLM resolve from dialogue —
        # never block the hook on the local model. Background resolve marks
        # ``pending_context_pack``; the next injection-capable event emits it
        # (hosts without push cannot inject mid-turn).
        if (
            kind == "user_message"
            and not result.duplicated
            and (event.text or "").strip()
        ):
            # Can this host inject a pack on user_message? Domain resolution
            # still runs (binding scope is host-independent), but a pack is only
            # produced/emitted when the host can actually surface it here.
            can_inject = "user_message" in self._capabilities(
                result.binding
            ).context_injection_events
            t0 = time.monotonic()
            upgraded = maybe_upgrade_domain_and_pack(
                self.store, self.cfg, self.embedder,
                binding=result.binding,
                query=event.text,
                cwd=event.cwd,
            )
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            if upgraded is not None:
                extras.update({
                    "domain": upgraded.resolved_domain,
                    "domain_upgraded_from": upgraded.previous_domain,
                    "needs_domain_confirmation": False,
                })
                budget = self._pack_budget_ms("user_message")
                over_budget = budget > 0 and elapsed_ms > budget
                if not can_inject:
                    # Domain applied; hold the pack — host has no injection point.
                    extras["pack_held_no_injection_point"] = True
                    return NativeEventResult(
                        binding=upgraded.binding,
                        session_id=upgraded.binding.cognitive_session_id,
                        extras=extras,
                    )
                if over_budget:
                    # Domain upgrade persisted; drop the pack to stay responsive.
                    extras["pack_skipped_budget"] = True
                    extras["pack_elapsed_ms"] = round(elapsed_ms, 1)
                    return NativeEventResult(
                        binding=upgraded.binding,
                        session_id=upgraded.binding.cognitive_session_id,
                        extras=extras,
                    )
                pack = upgraded.pack
                extras["emit_pack"] = True
                return NativeEventResult(
                    binding=upgraded.binding,
                    session_id=upgraded.binding.cognitive_session_id,
                    context_pack=pack.context_pack,
                    sources=list(pack.sources or []),
                    extras=extras,
                )
            if can_inject:
                pending = self._maybe_emit_pending_pack(
                    result.binding, query=event.text, cwd=event.cwd, extras=extras,
                )
                if pending is not None:
                    return pending
            job_id = maybe_enqueue_domain_resolve(
                self.store, result.binding, cwd=event.cwd,
            )
            if job_id:
                extras["domain_resolve_job_id"] = job_id
                extras["needs_domain_confirmation"] = True

        return NativeEventResult(
            binding=result.binding,
            session_id=result.binding.cognitive_session_id,
            extras=extras,
        )

    def _maybe_emit_pending_pack(
        self,
        binding: HostSessionBinding,
        *,
        query: str,
        cwd: Optional[str],
        extras: dict[str, Any],
    ) -> Optional[NativeEventResult]:
        """Emit a pack prepared after background domain resolve (next turn)."""
        meta = dict(binding.metadata or {})
        if not meta.get("pending_context_pack"):
            return None
        from ...config import UNCLASSIFIED_DOMAIN
        if not binding.domain or binding.domain == UNCLASSIFIED_DOMAIN:
            return None
        pack = request_context_pack(
            self.store, self.cfg, self.embedder,
            query=query or "native host session",
            binding=binding,
            cwd=cwd,
            client=binding.host_type or "native",
        )
        meta.pop("pending_context_pack", None)
        binding.metadata = meta
        self.store.update_host_session_binding(binding)
        extras.update({
            "domain": binding.domain,
            "pending_context_pack_emitted": True,
            "needs_domain_confirmation": False,
            "emit_pack": True,
        })
        return NativeEventResult(
            binding=binding,
            session_id=binding.cognitive_session_id,
            context_pack=pack.context_pack,
            sources=list(pack.sources or []),
            extras=extras,
        )

    def _start_or_pack(
        self, event: HostEvent, *, observe_start: bool,
    ) -> NativeEventResult:
        query = event.text or event.summary or "native host session"
        meta = dict(event.metadata or {})
        # Capabilities belong on the binding, not every observation artifact.
        if observe_start:
            caps = meta.get("host_capabilities")
            if not caps:
                # Prefer adapter-supplied capabilities; fall back to defaults
                # for the declared host_type without importing provider modules
                # into the generic path beyond the known registry.
                from .events import CLAUDE_CODE_CAPABILITIES, HostCapabilities
                if event.host_type == "claude-code":
                    caps = CLAUDE_CODE_CAPABILITIES.model_dump()
                else:
                    caps = HostCapabilities().model_dump()
                meta["host_capabilities"] = caps
        t0 = time.monotonic()
        started: NativeSessionStart = bind_and_start(
            self.store, self.cfg, self.embedder,
            host_type=event.host_type,
            external_session_id=event.external_session_id,
            query=query,
            cwd=event.cwd,
            domain=event.domain,
            project=event.project,
            task_profile=event.task_profile,
            persona=event.persona or "individual",
            purpose=event.purpose or "task_execution",
            audience=event.audience or "self",
            metadata=meta,
        )
        elapsed_ms = (time.monotonic() - t0) * 1000.0
        if observe_start:
            observe_host_event(
                self.store,
                host_type=event.host_type,
                external_session_id=event.external_session_id,
                event_kind="session_start",
                note=query,
                ref=event.cwd,
                event_id=event.event_id or f"session_start:{started.binding.occurrence}",
            )
        pack = started.started.pack
        extras: dict[str, Any] = {
            "project_id": started.binding.project_id,
            "domain": started.binding.domain,
            "task_profile": started.binding.task_profile,
            "occurrence": started.binding.occurrence,
            "needs_domain_confirmation": started.started.needs_domain_confirmation,
        }
        budget = self._pack_budget_ms(
            "session_start" if observe_start else "pack_request"
        )
        if budget > 0 and elapsed_ms > budget:
            # Session/binding persisted; drop the pack to keep the hook snappy.
            extras["pack_skipped_budget"] = True
            extras["pack_elapsed_ms"] = round(elapsed_ms, 1)
            return NativeEventResult(
                binding=started.binding,
                session_id=started.binding.cognitive_session_id,
                extras=extras,
            )
        extras["emit_pack"] = True
        return NativeEventResult(
            binding=started.binding,
            session_id=started.binding.cognitive_session_id,
            context_pack=pack.context_pack,
            sources=list(pack.sources or []),
            extras=extras,
        )


def handle_normalized_event(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    event: HostEvent,
) -> NativeEventResult:
    return NativeHostService(store, cfg, embedder).handle(event)


def proactive_pack(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    *,
    query: str,
    host_type: str = "native",
    session_id: Optional[str] = None,
    cwd: Optional[str] = None,
    project: Optional[str] = None,
    domain: Optional[str] = None,
    task_profile: Optional[str] = None,
) -> dict[str, Any]:
    pack = request_context_pack(
        store, cfg, embedder,
        query=query, session_id=session_id, cwd=cwd,
        domain=domain, project=project, task_profile=task_profile,
        client=host_type,
    )
    return {
        "context_pack": pack.context_pack,
        "sources": pack.sources,
        "blocked": pack.blocked,
        "project_id": pack.project_id,
        "task_profile": pack.task_profile,
    }


def should_emit_pack(kind: str) -> bool:
    return kind in PACK_EMIT_KINDS
