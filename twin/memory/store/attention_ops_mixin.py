"""Attention emission ledger."""

from __future__ import annotations

import json
from typing import Any, Optional

from twin.clock import now_iso
from twin.cognition.attention import AttentionKind, AttentionOutcome


ATTENTION_OPS_SCHEMA = """
CREATE TABLE IF NOT EXISTS attention_emissions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'silence',
    memory_id TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    expected_value REAL NOT NULL DEFAULT 0,
    relevance REAL NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_attention_session
    ON attention_emissions(session_id, status, created_at);

CREATE TABLE IF NOT EXISTS attention_suppressions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT '',
    memory_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_attention_suppress
    ON attention_suppressions(session_id, kind, memory_id);
"""


def _dumps(obj: Any) -> str:
    return json.dumps(obj or {}, default=str)


def _loads(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    return json.loads(raw or "{}")


def row_to_emission(row: Any) -> AttentionOutcome:
    kind_raw = row["kind"] or "silence"
    try:
        kind = AttentionKind(kind_raw)
    except ValueError:
        kind = AttentionKind.silence
    return AttentionOutcome(
        id=row["id"],
        session_id=row["session_id"],
        kind=kind,
        memory_id=row["memory_id"] or "",
        summary=row["summary"] or "",
        reason=row["reason"] or "",
        expected_value=float(row["expected_value"] or 0),
        relevance=float(row["relevance"] or 0),
        confidence=float(row["confidence"] or 0),
        status=row["status"] or "open",
        created_at=row["created_at"] or "",
        payload=_loads(row["payload"]),
    )


class AttentionOpsStoreMixin:
    def insert_attention_emission(self, em: AttentionOutcome) -> str:
        if not em.created_at:
            em.created_at = now_iso()
        kind = em.kind.value if hasattr(em.kind, "value") else str(em.kind)
        self._j_exec(
            "INSERT INTO attention_emissions (id, session_id, kind, memory_id, summary,"
            " reason, expected_value, relevance, confidence, status, created_at, payload)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                em.id, em.session_id, kind, em.memory_id or "", em.summary or "",
                em.reason or "", float(em.expected_value), float(em.relevance),
                float(em.confidence), em.status or "open", em.created_at,
                _dumps(em.payload),
            ),
        )
        self._j_commit()
        return em.id

    def update_attention_emission(self, em: AttentionOutcome) -> None:
        kind = em.kind.value if hasattr(em.kind, "value") else str(em.kind)
        self._j_exec(
            "UPDATE attention_emissions SET kind=?, memory_id=?, summary=?, reason=?,"
            " expected_value=?, relevance=?, confidence=?, status=?, payload=?"
            " WHERE id=?",
            (
                kind, em.memory_id or "", em.summary or "", em.reason or "",
                float(em.expected_value), float(em.relevance), float(em.confidence),
                em.status, _dumps(em.payload), em.id,
            ),
        )
        self._j_commit()

    def get_attention_emission(self, emission_id: str) -> Optional[AttentionOutcome]:
        row = self._j_fetchone(
            "SELECT * FROM attention_emissions WHERE id = ?", (emission_id,),
        )
        return row_to_emission(row) if row else None

    def list_attention_emissions(
        self,
        session_id: str,
        *,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[AttentionOutcome]:
        if status:
            rows = self._j_fetchall(
                "SELECT * FROM attention_emissions WHERE session_id = ? AND status = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (session_id, status, limit),
            )
        else:
            rows = self._j_fetchall(
                "SELECT * FROM attention_emissions WHERE session_id = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            )
        return [row_to_emission(r) for r in rows]

    def supersede_attention_emissions(self, session_id: str, *, reason: str = "") -> int:
        cur = self._j_exec(
            "UPDATE attention_emissions SET status = 'superseded'"
            " WHERE session_id = ? AND status = 'open' AND kind != 'silence'",
            (session_id,),
        )
        self._j_commit()
        return int(getattr(cur, "rowcount", 0) or 0)

    def add_attention_suppression(
        self, session_id: str, *, kind: str = "", memory_id: str = "",
    ) -> None:
        from twin import ids

        self._j_exec(
            "INSERT INTO attention_suppressions"
            " (id, session_id, kind, memory_id, created_at) VALUES (?,?,?,?,?)",
            (ids.new_id("asup"), session_id, kind or "", memory_id or "", now_iso()),
        )
        self._j_commit()

    def is_attention_suppressed(
        self, session_id: str, *, kind: str = "", memory_id: str = "",
    ) -> bool:
        row = self._j_fetchone(
            "SELECT id FROM attention_suppressions WHERE session_id = ?"
            " AND (kind = '' OR kind = ?) AND (memory_id = '' OR memory_id = ?)"
            " LIMIT 1",
            (session_id, kind or "", memory_id or ""),
        )
        return row is not None
