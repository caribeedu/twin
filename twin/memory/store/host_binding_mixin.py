"""HostSessionBinding + observed-event idempotency (v0.6 Phase 8)."""

from __future__ import annotations

import json
from typing import Any, Optional

from twin import ids
from twin.memory.models import HostSessionBinding


def is_unique_violation(exc: BaseException) -> bool:
    """True only for UNIQUE / PRIMARY KEY conflicts — never generic IntegrityError.

    SQLite ``IntegrityError`` also covers NOT NULL / FOREIGN KEY / CHECK; those
    must surface as real errors, not silent ``duplicated=True``.
    """
    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    while stack:
        cur = stack.pop()
        if cur is None or id(cur) in seen:
            continue
        seen.add(id(cur))

        sqlstate = (
            getattr(cur, "sqlstate", None)
            or getattr(cur, "pgcode", None)
        )
        if sqlstate is None:
            diag = getattr(cur, "diag", None)
            sqlstate = getattr(diag, "sqlstate", None) if diag is not None else None
        if sqlstate == "23505":
            return True

        name = type(cur).__name__.lower()
        if "uniqueviolation" in name:
            return True

        sqlite_name = getattr(cur, "sqlite_errorname", None)
        if sqlite_name in {
            "SQLITE_CONSTRAINT_UNIQUE",
            "SQLITE_CONSTRAINT_PRIMARYKEY",
        }:
            return True

        # Older SQLite / wrapped drivers — message only, never bare IntegrityError.
        message = str(cur).lower()
        if (
            "unique constraint failed" in message
            or "duplicate key value violates unique constraint" in message
            or "is not unique" in message
        ):
            # Exclude other constraint phrases that can contain "unique" loosely.
            if "not null" in message or "foreign key" in message or "check constraint" in message:
                pass
            else:
                return True

        for linked in (cur.__cause__, cur.__context__):
            if isinstance(linked, BaseException):
                stack.append(linked)
    return False


HOST_BINDING_SCHEMA = """
DROP INDEX IF EXISTS uq_hsb_host_ext;
CREATE TABLE IF NOT EXISTS host_session_bindings (
    id TEXT PRIMARY KEY,
    host_type TEXT NOT NULL,
    external_session_id TEXT NOT NULL,
    occurrence INTEGER NOT NULL DEFAULT 1,
    cognitive_session_id TEXT NOT NULL,
    project_id TEXT NOT NULL DEFAULT '',
    principal_id TEXT NOT NULL DEFAULT '',
    vault_id TEXT NOT NULL DEFAULT '',
    domain TEXT NOT NULL DEFAULT '',
    persona TEXT NOT NULL DEFAULT 'individual',
    purpose TEXT NOT NULL DEFAULT 'task_execution',
    audience TEXT NOT NULL DEFAULT 'self',
    task_profile TEXT NOT NULL DEFAULT '',
    connector_id TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT '',
    ended_at TEXT,
    payload TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_hsb_host_ext_occ
    ON host_session_bindings(host_type, external_session_id, occurrence);
CREATE INDEX IF NOT EXISTS idx_hsb_session
    ON host_session_bindings(cognitive_session_id);
CREATE INDEX IF NOT EXISTS idx_hsb_active
    ON host_session_bindings(host_type, external_session_id, ended_at);

CREATE TABLE IF NOT EXISTS host_observed_events (
    id TEXT PRIMARY KEY,
    host_type TEXT NOT NULL,
    external_session_id TEXT NOT NULL,
    occurrence INTEGER NOT NULL DEFAULT 1,
    event_id TEXT NOT NULL,
    binding_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_host_event
    ON host_observed_events(host_type, external_session_id, occurrence, event_id);
CREATE INDEX IF NOT EXISTS idx_host_event_binding
    ON host_observed_events(binding_id);
"""


def _binding_to_row(b: HostSessionBinding) -> dict[str, Any]:
    return {
        "id": b.id,
        "host_type": b.host_type,
        "external_session_id": b.external_session_id,
        "occurrence": int(b.occurrence or 1),
        "cognitive_session_id": b.cognitive_session_id,
        "project_id": b.project_id or "",
        "principal_id": b.principal_id or "",
        "vault_id": b.vault_id or "",
        "domain": b.domain or "",
        "persona": b.persona or "individual",
        "purpose": b.purpose or "task_execution",
        "audience": b.audience or "self",
        "task_profile": b.task_profile or "",
        "connector_id": b.connector_id or "",
        "started_at": b.started_at or "",
        "ended_at": b.ended_at,
        "payload": json.dumps(b.metadata or {}),
    }


def _row_to_binding(row: Any) -> HostSessionBinding:
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    payload = row["payload"] if "payload" in keys else "{}"
    if isinstance(payload, dict):
        meta = payload
    else:
        meta = json.loads(payload or "{}")
    occ = row["occurrence"] if "occurrence" in keys else 1
    return HostSessionBinding(
        id=row["id"],
        host_type=row["host_type"],
        external_session_id=row["external_session_id"],
        occurrence=int(occ or 1),
        cognitive_session_id=row["cognitive_session_id"],
        project_id=row["project_id"] or None,
        principal_id=row["principal_id"] or None,
        vault_id=(row["vault_id"] if "vault_id" in keys else "") or None,
        domain=(row["domain"] if "domain" in keys else "") or None,
        persona=(row["persona"] if "persona" in keys else None) or "individual",
        purpose=(row["purpose"] if "purpose" in keys else None) or "task_execution",
        audience=(row["audience"] if "audience" in keys else None) or "self",
        task_profile=(row["task_profile"] if "task_profile" in keys else "") or None,
        connector_id=row["connector_id"] or None,
        started_at=row["started_at"] or "",
        ended_at=row["ended_at"],
        metadata=meta or {},
    )


