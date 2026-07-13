"""Cognitive session lifecycle.

A session closes the read-only flow (twin → LLM) into a maintained loop:

    session_start     → identify project/domain/task, supply a context pack
    session_observe   → record artifacts produced or changed during the work
    session_complete  → turn what happened into a percept and candidate memories
    session_feedback  → record explicit usefulness feedback

Sessions are the unit product metrics hang from: what was supplied, what
came back, and whether it was actually useful.

Design rules this module enforces:

- ambiguity fails visibly and conservatively — an unknown explicit project
  raises instead of being replaced by inference, and an unclassified domain
  yields an empty (default-deny) pack plus ``needs_domain_confirmation``;
- completion (the work ended) and consolidation (twin learned from it) are
  separate states: consolidation is idempotent and retryable, anchored on a
  deterministic percept dedup key;
- artifact and feedback writes are append-only store operations, safe under
  concurrent clients.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .. import ids
from ..clock import now_iso
from ..config import UNCLASSIFIED_DOMAIN, Config
from ..memory.embeddings import Embedder
from ..memory.models import (
    FEEDBACK_SCOPES,
    CognitiveSession,
    ConsolidationStatus,
    FeedbackVerdict,
    Project,
    SessionStatus,
)
from ..memory.store.base import MemoryStore
from ..sensory.percept import Percept
from .context_pack import ContextPack, build_context_pack
from .observer import read_context
from .pipeline import extract_percept

logger = logging.getLogger("twin.cognition.sessions")

# How much a session summary can be trusted depends on who wrote it, not on
# the fact that it arrived through a session. "user" means the human typed
# or explicitly confirmed it; "derived" means deterministically assembled
# from verified artifacts; "client" is a free-form program-supplied text;
# "assistant" is an LLM's own unconfirmed account of what it did.
SUMMARY_TRUST = {"user": 0.9, "derived": 0.85, "client": 0.7, "assistant": 0.6}
DEFAULT_STALE_HOURS = 24.0


@dataclass
class SessionStart:
    session: CognitiveSession
    pack: ContextPack
    reading_confidences: dict[str, float]
    observer_mode: str
    needs_domain_confirmation: bool = False
    observer_fallback: Optional[str] = None


def start_session(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    query: str,
    client: str = "unknown",
    cwd: Optional[str] = None,
    domain: Optional[str] = None,
    project: Optional[str] = None,      # explicit project name/alias/id
    task_profile: Optional[str] = None,
    max_tokens: int = 1200,
    include_candidates: bool = False,
    persona: str = "individual",
    purpose: str = "task_execution",
    audience: str = "self",
    tool_id: Optional[str] = None,
) -> SessionStart:
    """Identify project/domain/task profile (unless given explicitly), build
    a task-aware pack and open the session that records what was supplied.

    An explicit ``project`` that cannot be resolved raises ValueError —
    inference never silently substitutes an explicit argument. When neither
    the caller nor observation can name a domain, the session opens as
    ``unclassified``: the firewall blocks all memories, the pack carries no
    judgment, and ``needs_domain_confirmation`` asks the client to confirm.
    """
    reading = read_context(store, cfg, query, cwd=cwd)

    if project:
        found = store.get_project(project) or store.find_project(project)
        if found is None:
            raise ValueError(f"project {project!r} not found — create it first "
                             "or omit it to let twin infer the project")
        project_id: Optional[str] = found.id
        if reading.project_id and reading.project_id != found.id:
            logger.info("explicit project %s overrides inferred %s",
                        found.id, reading.project_id)
    else:
        project_id = reading.project_id

    session_domain = domain or reading.domain
    needs_confirmation = session_domain == UNCLASSIFIED_DOMAIN

    started_at = now_iso()
    # Never treat the placeholder client name "unknown" as a tool identity —
    # that would trip restricted-mode default-deny.
    if tool_id:
        tool = tool_id
    elif client and client not in ("unknown", ""):
        tool = client
    else:
        tool = "local-cli"
    session = CognitiveSession(
        id=ids.session_id(),
        client=client,
        project_id=project_id,
        domain=session_domain,
        task_profile=task_profile or reading.task_profile,
        initial_query=query,
        started_at=started_at,
        last_activity_at=started_at,
        principal_id=f"tool_{tool}",
        persona=persona,
        purpose=purpose,
        audience=audience,
        tool_id=tool,
    )
    from ..privacy.models import AccessRequest
    access = AccessRequest(
        principal_id=session.principal_id or f"tool_{tool}",
        persona=persona,
        purpose=purpose,
        audience=audience,
        tool_id=tool,
        project_id=project_id,
        session_id=session.id,
        requested_domains=[session_domain],
    )
    pack = build_context_pack(
        store, cfg, embedder, query,
        target_domain=session.domain, max_tokens=max_tokens,
        include_candidates=include_candidates,
        # an unconfirmed domain gets nothing, not even the judgment profile
        include_judgment=not needs_confirmation,
        task_profile=session.task_profile, project_id=project_id,
        access=access,
    )
    session.supplied_memory_ids = [s["memory_id"] for s in pack.sources]
    session.pack_chars = len(pack.context_pack)
    session.judgment_snapshot_id = pack.judgment_snapshot_id
    session.privacy_decision_ids = (
        [pack.privacy_decision_id] if pack.privacy_decision_id else []
    )
    session.grant_ids = list((pack.privacy_meta or {}).get("grant_ids") or [])
    session.policy_snapshot_id = (pack.privacy_meta or {}).get("policy_set_version")
    store.insert_session(session)
    return SessionStart(
        session=session, pack=pack,
        reading_confidences=reading.confidences, observer_mode=reading.mode,
        needs_domain_confirmation=needs_confirmation,
        observer_fallback=reading.fallback_reason,
    )


def observe_session(store: MemoryStore, session_id: str,
                    artifact: dict[str, Any]) -> CognitiveSession:
    """Record an artifact produced or changed during the session — a file,
    commit, PR, document or free-form note ({kind, ref?, note?, percept_id?}).

    When the artifact was already ingested by a sensor, pass its
    ``percept_id``: the session then references the verified percept instead
    of duplicating text, and consolidation will not re-extract the note.

    The append is atomic at the store level: concurrent observers never
    overwrite each other, and a session that is no longer active rejects
    the write instead of absorbing it silently."""
    if not str(artifact.get("kind", "")).strip():
        raise ValueError("artifact needs a non-empty 'kind'")
    store.append_session_artifact(session_id, {**artifact, "at": now_iso()})
    return store.get_session(session_id)


def complete_session(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    session_id: str,
    summary: str = "",
    abandoned: bool = False,
    summary_origin: str = "client",   # user | assistant | client | derived
    user_confirmed: bool = False,
) -> CognitiveSession:
    """Close the session and consolidate what happened.

    Completion is a compare-and-set transition (two concurrent completes
    cannot both win). Consolidation — summary + artifact notes become a
    percept, extraction turns it into candidate memories — is tracked in
    ``consolidation_status`` and is retryable: calling complete again on a
    session whose consolidation failed re-runs only the consolidation,
    without duplicating percepts or memories (the percept dedup key is
    derived from the session id)."""
    if summary_origin not in SUMMARY_TRUST:
        raise ValueError(f"summary_origin must be one of {sorted(SUMMARY_TRUST)}")
    session = store.get_session(session_id)
    if session is None:
        raise ValueError(f"session {session_id} not found")

    if session.status == SessionStatus.active:
        target = SessionStatus.abandoned if abandoned else SessionStatus.completed
        if not store.transition_session(session_id, SessionStatus.active.value,
                                        target.value, ended_at=now_iso()):
            raise ValueError(f"session {session_id} was concurrently transitioned")
        session = store.get_session(session_id)
    elif (session.status == SessionStatus.completed
          and session.consolidation_status == ConsolidationStatus.failed
          and not abandoned):
        pass  # retry path: only consolidation runs again
    else:
        raise ValueError(
            f"session {session_id} is {session.status.value} "
            f"(consolidation: {session.consolidation_status.value}), not completable"
        )

    if abandoned:
        session.consolidation_status = ConsolidationStatus.skipped
        store.update_session(session)
        return session

    lines = [summary] if summary else []
    for artifact in session.artifacts:
        if artifact.get("percept_id"):
            continue  # already a first-class percept — never duplicated as text
        note = artifact.get("note") or artifact.get("ref") or ""
        if note:
            lines.append(f"[{artifact.get('kind', 'artifact')}] {note}")
    if not lines:
        session.consolidation_status = ConsolidationStatus.skipped
        store.update_session(session)
        return session

    return _consolidate(store, cfg, embedder, session, lines,
                        summary_origin, user_confirmed)


def _consolidate(store: MemoryStore, cfg: Config, embedder: Embedder,
                 session: CognitiveSession, lines: list[str],
                 summary_origin: str, user_confirmed: bool) -> CognitiveSession:
    session.consolidation_status = ConsolidationStatus.pending
    session.consolidation_error = None
    store.update_session(session)
    try:
        trust = 0.9 if user_confirmed else SUMMARY_TRUST[summary_origin]
        percept = Percept(
            percept_type="session_summary",
            source_sensor="session",
            occurred_at=session.ended_at,
            ingested_at=now_iso(),
            actors=[],
            content="\n".join(lines),
            content_refs=[{"kind": "cognitive_session", "session_id": session.id}],
            privacy_hints={"domain_hint": session.domain},
            metadata={"summary_origin": summary_origin,
                      "user_confirmed": user_confirmed},
            source_trust=trust,
            source_scope=session.domain,
            source_confidentiality="internal",
            project_id=session.project_id,
        )
        # deterministic dedup key → a retry can never store a second percept
        percept.integrity["content_hash"] = f"session:{session.id}"
        percept.seal()
        if store.insert_percept(percept) is None:
            if session.summary_percept_id is None:
                raise RuntimeError("summary percept already stored but its id "
                                   "was lost — inspect the percepts table")
            percept = store.get_percept(session.summary_percept_id)
            if percept is None:
                raise RuntimeError(f"summary percept "
                                   f"{session.summary_percept_id} disappeared")
        session.summary_percept_id = percept.id

        report = extract_percept(store, cfg, embedder, percept)
        new_ids = [m for m in report.inserted if m not in session.created_memory_ids]
        session.created_memory_ids = session.created_memory_ids + new_ids
        if session.project_id:
            for mid in new_ids:
                store.update_memory(mid, project_id=session.project_id)
        if session.judgment_snapshot_id:
            for mid in new_ids:
                mem = store.get_memory(mid)
                if mem is None:
                    continue
                payload = dict(mem.payload or {})
                payload["judgment_influenced"] = True
                payload["decision_origin"] = "twin_assisted"
                payload["judgment_snapshot_id"] = session.judgment_snapshot_id
                store.update_memory(mid, payload=payload)
        session.consolidation_status = ConsolidationStatus.completed
    except Exception as exc:
        # never silent: the session stays diagnosable and retryable
        session.consolidation_status = ConsolidationStatus.failed
        session.consolidation_error = f"{type(exc).__name__}: {exc}"[:300]
        logger.warning("session %s consolidation failed: %s",
                       session.id, type(exc).__name__)
    store.update_session(session)
    return session


def record_feedback(store: MemoryStore, session_id: str, verdict: str,
                    memory_id: Optional[str] = None, note: str = "",
                    scope: Optional[str] = None) -> CognitiveSession:
    """Explicit usefulness feedback — the raw material of product metrics.

    ``scope`` says what the verdict is about: the whole ``session``, the
    supplied ``pack``, or one ``memory`` (implied when memory_id is given).
    A memory_id must exist and must have been part of this session (supplied
    in the pack or created by it) — feedback about foreign memories would
    silently corrupt the usage metrics."""
    FeedbackVerdict(verdict)  # raises ValueError on unknown verdicts
    session = store.get_session(session_id)
    if session is None:
        raise ValueError(f"session {session_id} not found")

    if memory_id:
        if store.get_memory(memory_id) is None:
            raise ValueError(f"memory {memory_id} not found")
        if memory_id not in session.supplied_memory_ids + session.created_memory_ids:
            raise ValueError(f"memory {memory_id} was not supplied by or created "
                             f"in session {session_id}")
        scope = scope or "memory"
    else:
        scope = scope or "session"
    if scope not in FEEDBACK_SCOPES:
        raise ValueError(f"scope must be one of {FEEDBACK_SCOPES}")
    if scope == "memory" and not memory_id:
        raise ValueError("scope='memory' requires memory_id")

    store.append_session_feedback(session_id, {
        "scope": scope,
        "verdict": verdict,
        "memory_id": memory_id,
        "note": note,
        "at": now_iso(),
    })
    return store.get_session(session_id)


def ensure_project(store: MemoryStore, name: str, repos: Optional[list[str]] = None,
                   aliases: Optional[list[str]] = None) -> Project:
    """Create the project or merge new repos/aliases into the existing one —
    calling it again with more signals enriches the project instead of
    silently discarding them."""
    existing = store.find_project(name)
    if existing is not None:
        changed = False
        for repo in repos or []:
            if repo.lower() not in {r.lower() for r in existing.repos}:
                existing.repos.append(repo)
                changed = True
        current = {existing.name.lower()} | {a.lower() for a in existing.aliases}
        for alias in aliases or []:
            if alias.lower() not in current:
                existing.aliases.append(alias)
                changed = True
        if changed:
            store.update_project(existing)
        return existing
    project = Project(id=ids.project_id(), name=name,
                      repos=repos or [], aliases=aliases or [])
    store.insert_project(project)
    return project


def stale_sessions(store: MemoryStore,
                   max_idle_hours: float = DEFAULT_STALE_HOURS) -> list[CognitiveSession]:
    """Active sessions with no activity for longer than ``max_idle_hours``."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_idle_hours)).isoformat()
    return [
        s for s in store.list_sessions(status=SessionStatus.active.value, limit=10000)
        if (s.last_activity_at or s.started_at) < cutoff
    ]


def abandon_stale_sessions(store: MemoryStore,
                           max_idle_hours: float = DEFAULT_STALE_HOURS) -> list[str]:
    """Mark stale active sessions as abandoned. Returns the ids affected."""
    abandoned: list[str] = []
    for session in stale_sessions(store, max_idle_hours):
        if store.transition_session(session.id, SessionStatus.active.value,
                                    SessionStatus.abandoned.value, ended_at=now_iso()):
            session = store.get_session(session.id)
            session.consolidation_status = ConsolidationStatus.skipped
            store.update_session(session)
            abandoned.append(session.id)
    return abandoned
