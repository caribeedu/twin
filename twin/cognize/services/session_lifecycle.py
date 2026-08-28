"""Closed cognitive session ops — deltas, checkpoints, structured closure.

Extends the existing CognitiveSession loop without replacing it. Completion
still uses ``complete_session``; this module adds ordered events, checkpoints,
pause/reopen, and a structured ``SessionClosure`` that never auto-confirms
Memory or Judgment.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from twin import ids
from twin.clock import now_iso
from twin.config import Config
from twin.store.embeddings import Embedder
from twin.store.models import CognitiveSession, SessionStatus
from twin.store.store.base import TwinStore
from twin.cognize.services.sessions import complete_session


class SessionEvent(BaseModel):
    id: str = Field(default_factory=ids.session_event_id)
    session_id: str
    sequence: int
    kind: str = "delta"  # delta | note | tool | gap | checkpoint_marker
    payload: dict[str, Any] = Field(default_factory=dict)
    external_session_id: str = ""
    client: str = ""
    created_at: str = Field(default_factory=now_iso)


class SessionCheckpoint(BaseModel):
    id: str = Field(default_factory=ids.session_checkpoint_id)
    session_id: str
    sequence: int
    summary: str = ""
    active_goal: str = ""
    unresolved_items: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    event_count: int = 0
    gap_detected: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


class SessionClosure(BaseModel):
    """Structured close — candidates only; never auto-confirms Narratives/Stances."""

    id: str = Field(default_factory=ids.session_closure_id)
    session_id: str
    what_happened: str = ""
    what_changed: list[str] = Field(default_factory=list)
    decisions_observed: list[str] = Field(default_factory=list)
    undecided_proposals: list[str] = Field(default_factory=list)
    tasks_commitments: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    rejected_alternatives: list[str] = Field(default_factory=list)
    possible_contradictions: list[str] = Field(default_factory=list)
    memory_candidates: list[str] = Field(default_factory=list)
    review_required: list[str] = Field(default_factory=list)
    related_session_ids: list[str] = Field(default_factory=list)
    outcome_summary: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


def pause_session(store: TwinStore, session_id: str) -> CognitiveSession:
    if not store.transition_session(
        session_id, SessionStatus.active.value, SessionStatus.paused.value,
    ):
        raise ValueError(f"session {session_id} not active — cannot pause")
    return store.get_session(session_id)


def resume_session(store: TwinStore, session_id: str) -> CognitiveSession:
    if not store.transition_session(
        session_id, SessionStatus.paused.value, SessionStatus.active.value,
    ):
        raise ValueError(f"session {session_id} not paused — cannot resume")
    return store.get_session(session_id)


def reopen_session(store: TwinStore, session_id: str) -> CognitiveSession:
    """Controlled reopen of completed/abandoned → active (clears ended_at)."""
    session = store.get_session(session_id)
    if session is None:
        raise ValueError(f"session {session_id} not found")
    st = session.status.value if hasattr(session.status, "value") else str(session.status)
    if st not in (SessionStatus.completed.value, SessionStatus.abandoned.value,
                  SessionStatus.paused.value):
        raise ValueError(f"session {session_id} is {st}, not reopenable")
    if not store.transition_session(session_id, st, SessionStatus.active.value):
        raise ValueError(f"session {session_id} concurrently transitioned")
    session = store.get_session(session_id)
    session.ended_at = None
    store.update_session(session)
    return store.get_session(session_id)


def archive_session(store: TwinStore, session_id: str) -> CognitiveSession:
    session = store.get_session(session_id)
    if session is None:
        raise ValueError(f"session {session_id} not found")
    st = session.status.value if hasattr(session.status, "value") else str(session.status)
    if st not in (SessionStatus.completed.value, SessionStatus.abandoned.value):
        raise ValueError(f"session {session_id} must be completed/abandoned to archive")
    if not store.transition_session(session_id, st, SessionStatus.archived.value):
        raise ValueError(f"session {session_id} concurrently transitioned")
    return store.get_session(session_id)


def append_session_delta(
    store: TwinStore,
    session_id: str,
    *,
    text: str = "",
    kind: str = "delta",
    sequence: Optional[int] = None,
    external_session_id: str = "",
    client: str = "",
    payload: Optional[dict[str, Any]] = None,
) -> SessionEvent:
    """Append an ordered session event. Detects sequence gaps."""
    session = store.get_session(session_id)
    if session is None:
        raise ValueError(f"session {session_id} not found")
    st = session.status.value if hasattr(session.status, "value") else str(session.status)
    if st not in (SessionStatus.active.value, SessionStatus.paused.value):
        raise ValueError(f"session {session_id} is {st}, not accepting deltas")

    last_seq = store.max_session_event_sequence(session_id)
    if sequence is None:
        sequence = last_seq + 1
    gap = sequence > last_seq + 1
    body = dict(payload or {})
    if text:
        body["text"] = text
    if gap:
        body["gap_from"] = last_seq
        body["gap_to"] = sequence
        # Record gap marker first (best-effort audit)
        store.insert_session_event(SessionEvent(
            session_id=session_id,
            sequence=last_seq + 1 if last_seq >= 0 else 0,
            kind="gap",
            payload={"expected_next": last_seq + 1, "got": sequence},
            external_session_id=external_session_id,
            client=client,
        ))
    event = SessionEvent(
        session_id=session_id,
        sequence=sequence,
        kind=kind,
        payload=body,
        external_session_id=external_session_id,
        client=client,
    )
    store.insert_session_event(event)
    session.last_activity_at = now_iso()
    store.update_session(session)
    # Continuous attention: enqueue durable evaluate job (not an agent).
    if text and hasattr(store, "insert_runtime_job"):
        try:
            from twin.cognize.services.attention import maybe_enqueue_attention_job
            maybe_enqueue_attention_job(store, session_id, text=text)
        except Exception:
            pass
    return event


def checkpoint_session(
    store: TwinStore,
    session_id: str,
    *,
    summary: str = "",
    active_goal: str = "",
    unresolved_items: Optional[list[str]] = None,
    constraints: Optional[list[str]] = None,
) -> SessionCheckpoint:
    session = store.get_session(session_id)
    if session is None:
        raise ValueError(f"session {session_id} not found")
    events = store.list_session_events(session_id, limit=10_000)
    last_seq = events[-1].sequence if events else 0
    gap = any(e.kind == "gap" for e in events)
    # Incremental summary: prefer caller text, else concatenate recent deltas
    if not summary:
        bits = [
            (e.payload or {}).get("text", "")
            for e in events[-20:]
            if e.kind == "delta" and (e.payload or {}).get("text")
        ]
        summary = " | ".join(bits)[:2000]
    cp = SessionCheckpoint(
        session_id=session_id,
        sequence=last_seq,
        summary=summary,
        active_goal=active_goal or getattr(session, "active_goal", "") or "",
        unresolved_items=list(unresolved_items or []),
        constraints=list(constraints or []),
        event_count=len(events),
        gap_detected=gap,
    )
    store.insert_session_checkpoint(cp)
    session.last_activity_at = now_iso()
    store.update_session(session)
    return cp


def close_session_structured(
    store: TwinStore,
    cfg: Config,
    embedder: Embedder,
    session_id: str,
    *,
    summary: str = "",
    abandoned: bool = False,
    closure: Optional[dict[str, Any]] = None,
    related_session_ids: Optional[list[str]] = None,
    summary_origin: str = "client",
    user_confirmed: bool = False,
) -> tuple[CognitiveSession, SessionClosure]:
    """Complete the session and persist a structured closure record.

    Closure never auto-confirms Narratives or Stances — only records candidates /
    observations for later review.
    """
    session = complete_session(
        store, cfg, embedder, session_id,
        summary=summary,
        abandoned=abandoned,
        summary_origin=summary_origin,
        user_confirmed=user_confirmed,
    )
    c = dict(closure or {})
    sc = SessionClosure(
        session_id=session_id,
        what_happened=c.get("what_happened") or summary or session.initial_query,
        what_changed=list(c.get("what_changed") or []),
        decisions_observed=list(c.get("decisions_observed") or []),
        undecided_proposals=list(c.get("undecided_proposals") or []),
        tasks_commitments=list(c.get("tasks_commitments") or []),
        constraints=list(c.get("constraints") or []),
        open_questions=list(c.get("open_questions") or []),
        rejected_alternatives=list(c.get("rejected_alternatives") or []),
        possible_contradictions=list(c.get("possible_contradictions") or []),
        memory_candidates=list(
            c.get("memory_candidates") or session.created_claim_ids or []
        ),
        review_required=list(c.get("review_required") or []),
        related_session_ids=list(related_session_ids or c.get("related_session_ids") or []),
        outcome_summary=c.get("outcome_summary") or summary or "",
        provenance={
            "client": session.client,
            "domain": session.domain,
            "persona": session.persona,
            "project_id": session.project_id,
            "consolidation_status": (
                session.consolidation_status.value
                if hasattr(session.consolidation_status, "value")
                else str(session.consolidation_status)
            ),
            "summary_percept_id": session.summary_percept_id,
            "confirms_memory": False,
            "confirms_judgment": False,
        },
    )
    store.insert_session_closure(sc)
    return session, sc


def get_session_closure(store: TwinStore, session_id: str) -> Optional[SessionClosure]:
    return store.get_session_closure(session_id)