class HostBindingStoreMixin:
    """Duck-typed HostSessionBinding store (uses connector SQL helpers)."""

    def insert_host_session_binding(self, binding: HostSessionBinding) -> str:
        self._c_insert("host_session_bindings", _binding_to_row(binding))
        return binding.id

    def update_host_session_binding(self, binding: HostSessionBinding) -> None:
        self._c_update(
            "host_session_bindings", binding.id, _binding_to_row(binding),
        )

    def get_host_session_binding(self, binding_id: str) -> Optional[HostSessionBinding]:
        row = self._j_fetchone(
            "SELECT * FROM host_session_bindings WHERE id = ?", (binding_id,),
        )
        return _row_to_binding(row) if row else None

    def find_active_host_session_binding(
        self, *, host_type: str, external_session_id: str,
    ) -> Optional[HostSessionBinding]:
        row = self._j_fetchone(
            "SELECT * FROM host_session_bindings WHERE host_type = ? AND "
            "external_session_id = ? AND (ended_at IS NULL OR ended_at = '') "
            "ORDER BY occurrence DESC LIMIT 1",
            (host_type, external_session_id),
        )
        return _row_to_binding(row) if row else None

    def find_host_session_binding(
        self, *, host_type: str, external_session_id: str,
    ) -> Optional[HostSessionBinding]:
        """Latest binding for the external id (active preferred, else newest)."""
        active = self.find_active_host_session_binding(
            host_type=host_type, external_session_id=external_session_id,
        )
        if active is not None:
            return active
        row = self._j_fetchone(
            "SELECT * FROM host_session_bindings WHERE host_type = ? AND "
            "external_session_id = ? ORDER BY occurrence DESC LIMIT 1",
            (host_type, external_session_id),
        )
        return _row_to_binding(row) if row else None

    def next_host_binding_occurrence(
        self, *, host_type: str, external_session_id: str,
    ) -> int:
        row = self._j_fetchone(
            "SELECT MAX(occurrence) AS m FROM host_session_bindings "
            "WHERE host_type = ? AND external_session_id = ?",
            (host_type, external_session_id),
        )
        if not row:
            return 1
        m = row["m"] if "m" in set(row.keys()) else None
        return int(m or 0) + 1

    def find_host_session_binding_by_session(
        self, cognitive_session_id: str,
    ) -> Optional[HostSessionBinding]:
        row = self._j_fetchone(
            "SELECT * FROM host_session_bindings WHERE cognitive_session_id = ? "
            "ORDER BY occurrence DESC LIMIT 1",
            (cognitive_session_id,),
        )
        return _row_to_binding(row) if row else None

    def list_host_session_bindings(
        self,
        *,
        host_type: Optional[str] = None,
        external_session_id: Optional[str] = None,
        limit: int = 200,
    ) -> list[HostSessionBinding]:
        if host_type and external_session_id:
            rows = self._j_fetchall(
                "SELECT * FROM host_session_bindings WHERE host_type = ? AND "
                "external_session_id = ? ORDER BY occurrence DESC LIMIT ?",
                (host_type, external_session_id, limit),
            )
        elif host_type:
            rows = self._j_fetchall(
                "SELECT * FROM host_session_bindings WHERE host_type = ? "
                "ORDER BY started_at DESC LIMIT ?",
                (host_type, limit),
            )
        else:
            rows = self._j_fetchall(
                "SELECT * FROM host_session_bindings ORDER BY started_at DESC "
                "LIMIT ?",
                (limit,),
            )
        return [_row_to_binding(r) for r in rows]

    def has_host_observed_event(
        self,
        *,
        host_type: str,
        external_session_id: str,
        occurrence: int,
        event_id: str,
    ) -> bool:
        row = self._j_fetchone(
            "SELECT id FROM host_observed_events WHERE host_type = ? AND "
            "external_session_id = ? AND occurrence = ? AND event_id = ?",
            (host_type, external_session_id, occurrence, event_id),
        )
        return row is not None

    def insert_host_observed_event(
        self,
        *,
        host_type: str,
        external_session_id: str,
        occurrence: int,
        event_id: str,
        binding_id: str,
        kind: str,
        created_at: str,
    ) -> bool:
        """Insert idempotency row. Returns False if already present (incl. races)."""
        try:
            self._c_insert("host_observed_events", {
                "id": ids.new_id("hevt"),
                "host_type": host_type,
                "external_session_id": external_session_id,
                "occurrence": occurrence,
                "event_id": event_id,
                "binding_id": binding_id,
                "kind": kind,
                "created_at": created_at,
            })
            return True
        except Exception as exc:
            if is_unique_violation(exc):
                return False
            raise
