"""Host ↔ cognitive session binding (v0.6 Phase 8).

Native adapters call this module. They never assemble Context Packs or write
confirmed Memory / Judgment — the same core used by MCP / CLI / API does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from ..clock import now_iso
from ..config import Config
from ..memory.embeddings import Embedder
from ..memory.models import (
    HostSessionBinding,
    InterventionRecommendation,
    MemoryStatus,
)
from ..memory.store.base import MemoryStore
from .context_pack import ContextPack, build_context_pack
from .sessions import SessionStart, complete_session, observe_session, start_session

NATIVE_HOSTS = frozenset({
    "claude-code", "codex", "codex-app-server", "native",
})

# Host event kinds → session artifact kinds
EVENT_KIND_MAP = {
    "session_start": "session_start",
    "user_message": "user_message",
    "assistant_result": "assistant_result",
    "tool_execution": "tool_execution",
    "file_context": "file_context",
    "project_context": "project_context",
    "session_end": "session_end",
}


@dataclass
class NativeSessionStart:
    binding: HostSessionBinding
    started: SessionStart


def bind_and_start(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    *,
    host_type: str,
    external_session_id: str,
    query: str,
    cwd: Optional[str] = None,
    domain: Optional[str] = None,
    project: Optional[str] = None,
    task_profile: Optional[str] = None,
    max_tokens: int = 1200,
    persona: str = "individual",
    purpose: str = "task_execution",
    audience: str = "self",
    metadata: Optional[dict[str, Any]] = None,
) -> NativeSessionStart:
    """Open a CognitiveSession + HostSessionBinding for a host conversation.

    Idempotent on ``(host_type, external_session_id)`` while the binding is
    still open: reuses the existing cognitive session and rebuilds a pack.
    """
    host_type = (host_type or "native").lower()
    existing = store.find_host_session_binding(
        host_type=host_type, external_session_id=external_session_id,
    )
    if existing is not None and not existing.ended_at:
        # Proactive refresh — same session, new pack from core.
        pack = request_context_pack(
            store, cfg, embedder,
            query=query,
            session_id=existing.cognitive_session_id,
            cwd=cwd, domain=domain, project=project,
            task_profile=task_profile, max_tokens=max_tokens,
            persona=persona, purpose=purpose, audience=audience,
            client=host_type,
        )
        session = store.get_session(existing.cognitive_session_id)
        if session is None:
            raise ValueError(
                f"binding {existing.id} points at missing session "
                f"{existing.cognitive_session_id}"
            )
        # Synthetic SessionStart for callers
        started = SessionStart(
            session=session, pack=pack,
            reading_confidences={}, observer_mode="native",
        )
        return NativeSessionStart(binding=existing, started=started)

    started = start_session(
        store, cfg, embedder, query,
        client=host_type,
        cwd=cwd, domain=domain, project=project,
        task_profile=task_profile, max_tokens=max_tokens,
        persona=persona, purpose=purpose, audience=audience,
        tool_id=host_type,
    )
    binding = HostSessionBinding(
        host_type=host_type,
        external_session_id=external_session_id,
        cognitive_session_id=started.session.id,
        project_id=started.session.project_id,
        principal_id=started.session.principal_id,
        started_at=started.session.started_at or now_iso(),
        metadata=dict(metadata or {}),
    )
    store.insert_host_session_binding(binding)
    return NativeSessionStart(binding=binding, started=started)


def resolve_binding(
    store: MemoryStore,
    *,
    host_type: str,
    external_session_id: Optional[str] = None,
    cognitive_session_id: Optional[str] = None,
    binding_id: Optional[str] = None,
) -> HostSessionBinding:
    if binding_id:
        b = store.get_host_session_binding(binding_id)
        if b is None:
            raise ValueError(f"host binding {binding_id} not found")
        return b
    if cognitive_session_id:
        b = store.find_host_session_binding_by_session(cognitive_session_id)
        if b is None:
            raise ValueError(
                f"no host binding for session {cognitive_session_id}"
            )
        return b
    if external_session_id:
        b = store.find_host_session_binding(
            host_type=host_type, external_session_id=external_session_id,
        )
        if b is None:
            raise ValueError(
                f"no host binding for {host_type}:{external_session_id}"
            )
        return b
    raise ValueError("need binding_id, external_session_id, or cognitive_session_id")


def observe_host_event(
    store: MemoryStore,
    *,
    host_type: str,
    external_session_id: str,
    event_kind: str,
    note: str = "",
    ref: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> HostSessionBinding:
    """Record a host observation on the bound CognitiveSession."""
    binding = resolve_binding(
        store, host_type=host_type, external_session_id=external_session_id,
    )
    if binding.ended_at:
        raise ValueError(f"host binding {binding.id} already ended")
    kind = EVENT_KIND_MAP.get(event_kind, event_kind)
    artifact: dict[str, Any] = {"kind": kind, "host_type": host_type}
    if note:
        artifact["note"] = note
    if ref:
        artifact["ref"] = ref
    if extra:
        artifact["host"] = extra
    observe_session(store, binding.cognitive_session_id, artifact)
    return binding


def request_context_pack(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    *,
    query: str,
    session_id: Optional[str] = None,
    cwd: Optional[str] = None,
    domain: Optional[str] = None,
    project: Optional[str] = None,
    task_profile: Optional[str] = None,
    max_tokens: int = 1200,
    persona: str = "individual",
    purpose: str = "memory_retrieval",
    audience: str = "self",
    client: str = "claude-code",
) -> ContextPack:
    """Proactive Context Pack — assembled only by the cognitive core."""
    from ..privacy.identity import ensure_local_identity, resolve_access
    from ..privacy.yaml_io import bootstrap_policy_set
    from .observer import read_context

    reading = read_context(store, cfg, query, cwd=cwd)
    project_id = None
    if project:
        found = store.get_project(project) or store.find_project(project)
        if found is None:
            raise ValueError(f"project {project!r} not found")
        project_id = found.id
    else:
        project_id = reading.project_id
    if session_id:
        session = store.get_session(session_id)
        if session is not None:
            project_id = project_id or session.project_id
            domain = domain or session.domain
            task_profile = task_profile or session.task_profile

    session_domain = domain or reading.domain
    bootstrap_policy_set(store, policies_path=cfg.policies_path)
    ensure_local_identity(store)
    # Hook runner is local CLI transport; client label stays native host.
    access = resolve_access(
        store,
        surface="cli",
        client="cli",
        tool_id=client,
        persona=persona,
        purpose=purpose,
        audience=audience,
        project_id=project_id,
        session_id=session_id,
        requested_domains=[session_domain] if session_domain else [],
    )
    return build_context_pack(
        store, cfg, embedder, query,
        target_domain=session_domain,
        max_tokens=max_tokens,
        task_profile=task_profile or reading.task_profile,
        project_id=project_id,
        access=access,
    )


def end_host_session(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    *,
    host_type: str,
    external_session_id: str,
    summary: str = "",
    abandoned: bool = False,
    summary_origin: str = "assistant",
) -> HostSessionBinding:
    binding = resolve_binding(
        store, host_type=host_type, external_session_id=external_session_id,
    )
    if not binding.ended_at:
        complete_session(
            store, cfg, embedder, binding.cognitive_session_id,
            summary=summary, abandoned=abandoned,
            summary_origin=summary_origin,
        )
        binding.ended_at = now_iso()
        store.update_host_session_binding(binding)
    return binding


def recommend_intervention(
    store: MemoryStore,
    *,
    session_id: str,
    draft_text: str,
    limit: int = 5,
) -> list[InterventionRecommendation]:
    """Lightweight display-only warnings (no host action).

    Flags confirmed decisions that look contradicted by the draft text.
    """
    text = (draft_text or "").strip()
    if not text:
        return []
    session = store.get_session(session_id)
    if session is None:
        return []

    # Prefer memories already supplied to this session; fall back to project.
    candidates = []
    for mid in list(session.supplied_memory_ids or [])[:50]:
        mem = store.get_memory(mid)
        if mem is not None:
            candidates.append(mem)
    if not candidates and session.project_id:
        candidates = store.list_memories(
            project_id=session.project_id, status="confirmed", limit=40,
        )

    reverse_cues = (
        "instead", "revert", "undo", "no longer", "don't use", "do not use",
        "replace with", "abandon", "cancel", "postpone", "never mind",
    )
    lowered = text.lower()
    has_reverse = any(c in lowered for c in reverse_cues)
    out: list[InterventionRecommendation] = []
    for mem in candidates:
        if getattr(mem.status, "value", mem.status) not in (
            MemoryStatus.confirmed.value, "confirmed",
        ):
            continue
        if mem.type.value != "decision" and str(mem.type) != "decision":
            continue
        # Title/summary tokens overlapping the draft → possible conflict
        hay = f"{mem.title} {mem.summary}".lower()
        tokens = [t for t in hay.replace(",", " ").split() if len(t) >= 4][:12]
        overlap = sum(1 for t in tokens if t in lowered)
        if overlap < 2 and not (has_reverse and overlap >= 1):
            continue
        urgency = "high" if has_reverse and overlap >= 2 else "medium"
        out.append(InterventionRecommendation(
            type="warning",
            reason=(
                f"Draft may reverse confirmed decision "
                f"{mem.id}: {mem.title}"
            ),
            urgency=urgency,
            session_id=session_id,
            supported_actions=["display"],
            requires_confirmation=False,
            metadata={"memory_id": mem.id, "overlap": overlap},
        ))
        if len(out) >= limit:
            break
    return out
