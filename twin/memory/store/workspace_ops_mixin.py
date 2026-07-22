"""Workspace tick + consolidation-run operational persistence (v0.8).

Identity / idempotency for synchronous workspace evaluation and scheduled
consolidation cycles. Not a background worker — just durable run records so
retries and concurrent callers do not duplicate interpretation or proposals.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from twin import ids
from twin.clock import now_iso
from twin.memory.store.host_binding_mixin import is_unique_violation


WORKSPACE_OPS_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspace_ticks (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL DEFAULT '',
    sequence INTEGER,
    content_hash TEXT NOT NULL DEFAULT '',
    input_mode TEXT NOT NULL DEFAULT 'snapshot',
    idempotency_key TEXT NOT NULL DEFAULT '',
    interpret INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    previous_tick_id TEXT NOT NULL DEFAULT '',
    percept_id TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT '',
    completed_at TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ws_tick_idem
    ON workspace_ticks(idempotency_key)
    WHERE idempotency_key != '';
CREATE UNIQUE INDEX IF NOT EXISTS uq_ws_tick_session_seq
    ON workspace_ticks(session_id, sequence)
    WHERE session_id != '' AND sequence IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_ws_tick_session_delta_hash
    ON workspace_ticks(session_id, content_hash, input_mode)
    WHERE session_id != '' AND input_mode = 'delta' AND interpret = 1
          AND content_hash != '';
CREATE INDEX IF NOT EXISTS idx_ws_tick_session
    ON workspace_ticks(session_id, started_at);

CREATE TABLE IF NOT EXISTS consolidation_runs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    dry_run INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TEXT NOT NULL DEFAULT '',
    completed_at TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_consol_window_apply
    ON consolidation_runs(kind, window_start, window_end)
    WHERE dry_run = 0;
CREATE INDEX IF NOT EXISTS idx_consol_kind_started
    ON consolidation_runs(kind, started_at);
"""


@dataclass
class WorkspaceTickRecord:
    id: str = ""
    session_id: str = ""
    sequence: Optional[int] = None
    content_hash: str = ""
    input_mode: str = "snapshot"
    idempotency_key: str = ""
    interpret: bool = False
    status: str = "pending"
    previous_tick_id: str = ""
    percept_id: str = ""
    started_at: str = ""
    completed_at: str = ""
    error: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id or "",
            "sequence": self.sequence,
            "content_hash": self.content_hash or "",
            "input_mode": self.input_mode or "snapshot",
            "idempotency_key": self.idempotency_key or "",
            "interpret": int(bool(self.interpret)),
            "status": self.status,
            "previous_tick_id": self.previous_tick_id or "",
            "percept_id": self.percept_id or "",
            "started_at": self.started_at or "",
            "completed_at": self.completed_at or "",
            "error": self.error or "",
            "payload": json.dumps(self.payload or {}, default=str),
        }


def _row_to_tick(row: Any) -> WorkspaceTickRecord:
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    raw = row["payload"] if "payload" in keys else "{}"
    payload = raw if isinstance(raw, dict) else json.loads(raw or "{}")
    seq = row["sequence"] if "sequence" in keys else None
    return WorkspaceTickRecord(
        id=row["id"],
        session_id=row["session_id"] or "",
        sequence=None if seq is None else int(seq),
        content_hash=row["content_hash"] or "",
        input_mode=row["input_mode"] or "snapshot",
        idempotency_key=row["idempotency_key"] or "",
        interpret=bool(row["interpret"]),
        status=row["status"] or "pending",
        previous_tick_id=row["previous_tick_id"] or "",
        percept_id=row["percept_id"] or "",
        started_at=row["started_at"] or "",
        completed_at=row["completed_at"] or "",
        error=row["error"] or "",
        payload=payload or {},
    )


@dataclass
class ConsolidationRunRecord:
    id: str = ""
    kind: str = "daily"
    window_start: str = ""
    window_end: str = ""
    dry_run: bool = True
    status: str = "pending"
    started_at: str = ""
    completed_at: str = ""
    error: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "dry_run": int(bool(self.dry_run)),
            "status": self.status,
            "started_at": self.started_at or "",
            "completed_at": self.completed_at or "",
            "error": self.error or "",
            "payload": json.dumps(self.payload or {}, default=str),
        }


def _row_to_run(row: Any) -> ConsolidationRunRecord:
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    raw = row["payload"] if "payload" in keys else "{}"
    payload = raw if isinstance(raw, dict) else json.loads(raw or "{}")
    return ConsolidationRunRecord(
        id=row["id"],
        kind=row["kind"],
        window_start=row["window_start"],
        window_end=row["window_end"],
        dry_run=bool(row["dry_run"]),
        status=row["status"] or "pending",
        started_at=row["started_at"] or "",
        completed_at=row["completed_at"] or "",
        error=row["error"] or "",
        payload=payload or {},
    )


