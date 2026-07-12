"""Cognitive session lifecycle.

A session closes the read-only flow (twin → LLM) into a maintained loop:

    session_start     → identify project/domain/task, supply a context pack
    session_observe   → record artifacts produced or changed during the work
    session_complete  → turn what happened into a percept and candidate memories
    session_feedback  → record explicit usefulness feedback

Sessions are the unit product metrics hang from: what was supplied, what
came back, and whether it was actually useful.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .. import ids
from ..clock import now_iso
from ..config import Config
from ..memory.embeddings import Embedder
from ..memory.models import CognitiveSession, FeedbackVerdict, Project, SessionStatus
from ..memory.store.base import MemoryStore
from ..sensory.percept import Percept
from .context_pack import ContextPack, build_context_pack
from .observer import read_context
from .pipeline import extract_percept


@dataclass
class SessionStart:
    session: CognitiveSession
    pack: ContextPack
    reading_confidences: dict[str, float]
    observer_mode: str


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
) -> SessionStart:
    """Identify project/domain/task profile (unless given explicitly), build
    a task-aware pack and open the session that records what was supplied."""
    reading = read_context(store, cfg, query, cwd=cwd)

    project_id: Optional[str] = None
    if project:
        found = store.get_project(project) or store.find_project(project)
        project_id = found.id if found else None
    if project_id is None:
        project_id = reading.project_id

    session = CognitiveSession(
        id=ids.session_id(),
        client=client,
        project_id=project_id,
        domain=domain or reading.domain,
        task_profile=task_profile or reading.task_profile,
        initial_query=query,
        started_at=now_iso(),
    )
    pack = build_context_pack(
        store, cfg, embedder, query,
        target_domain=session.domain, max_tokens=max_tokens,
        include_candidates=include_candidates,
        task_profile=session.task_profile, project_id=project_id,
    )
    session.supplied_memory_ids = [s["memory_id"] for s in pack.sources]
    session.pack_chars = len(pack.context_pack)
    store.insert_session(session)
    return SessionStart(
        session=session, pack=pack,
        reading_confidences=reading.confidences, observer_mode=reading.mode,
    )


def observe_session(store: MemoryStore, session_id: str,
                    artifact: dict[str, Any]) -> CognitiveSession:
    """Record an artifact produced or changed during the session — a file,
    commit, PR, document or free-form note ({kind, ref?, note?})."""
    session = _require_active(store, session_id)
    session.artifacts.append({**artifact, "at": now_iso()})
    store.update_session(session)
    return session


def complete_session(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    session_id: str,
    summary: str = "",
    abandoned: bool = False,
) -> CognitiveSession:
    """Close the session. When a summary of what happened is provided (or
    artifacts were observed), it becomes a percept and goes through the
    normal extraction pipeline — decisions and changes made during the work
    turn into candidate memories linked to the session's project."""
    session = _require_active(store, session_id)
    session.status = SessionStatus.abandoned if abandoned else SessionStatus.completed
    session.ended_at = now_iso()

    if not abandoned:
        lines = []
        if summary:
            lines.append(summary)
        for artifact in session.artifacts:
            note = artifact.get("note") or artifact.get("ref") or ""
            if note:
                lines.append(f"[{artifact.get('kind', 'artifact')}] {note}")
        if lines:
            percept = Percept(
                percept_type="session_summary",
                source_sensor="session",
                occurred_at=session.ended_at,
                ingested_at=now_iso(),
                actors=[],
                content="\n".join(lines),
                content_refs=[{"kind": "cognitive_session", "session_id": session.id}],
                privacy_hints={"domain_hint": session.domain},
                # first-person account of completed work: high trust
                source_trust=0.9,
                source_scope=session.domain,
                source_confidentiality="internal",
                project_id=session.project_id,
            ).seal()
            if store.insert_percept(percept) is not None:
                report = extract_percept(store, cfg, embedder, percept)
                session.created_memory_ids = report.inserted
                for mid in report.inserted:
                    if session.project_id:
                        store.update_memory(mid, project_id=session.project_id)

    store.update_session(session)
    return session


def record_feedback(store: MemoryStore, session_id: str, verdict: str,
                    memory_id: Optional[str] = None, note: str = "") -> CognitiveSession:
    """Explicit usefulness feedback — the raw material of product metrics."""
    FeedbackVerdict(verdict)  # raises ValueError on unknown verdicts
    session = store.get_session(session_id)
    if session is None:
        raise ValueError(f"session {session_id} not found")
    session.feedback.append({
        "verdict": verdict,
        "memory_id": memory_id,
        "note": note,
        "at": now_iso(),
    })
    store.update_session(session)
    return session


def ensure_project(store: MemoryStore, name: str, repos: Optional[list[str]] = None,
                   aliases: Optional[list[str]] = None) -> Project:
    existing = store.find_project(name)
    if existing is not None:
        return existing
    project = Project(id=ids.project_id(), name=name,
                      repos=repos or [], aliases=aliases or [])
    store.insert_project(project)
    return project


def _require_active(store: MemoryStore, session_id: str) -> CognitiveSession:
    session = store.get_session(session_id)
    if session is None:
        raise ValueError(f"session {session_id} not found")
    if session.status != SessionStatus.active:
        raise ValueError(f"session {session_id} is {session.status.value}, not active")
    return session
