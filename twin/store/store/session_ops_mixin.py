"""Session events / checkpoints / closures persistence."""

from __future__ import annotations

import json
from typing import Any, Optional

from twin.clock import now_iso
from twin.cognition.session_lifecycle import (
    SessionCheckpoint,
    SessionClosure,
    SessionEvent,
)


SESSION_OPS_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'delta',
    payload TEXT NOT NULL DEFAULT '{}',
    external_session_id TEXT NOT NULL DEFAULT '',
    client TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_session_event_seq
    ON session_events(session_id, sequence);
CREATE INDEX IF NOT EXISTS idx_session_events_sid
    ON session_events(session_id, sequence);

CREATE TABLE IF NOT EXISTS session_checkpoints (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    sequence INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    active_goal TEXT NOT NULL DEFAULT '',
    unresolved_items TEXT NOT NULL DEFAULT '[]',
    constraints TEXT NOT NULL DEFAULT '[]',
    event_count INTEGER NOT NULL DEFAULT 0,
    gap_detected INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_session_checkpoints_sid
    ON session_checkpoints(session_id, created_at);

CREATE TABLE IF NOT EXISTS session_closures (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_session_closure_sid
    ON session_closures(session_id);
"""


def _dumps(obj: Any) -> str:
    return json.dumps(obj if obj is not None else {}, default=str)


def _loads_list(raw: Any) -> list:
    if isinstance(raw, list):
        return raw
    return json.loads(raw or "[]")


def _loads_dict(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    return json.loads(raw or "{}")


class SessionOpsStoreMixin:
    def insert_session_event(self, event: SessionEvent) -> str:
        if not event.created_at:
            event.created_at = now_iso()
        self._j_exec(
            "INSERT INTO session_events (id, session_id, sequence, kind, payload,"
            " external_session_id, client, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                event.id, event.session_id, int(event.sequence), event.kind,
                _dumps(event.payload), event.external_session_id or "",
                event.client or "", event.created_at,
            ),
        )
        self._j_commit()
        return event.id

    def max_session_event_sequence(self, session_id: str) -> int:
        row = self._j_fetchone(
            "SELECT MAX(sequence) AS m FROM session_events WHERE session_id = ?",
            (session_id,),
        )
        if row is None:
            return 0
        # sqlite Row / dict
        m = row["m"] if hasattr(row, "keys") else row[0]
        return int(m or 0)

    def list_session_events(
        self, session_id: str, *, limit: int = 1000,
    ) -> list[SessionEvent]:
        rows = self._j_fetchall(
            "SELECT * FROM session_events WHERE session_id = ?"
            " ORDER BY sequence ASC LIMIT ?",
            (session_id, limit),
        )
        out: list[SessionEvent] = []
        for r in rows:
            out.append(SessionEvent(
                id=r["id"],
                session_id=r["session_id"],
                sequence=int(r["sequence"]),
                kind=r["kind"] or "delta",
                payload=_loads_dict(r["payload"]),
                external_session_id=r["external_session_id"] or "",
                client=r["client"] or "",
                created_at=r["created_at"] or "",
            ))
        return out

    def insert_session_checkpoint(self, cp: SessionCheckpoint) -> str:
        if not cp.created_at:
            cp.created_at = now_iso()
        self._j_exec(
            "INSERT INTO session_checkpoints (id, session_id, sequence, summary,"
            " active_goal, unresolved_items, constraints, event_count,"
            " gap_detected, payload, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                cp.id, cp.session_id, int(cp.sequence), cp.summary or "",
                cp.active_goal or "", _dumps(cp.unresolved_items),
                _dumps(cp.constraints), int(cp.event_count),
                1 if cp.gap_detected else 0, _dumps(cp.payload), cp.created_at,
            ),
        )
        self._j_commit()
        return cp.id

    def list_session_checkpoints(
        self, session_id: str, *, limit: int = 100,
    ) -> list[SessionCheckpoint]:
        rows = self._j_fetchall(
            "SELECT * FROM session_checkpoints WHERE session_id = ?"
            " ORDER BY created_at ASC LIMIT ?",
            (session_id, limit),
        )
        out: list[SessionCheckpoint] = []
        for r in rows:
            out.append(SessionCheckpoint(
                id=r["id"],
                session_id=r["session_id"],
                sequence=int(r["sequence"]),
                summary=r["summary"] or "",
                active_goal=r["active_goal"] or "",
                unresolved_items=_loads_list(r["unresolved_items"]),
                constraints=_loads_list(r["constraints"]),
                event_count=int(r["event_count"] or 0),
                gap_detected=bool(int(r["gap_detected"] or 0)),
                payload=_loads_dict(r["payload"]),
                created_at=r["created_at"] or "",
            ))
        return out

    def insert_session_closure(self, closure: SessionClosure) -> str:
        if not closure.created_at:
            closure.created_at = now_iso()
        self._j_exec(
            "INSERT INTO session_closures (id, session_id, body, created_at)"
            " VALUES (?,?,?,?)"
            " ON CONFLICT(session_id) DO UPDATE SET body = excluded.body,"
            " created_at = excluded.created_at, id = excluded.id",
            (
                closure.id, closure.session_id,
                _dumps(closure.model_dump(mode="json")),
                closure.created_at,
            ),
        )
        self._j_commit()
        return closure.id

    def get_session_closure(self, session_id: str) -> Optional[SessionClosure]:
        row = self._j_fetchone(
            "SELECT body FROM session_closures WHERE session_id = ?",
            (session_id,),
        )
        if row is None:
            return None
        body = _loads_dict(row["body"])
        return SessionClosure.model_validate(body)
