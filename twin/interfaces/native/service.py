"""Native host façade over the cognitive core (v0.6 Phase 8).

Fail-open: unexpected Twin errors become ``ok=False`` results — they must
not crash the host hook process. Orphan / out-of-order events follow an
explicit policy (documented on each branch below).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

_PROTO_DENY_EXTRAS = frozenset({
    "traceback", "traceback_tail", "stack", "error_class",
})

from ...cognition.host_session import (
    BindingScopeError,
    NativeSessionStart,
    bind_and_start,
    end_host_session,
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
            # Orphan Stop → idempotent no-op (warning logged in end_host_session)
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

        # Observations require an active binding — never invent one from cwd.
        # After Stop: reject (do not attach to closed occurrence).
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
        return NativeEventResult(
            binding=result.binding,
            session_id=result.binding.cognitive_session_id,
            extras={"duplicated": result.duplicated},
        )

    def _start_or_pack(
        self, event: HostEvent, *, observe_start: bool,
    ) -> NativeEventResult:
        query = event.text or event.summary or "native host session"
        meta = dict(event.metadata or {})
        # Capabilities belong on the binding, not every observation artifact.
        if observe_start:
            from .events import CLAUDE_CODE_CAPABILITIES
            meta.setdefault(
                "host_capabilities", CLAUDE_CODE_CAPABILITIES.model_dump(),
            )
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
        return NativeEventResult(
            binding=started.binding,
            session_id=started.binding.cognitive_session_id,
            context_pack=pack.context_pack,
            sources=list(pack.sources or []),
            extras={
                "project_id": started.binding.project_id,
                "domain": started.binding.domain,
                "task_profile": started.binding.task_profile,
                "occurrence": started.binding.occurrence,
                "needs_domain_confirmation": started.started.needs_domain_confirmation,
                "emit_pack": True,
            },
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
    host_type: str = "claude-code",
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
