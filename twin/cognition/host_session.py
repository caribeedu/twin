"""Host ↔ cognitive session binding (v0.6 Phase 8).

Native adapters call this module. They never assemble Context Packs or write
confirmed Memory / Judgment — the same core used by MCP / CLI / API does.

Binding contract:
- ``(host_type, external_session_id, occurrence)`` is unique;
- after Stop, a new SessionStart opens occurrence N+1 + new CognitiveSession;
- security fields (domain/project/persona/purpose/audience/vault) freeze at bind;
- observations are idempotent by ``event_id``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from .. import ids
from ..clock import now_iso
from ..config import Config
from ..memory.embeddings import Embedder
from ..memory.models import (
    HostSessionBinding,
    InterventionRecommendation,
    MemoryStatus,
    SessionStatus,
)
from ..memory.store.base import MemoryStore
from ..memory.store.host_binding_mixin import is_unique_violation
from .context_pack import ContextPack, build_context_pack
from .sessions import SessionStart, complete_session, observe_session, start_session

logger = logging.getLogger("twin.cognition.host_session")

NATIVE_HOSTS = frozenset({
    "claude-code", "codex", "codex-app-server", "native",
})

ALLOWED_OBSERVE_KINDS = frozenset({
    "session_start",
    "user_message",
    "assistant_result",
    "tool_requested",
    "tool_completed",
    "tool_failed",
    "file_context",
    "project_context",
})

_TOOL_KINDS = frozenset({"tool_requested", "tool_completed", "tool_failed"})


@dataclass
class NativeSessionStart:
    binding: HostSessionBinding
    started: SessionStart


@dataclass
class ObserveResult:
    binding: HostSessionBinding
    duplicated: bool = False


class BindingScopeError(ValueError):
    """Host tried to widen frozen security scope on an open binding."""


def resolve_observation_event_id(
    *,
    event_id: Optional[str] = None,
    delivery_id: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    tool_phase: Optional[str] = None,
    kind: str = "",
    sequence: Optional[int] = None,
) -> str:
    """Stable idempotency key — never fingerprint content alone.

    Preference:
    1. host ``event_id``
    2. ``delivery_id``
    3. ``tool_call_id`` + phase (same tool call = same delivery)
    4. host ``sequence``
    5. allocate a unique id (identical text stays distinct; retries may dup)
    """
    if event_id:
        return str(event_id)
    if delivery_id:
        return f"delivery:{delivery_id}"
    if tool_call_id and kind in _TOOL_KINDS:
        phase = tool_phase or kind
        return f"tool:{tool_call_id}:{phase}"
    if sequence is not None:
        return f"seq:{int(sequence)}:{kind}"
    # No trustworthy identity → do not collapse equal payloads.
    return ids.new_id("hostevent")


def _assert_frozen_scope(
    binding: HostSessionBinding,
    *,
    domain: Optional[str],
    project: Optional[str],
    persona: Optional[str],
    purpose: Optional[str],
    audience: Optional[str],
) -> None:
    """Reject silent scope widening on an open binding."""
    if domain and binding.domain and domain != binding.domain:
        raise BindingScopeError(
            f"domain mismatch: binding frozen to {binding.domain!r}, "
            f"got {domain!r} — start a new host session"
        )
    if persona and binding.persona and persona != binding.persona:
        raise BindingScopeError(
            f"persona mismatch: binding frozen to {binding.persona!r}"
        )
    if purpose and binding.purpose and purpose != binding.purpose:
        raise BindingScopeError(
            f"purpose mismatch: binding frozen to {binding.purpose!r}"
        )
    if audience and binding.audience and audience != binding.audience:
        raise BindingScopeError(
            f"audience mismatch: binding frozen to {binding.audience!r}"
        )


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
    """Open or reuse an *active* binding; after Stop, open a new occurrence."""
    if not (external_session_id or "").strip():
        raise ValueError("external_session_id required")
    host_type = (host_type or "native").lower()
    external_session_id = external_session_id.strip()

    existing = store.find_active_host_session_binding(
        host_type=host_type, external_session_id=external_session_id,
    )
    if existing is not None:
        _assert_frozen_scope(
            existing,
            domain=domain, project=project,
            persona=persona, purpose=purpose, audience=audience,
        )
        if project:
            found = store.get_project(project) or store.find_project(project)
            if found is None:
                raise ValueError(f"project {project!r} not found")
            if existing.project_id and found.id != existing.project_id:
                raise BindingScopeError(
                    f"project mismatch: binding frozen to {existing.project_id!r}"
                )
        pack = request_context_pack(
            store, cfg, embedder,
            query=query,
            binding=existing,
            cwd=cwd,
            max_tokens=max_tokens,
            client=host_type,
        )
        session = store.get_session(existing.cognitive_session_id)
        if session is None:
            raise ValueError(
                f"binding {existing.id} points at missing session "
                f"{existing.cognitive_session_id}"
            )
        started = SessionStart(
            session=session, pack=pack,
            reading_confidences={}, observer_mode="native",
        )
        return NativeSessionStart(binding=existing, started=started)

    # Re-check under race: peer may have won between lookup and create.
    existing = store.find_active_host_session_binding(
        host_type=host_type, external_session_id=external_session_id,
    )
    if existing is not None:
        return bind_and_start(
            store, cfg, embedder,
            host_type=host_type, external_session_id=external_session_id,
            query=query, cwd=cwd, domain=domain, project=project,
            task_profile=task_profile, max_tokens=max_tokens,
            persona=persona, purpose=purpose, audience=audience,
            metadata=metadata,
        )

    occurrence = store.next_host_binding_occurrence(
        host_type=host_type, external_session_id=external_session_id,
    )
    started = start_session(
        store, cfg, embedder, query,
        client=host_type,
        cwd=cwd, domain=domain, project=project,
        task_profile=task_profile, max_tokens=max_tokens,
        persona=persona, purpose=purpose, audience=audience,
        tool_id=host_type,
    )
    # Vault comes from project / explicit metadata — never inferred from domain name.
    vault_id = None
    if started.session.project_id:
        proj = store.get_project(started.session.project_id)
        if proj is not None:
            vault_id = (proj.metadata or {}).get("vault_id")
    if not vault_id and isinstance(metadata, dict):
        vault_id = metadata.get("vault_id")
    if not vault_id:
        vault_id = None
    binding = HostSessionBinding(
        host_type=host_type,
        external_session_id=external_session_id,
        occurrence=occurrence,
        cognitive_session_id=started.session.id,
        project_id=started.session.project_id,
        principal_id=started.session.principal_id,
        vault_id=vault_id,
        domain=started.session.domain,
        persona=started.session.persona or persona,
        purpose=started.session.purpose or purpose,
        audience=started.session.audience or audience,
        task_profile=started.session.task_profile or task_profile,
        started_at=started.session.started_at or now_iso(),
        metadata=dict(metadata or {}),
    )
    try:
        store.insert_host_session_binding(binding)
    except Exception as exc:
        if not is_unique_violation(exc):
            raise
        # Peer won the race — abandon orphan CognitiveSession, return winner.
        logger.info(
            "host binding race lost host=%s ext=%s occ=%s; abandoning %s",
            host_type, external_session_id, occurrence, started.session.id,
        )
        try:
            store.transition_session(
                started.session.id,
                SessionStatus.active.value,
                SessionStatus.abandoned.value,
                ended_at=now_iso(),
            )
        except Exception:
            logger.exception("failed to abandon orphan session %s", started.session.id)
        winner = store.find_active_host_session_binding(
            host_type=host_type, external_session_id=external_session_id,
        )
        if winner is None:
            raise
        pack = request_context_pack(
            store, cfg, embedder,
            query=query, binding=winner, cwd=cwd,
            max_tokens=max_tokens, client=host_type,
        )
        session = store.get_session(winner.cognitive_session_id)
        if session is None:
            raise ValueError(
                f"winning binding {winner.id} points at missing session"
            )
        return NativeSessionStart(
            binding=winner,
            started=SessionStart(
                session=session, pack=pack,
                reading_confidences={}, observer_mode="native",
            ),
        )
    return NativeSessionStart(binding=binding, started=started)


def resolve_active_binding(
    store: MemoryStore,
    *,
    host_type: str,
    external_session_id: str,
) -> Optional[HostSessionBinding]:
    if not external_session_id:
        return None
    return store.find_active_host_session_binding(
        host_type=host_type, external_session_id=external_session_id,
    )


def observe_host_event(
    store: MemoryStore,
    *,
    host_type: str,
    external_session_id: str,
    event_kind: str,
    note: str = "",
    ref: Optional[str] = None,
    event_id: Optional[str] = None,
    delivery_id: Optional[str] = None,
    sequence: Optional[int] = None,
    tool_call_id: Optional[str] = None,
    tool_phase: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
    redacted: bool = False,
    redaction_categories: Optional[list[str]] = None,
) -> ObserveResult:
    """Record a host observation on the *active* binding (idempotent)."""
    if event_kind not in ALLOWED_OBSERVE_KINDS:
        raise ValueError(f"unsupported observation kind: {event_kind}")
    binding = resolve_active_binding(
        store, host_type=host_type, external_session_id=external_session_id,
    )
    if binding is None:
        raise ValueError(
            f"no active binding for {host_type}:{external_session_id}"
        )
    eid = resolve_observation_event_id(
        event_id=event_id,
        delivery_id=delivery_id,
        tool_call_id=tool_call_id,
        tool_phase=tool_phase,
        kind=event_kind,
        sequence=sequence,
    )
    inserted = store.insert_host_observed_event(
        host_type=host_type,
        external_session_id=external_session_id,
        occurrence=binding.occurrence,
        event_id=eid,
        binding_id=binding.id,
        kind=event_kind,
        created_at=now_iso(),
    )
    if not inserted:
        return ObserveResult(binding=binding, duplicated=True)

    artifact: dict[str, Any] = {
        "kind": event_kind,
        "host_type": host_type,
        "event_id": eid,
        "occurrence": binding.occurrence,
    }
    if note:
        artifact["note"] = note
    if ref:
        artifact["ref"] = ref
    if tool_call_id:
        artifact["tool_call_id"] = tool_call_id
    if tool_phase:
        artifact["tool_phase"] = tool_phase
    if redacted:
        artifact["redacted"] = True
        artifact["redaction_categories"] = list(redaction_categories or [])
    if extra:
        artifact["host"] = extra
    observe_session(store, binding.cognitive_session_id, artifact)
    return ObserveResult(binding=binding, duplicated=False)


def request_context_pack(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    *,
    query: str,
    binding: Optional[HostSessionBinding] = None,
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
    """Proactive Context Pack — assembled only by the cognitive core.

    When ``binding`` is set, frozen security fields win; divergent caller
    fields must already have been rejected by the caller.
    """
    from ..privacy.identity import ensure_local_identity, resolve_access
    from ..privacy.yaml_io import bootstrap_policy_set
    from .observer import read_context

    if binding is not None:
        session_id = binding.cognitive_session_id
        domain = binding.domain
        project_id = binding.project_id
        task_profile = binding.task_profile or task_profile
        persona = binding.persona or persona
        purpose = binding.purpose or purpose
        audience = binding.audience or audience
        client = binding.host_type or client
    else:
        project_id = None
        if project:
            found = store.get_project(project) or store.find_project(project)
            if found is None:
                raise ValueError(f"project {project!r} not found")
            project_id = found.id

    reading = read_context(store, cfg, query, cwd=cwd)
    if binding is None:
        if project_id is None:
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
    # Frozen vault is an explicit pack invariant: session/project resolve the
    # same vault; binding.vault_id is the audit anchor and cannot widen silently.
    if binding is not None and binding.vault_id:
        access = access.model_copy(update={
            "metadata": {
                **(access.metadata or {}),
                "frozen_vault_id": binding.vault_id,
                "frozen_domain": binding.domain,
            },
        })
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
) -> Optional[HostSessionBinding]:
    """End the active binding. Returns None when no active binding (orphan Stop)."""
    binding = resolve_active_binding(
        store, host_type=host_type, external_session_id=external_session_id,
    )
    if binding is None:
        logger.warning(
            "session_end with no active binding host=%s ext=%s (no-op)",
            host_type, external_session_id,
        )
        return None
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
    """Heuristic *possible decision reversal cue* (display-only).

    Not a semantic contradiction detector. May false-positive; never modifies
    host state. Stronger actions require a future semantic model.
    """
    text = (draft_text or "").strip()
    if not text:
        return []
    session = store.get_session(session_id)
    if session is None:
        return []

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
        hay = f"{mem.title} {mem.summary}".lower()
        tokens = [t for t in hay.replace(",", " ").split() if len(t) >= 4][:12]
        overlap = sum(1 for t in tokens if t in lowered)
        if overlap < 2 and not (has_reverse and overlap >= 1):
            continue
        urgency = "high" if has_reverse and overlap >= 2 else "medium"
        out.append(InterventionRecommendation(
            type="warning",
            reason=(
                f"Possible decision reversal cue vs confirmed decision "
                f"{mem.id}: {mem.title}"
            ),
            urgency=urgency,
            session_id=session_id,
            supported_actions=["display"],
            requires_confirmation=False,
            metadata={
                "memory_id": mem.id,
                "overlap": overlap,
                "heuristic": "token_overlap_reverse_cue",
            },
        ))
        if len(out) >= limit:
            break
    return out
