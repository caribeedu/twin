"""HostSessionBinding persistence (v0.6 Phase 8)."""

from __future__ import annotations

import json
from typing import Any, Optional

from twin.memory.models import HostSessionBinding

HOST_BINDING_SCHEMA = """
CREATE TABLE IF NOT EXISTS host_session_bindings (
    id TEXT PRIMARY KEY,
    host_type TEXT NOT NULL,
    external_session_id TEXT NOT NULL,
    cognitive_session_id TEXT NOT NULL,
    project_id TEXT NOT NULL DEFAULT '',
    principal_id TEXT NOT NULL DEFAULT '',
    connector_id TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT '',
    ended_at TEXT,
    payload TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_hsb_host_ext
    ON host_session_bindings(host_type, external_session_id);
CREATE INDEX IF NOT EXISTS idx_hsb_session
    ON host_session_bindings(cognitive_session_id);
"""


def _binding_to_row(b: HostSessionBinding) -> dict[str, Any]:
    return {
        "id": b.id,
        "host_type": b.host_type,
        "external_session_id": b.external_session_id,
        "cognitive_session_id": b.cognitive_session_id,
        "project_id": b.project_id or "",
        "principal_id": b.principal_id or "",
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
    return HostSessionBinding(
        id=row["id"],
        host_type=row["host_type"],
        external_session_id=row["external_session_id"],
        cognitive_session_id=row["cognitive_session_id"],
        project_id=row["project_id"] or None,
        principal_id=row["principal_id"] or None,
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

    def find_host_session_binding(
        self, *, host_type: str, external_session_id: str,
    ) -> Optional[HostSessionBinding]:
        row = self._j_fetchone(
            "SELECT * FROM host_session_bindings WHERE host_type = ? AND "
            "external_session_id = ?",
            (host_type, external_session_id),
        )
        return _row_to_binding(row) if row else None

    def find_host_session_binding_by_session(
        self, cognitive_session_id: str,
    ) -> Optional[HostSessionBinding]:
        row = self._j_fetchone(
            "SELECT * FROM host_session_bindings WHERE cognitive_session_id = ? "
            "ORDER BY started_at DESC LIMIT 1",
            (cognitive_session_id,),
        )
        return _row_to_binding(row) if row else None

    def list_host_session_bindings(
        self, *, host_type: Optional[str] = None, limit: int = 200,
    ) -> list[HostSessionBinding]:
        if host_type:
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