class WorkspaceOpsStoreMixin:
    """Duck-typed workspace/consolidation run store (uses connector SQL helpers)."""

    def insert_workspace_tick(self, tick: WorkspaceTickRecord) -> str:
        if not tick.id:
            tick.id = ids.new_id("wstk")
        if not tick.started_at:
            tick.started_at = now_iso()
        self._c_insert("workspace_ticks", tick.to_row())
        return tick.id

    def update_workspace_tick(self, tick: WorkspaceTickRecord) -> None:
        self._c_update("workspace_ticks", tick.id, tick.to_row())

    def get_workspace_tick(self, tick_id: str) -> Optional[WorkspaceTickRecord]:
        row = self._j_fetchone(
            "SELECT * FROM workspace_ticks WHERE id = ?", (tick_id,),
        )
        return _row_to_tick(row) if row else None

    def get_workspace_tick_by_idempotency_key(
        self, key: str,
    ) -> Optional[WorkspaceTickRecord]:
        if not key:
            return None
        row = self._j_fetchone(
            "SELECT * FROM workspace_ticks WHERE idempotency_key = ?", (key,),
        )
        return _row_to_tick(row) if row else None

    def get_workspace_tick_by_session_sequence(
        self, session_id: str, sequence: int,
    ) -> Optional[WorkspaceTickRecord]:
        if not session_id:
            return None
        row = self._j_fetchone(
            "SELECT * FROM workspace_ticks WHERE session_id = ? AND sequence = ?",
            (session_id, int(sequence)),
        )
        return _row_to_tick(row) if row else None

    def get_workspace_tick_by_session_delta_hash(
        self, session_id: str, content_hash: str,
    ) -> Optional[WorkspaceTickRecord]:
        if not session_id or not content_hash:
            return None
        row = self._j_fetchone(
            "SELECT * FROM workspace_ticks WHERE session_id = ? AND content_hash = ?"
            " AND input_mode = 'delta' AND interpret = 1"
            " ORDER BY started_at DESC LIMIT 1",
            (session_id, content_hash),
        )
        return _row_to_tick(row) if row else None

    def latest_workspace_tick_for_session(
        self, session_id: str,
    ) -> Optional[WorkspaceTickRecord]:
        if not session_id:
            return None
        row = self._j_fetchone(
            "SELECT * FROM workspace_ticks WHERE session_id = ?"
            " ORDER BY started_at DESC LIMIT 1",
            (session_id,),
        )
        return _row_to_tick(row) if row else None

    def try_begin_workspace_tick(self, tick: WorkspaceTickRecord) -> tuple[WorkspaceTickRecord, bool]:
        """Insert pending tick. Returns (record, created). On unique conflict, returns existing."""
        if not tick.id:
            tick.id = ids.new_id("wstk")
        if not tick.started_at:
            tick.started_at = now_iso()
        tick.status = tick.status or "running"
        try:
            self.insert_workspace_tick(tick)
            return tick, True
        except Exception as exc:
            if not is_unique_violation(exc):
                raise
            existing = None
            if tick.idempotency_key:
                existing = self.get_workspace_tick_by_idempotency_key(tick.idempotency_key)
            if existing is None and tick.session_id and tick.sequence is not None:
                existing = self.get_workspace_tick_by_session_sequence(
                    tick.session_id, tick.sequence,
                )
            if (
                existing is None
                and tick.session_id
                and tick.interpret
                and tick.input_mode == "delta"
            ):
                existing = self.get_workspace_tick_by_session_delta_hash(
                    tick.session_id, tick.content_hash,
                )
            if existing is None:
                raise
            return existing, False

    def insert_consolidation_run(self, run: ConsolidationRunRecord) -> str:
        if not run.id:
            run.id = ids.new_id("crun")
        if not run.started_at:
            run.started_at = now_iso()
        self._c_insert("consolidation_runs", run.to_row())
        return run.id

    def update_consolidation_run(self, run: ConsolidationRunRecord) -> None:
        self._c_update("consolidation_runs", run.id, run.to_row())

    def get_consolidation_run(self, run_id: str) -> Optional[ConsolidationRunRecord]:
        row = self._j_fetchone(
            "SELECT * FROM consolidation_runs WHERE id = ?", (run_id,),
        )
        return _row_to_run(row) if row else None

    def get_consolidation_run_for_window(
        self, *, kind: str, window_start: str, window_end: str, dry_run: bool = False,
    ) -> Optional[ConsolidationRunRecord]:
        row = self._j_fetchone(
            "SELECT * FROM consolidation_runs WHERE kind = ? AND window_start = ?"
            " AND window_end = ? AND dry_run = ?"
            " ORDER BY started_at DESC LIMIT 1",
            (kind, window_start, window_end, int(bool(dry_run))),
        )
        return _row_to_run(row) if row else None

    def try_begin_consolidation_run(
        self, run: ConsolidationRunRecord,
    ) -> tuple[ConsolidationRunRecord, bool]:
        """Insert apply-run for a window. Unique on (kind, window) when dry_run=0."""
        if not run.id:
            run.id = ids.new_id("crun")
        if not run.started_at:
            run.started_at = now_iso()
        run.status = run.status or "running"
        try:
            self.insert_consolidation_run(run)
            return run, True
        except Exception as exc:
            if not is_unique_violation(exc):
                raise
            if run.dry_run:
                raise
            existing = self.get_consolidation_run_for_window(
                kind=run.kind,
                window_start=run.window_start,
                window_end=run.window_end,
                dry_run=False,
            )
            if existing is None:
                raise
            return existing, False
