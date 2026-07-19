"""Native host façade over the cognitive core (v0.6 Phase 8)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ...cognition.host_session import (
    NativeSessionStart,
    bind_and_start,
    end_host_session,
    observe_host_event,
    recommend_intervention,
    request_context_pack,
)
from ...config import Config
from ...memory.embeddings import Embedder
from ...memory.models import HostSessionBinding, InterventionRecommendation
from ...memory.store.base import MemoryStore
from .events import HostEvent


@dataclass
class NativeEventResult:
    ok: bool = True
    binding: Optional[HostSessionBinding] = None
    session_id: Optional[str] = None
    context_pack: Optional[str] = None
    sources: list[dict[str, Any]] = field(default_factory=list)
    interventions: list[InterventionRecommendation] = field(default_factory=list)
    error: Optional[str] = None
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": self.ok}
        if self.error:
            out["error"] = self.error
        if self.binding is not None:
            out["binding_id"] = self.binding.id
            out["host_type"] = self.binding.host_type
            out["external_session_id"] = self.binding.external_session_id
        if self.session_id:
            out["session_id"] = self.session_id
        if self.context_pack is not None:
            out["context_pack"] = self.context_pack
            out["sources"] = self.sources
        if self.interventions:
            out["interventions"] = [i.model_dump() for i in self.interventions]
        if self.extras:
            out.update(self.extras)
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
        except ValueError as exc:
            return NativeEventResult(ok=False, error=str(exc))

    def _handle(self, event: HostEvent) -> NativeEventResult:
        kind = (event.kind or "").strip()
        if kind in ("session_start", "pack_request"):
            return self._start_or_pack(event, observe_start=(kind == "session_start"))
        if kind == "session_end":
            binding = end_host_session(
                self.store, self.cfg, self.embedder,
                host_type=event.host_type,
                external_session_id=event.external_session_id,
                summary=event.summary or event.text,
                abandoned=event.abandoned,
            )
            return NativeEventResult(
                binding=binding,
                session_id=binding.cognitive_session_id,
                extras={"ended": True, "ended_at": binding.ended_at},
            )
        if kind == "intervene_check":
            binding = self.store.find_host_session_binding(
                host_type=event.host_type,
                external_session_id=event.external_session_id,
            )
            if binding is None:
                return NativeEventResult(ok=False, error="no binding for intervene_check")
            recs = recommend_intervention(
                self.store,
                session_id=binding.cognitive_session_id,
                draft_text=event.text,
            )
            return NativeEventResult(
                binding=binding,
                session_id=binding.cognitive_session_id,
                interventions=recs,
            )
        # Observation events
        if not event.external_session_id:
            return NativeEventResult(ok=False, error="external_session_id required")
        binding = observe_host_event(
            self.store,
            host_type=event.host_type,
            external_session_id=event.external_session_id,
            event_kind=kind,
            note=event.text,
            ref=event.ref,
            extra=event.metadata or None,
        )
        return NativeEventResult(
            binding=binding,
            session_id=binding.cognitive_session_id,
        )

    def _start_or_pack(
        self, event: HostEvent, *, observe_start: bool,
    ) -> NativeEventResult:
        if not event.external_session_id:
            return NativeEventResult(ok=False, error="external_session_id required")
        query = event.text or event.summary or "native host session"
        started: NativeSessionStart = bind_and_start(
            self.store, self.cfg, self.embedder,
            host_type=event.host_type,
            external_session_id=event.external_session_id,
            query=query,
            cwd=event.cwd,
            domain=event.domain,
            project=event.project,
            task_profile=event.task_profile,
            metadata=event.metadata,
        )
        if observe_start:
            observe_host_event(
                self.store,
                host_type=event.host_type,
                external_session_id=event.external_session_id,
                event_kind="session_start",
                note=query,
                ref=event.cwd,
            )
        pack = started.started.pack
        return NativeEventResult(
            binding=started.binding,
            session_id=started.binding.cognitive_session_id,
            context_pack=pack.context_pack,
            sources=list(pack.sources or []),
            extras={
                "project_id": started.started.session.project_id,
                "domain": started.started.session.domain,
                "task_profile": started.started.session.task_profile,
                "needs_domain_confirmation": started.started.needs_domain_confirmation,
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
    """Convenience: pack-only call without mutating host binding."""
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
