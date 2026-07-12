"""Judgment store mixin — shared CRUD for SQLite and Postgres backends.

Backends implement ``_j_exec``, ``_j_fetchone``, ``_j_fetchall``, ``_j_commit``.
SQL uses ``?`` placeholders; Postgres adapters rewrite to ``%s``.
"""

from __future__ import annotations

from typing import Any, Optional

from twin.judgment.models import (
    JudgmentConflict,
    JudgmentItem,
    JudgmentProposal,
    JudgmentSnapshot,
    JudgmentTrace,
    JudgmentVersion,
)
from twin.judgment.persistence import (
    conflict_to_row,
    item_to_row,
    proposal_to_row,
    row_to_conflict,
    row_to_item,
    row_to_proposal,
    row_to_snapshot,
    row_to_trace,
    row_to_version,
    snapshot_to_row,
    trace_to_row,
    version_to_row,
)


class JudgmentStoreMixin:
    """Duck-typed judgment persistence. Mix into SqliteStore / PostgresStore."""

    def insert_judgment_item(self, item: JudgmentItem) -> str:
        row = item_to_row(item)
        cols = list(row.keys())
        ph = ", ".join("?" for _ in cols)
        self._j_exec(
            f"INSERT INTO judgment_items ({', '.join(cols)}) VALUES ({ph})",
            tuple(row[c] for c in cols),
        )
        self._j_commit()
        return item.id

    def get_judgment_item(self, judgment_id: str) -> Optional[JudgmentItem]:
        row = self._j_fetchone("SELECT * FROM judgment_items WHERE id = ?", (judgment_id,))
        return row_to_item(row) if row else None

    def update_judgment_item(self, judgment_id: str, **fields: Any) -> None:
        if not fields:
            return
        current = self.get_judgment_item(judgment_id)
        if current is None:
            raise ValueError(f"judgment {judgment_id} not found")
        data = current.model_dump(mode="json")
        data.update(fields)
        updated = JudgmentItem(**data)
        row = item_to_row(updated)
        sets = ", ".join(f"{k} = ?" for k in row if k != "id")
        vals = [row[k] for k in row if k != "id"] + [judgment_id]
        self._j_exec(f"UPDATE judgment_items SET {sets} WHERE id = ?", tuple(vals))
        self._j_commit()

    def list_judgment_items(
        self,
        *,
        status: Optional[str] = None,
        kind: Optional[str] = None,
        domain: Optional[str] = None,
        limit: int = 500,
    ) -> list[JudgmentItem]:
        clauses = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if domain:
            clauses.append("domain = ?")
            params.append(domain)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        rows = self._j_fetchall(
            f"SELECT * FROM judgment_items{where} ORDER BY updated_at DESC LIMIT ?",
            tuple(params),
        )
        return [row_to_item(r) for r in rows]

    def insert_judgment_proposal(self, proposal: JudgmentProposal) -> str:
        row = proposal_to_row(proposal)
        cols = list(row.keys())
        ph = ", ".join("?" for _ in cols)
        self._j_exec(
            f"INSERT INTO judgment_proposals ({', '.join(cols)}) VALUES ({ph})",
            tuple(row[c] for c in cols),
        )
        self._j_commit()
        return proposal.id

    def get_judgment_proposal(self, proposal_id: str) -> Optional[JudgmentProposal]:
        row = self._j_fetchone(
            "SELECT * FROM judgment_proposals WHERE id = ?", (proposal_id,),
        )
        return row_to_proposal(row) if row else None

    def update_judgment_proposal(self, proposal_id: str, **fields: Any) -> None:
        current = self.get_judgment_proposal(proposal_id)
        if current is None:
            raise ValueError(f"proposal {proposal_id} not found")
        data = current.model_dump(mode="json")
        data.update(fields)
        updated = JudgmentProposal(**data)
        row = proposal_to_row(updated)
        sets = ", ".join(f"{k} = ?" for k in row if k != "id")
        vals = [row[k] for k in row if k != "id"] + [proposal_id]
        self._j_exec(
            f"UPDATE judgment_proposals SET {sets} WHERE id = ?",
            tuple(vals),
        )
        self._j_commit()

    def list_judgment_proposals(
        self, *, status: Optional[str] = None, limit: int = 200,
    ) -> list[JudgmentProposal]:
        if status:
            rows = self._j_fetchall(
                "SELECT * FROM judgment_proposals WHERE status = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            rows = self._j_fetchall(
                "SELECT * FROM judgment_proposals ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return [row_to_proposal(r) for r in rows]

    def insert_judgment_version(self, version: JudgmentVersion) -> str:
        row = version_to_row(version)
        cols = list(row.keys())
        ph = ", ".join("?" for _ in cols)
        self._j_exec(
            f"INSERT INTO judgment_versions ({', '.join(cols)}) VALUES ({ph})",
            tuple(row[c] for c in cols),
        )
        self._j_commit()
        return version.id

    def get_judgment_version(self, version_id: str) -> Optional[JudgmentVersion]:
        row = self._j_fetchone(
            "SELECT * FROM judgment_versions WHERE id = ?", (version_id,),
        )
        return row_to_version(row) if row else None

    def get_active_judgment_version(self) -> Optional[JudgmentVersion]:
        row = self._j_fetchone(
            "SELECT * FROM judgment_versions WHERE active != 0"
            " ORDER BY version DESC LIMIT 1",
            (),
        )
        return row_to_version(row) if row else None

    def deactivate_judgment_versions(self) -> None:
        self._j_exec("UPDATE judgment_versions SET active = 0", ())
        self._j_commit()

    def list_judgment_versions(self, limit: int = 50) -> list[JudgmentVersion]:
        rows = self._j_fetchall(
            "SELECT * FROM judgment_versions ORDER BY version DESC LIMIT ?",
            (limit,),
        )
        return [row_to_version(r) for r in rows]

    def insert_judgment_snapshot(self, snapshot: JudgmentSnapshot) -> str:
        row = snapshot_to_row(snapshot)
        cols = list(row.keys())
        ph = ", ".join("?" for _ in cols)
        self._j_exec(
            f"INSERT INTO judgment_snapshots ({', '.join(cols)}) VALUES ({ph})",
            tuple(row[c] for c in cols),
        )
        self._j_commit()
        return snapshot.id

    def get_judgment_snapshot(self, snapshot_id: str) -> Optional[JudgmentSnapshot]:
        row = self._j_fetchone(
            "SELECT * FROM judgment_snapshots WHERE id = ?", (snapshot_id,),
        )
        return row_to_snapshot(row) if row else None

    def insert_judgment_conflict(self, conflict: JudgmentConflict) -> str:
        row = conflict_to_row(conflict)
        cols = list(row.keys())
        ph = ", ".join("?" for _ in cols)
        self._j_exec(
            f"INSERT INTO judgment_conflicts ({', '.join(cols)}) VALUES ({ph})",
            tuple(row[c] for c in cols),
        )
        self._j_commit()
        return conflict.id

    def get_judgment_conflict(self, conflict_id: str) -> Optional[JudgmentConflict]:
        row = self._j_fetchone(
            "SELECT * FROM judgment_conflicts WHERE id = ?", (conflict_id,),
        )
        return row_to_conflict(row) if row else None

    def update_judgment_conflict(self, conflict_id: str, **fields: Any) -> None:
        current = self.get_judgment_conflict(conflict_id)
        if current is None:
            raise ValueError(f"conflict {conflict_id} not found")
        data = current.model_dump(mode="json")
        data.update(fields)
        updated = JudgmentConflict(**data)
        row = conflict_to_row(updated)
        sets = ", ".join(f"{k} = ?" for k in row if k != "id")
        vals = [row[k] for k in row if k != "id"] + [conflict_id]
        self._j_exec(
            f"UPDATE judgment_conflicts SET {sets} WHERE id = ?",
            tuple(vals),
        )
        self._j_commit()

    def list_judgment_conflicts(
        self, *, status: Optional[str] = None, limit: int = 200,
    ) -> list[JudgmentConflict]:
        if status:
            rows = self._j_fetchall(
                "SELECT * FROM judgment_conflicts WHERE status = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            rows = self._j_fetchall(
                "SELECT * FROM judgment_conflicts ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return [row_to_conflict(r) for r in rows]

    def insert_judgment_trace(self, trace: JudgmentTrace) -> str:
        row = trace_to_row(trace)
        cols = list(row.keys())
        ph = ", ".join("?" for _ in cols)
        self._j_exec(
            f"INSERT INTO judgment_traces ({', '.join(cols)}) VALUES ({ph})",
            tuple(row[c] for c in cols),
        )
        self._j_commit()
        return trace.id

    def get_judgment_trace(self, trace_id: str) -> Optional[JudgmentTrace]:
        row = self._j_fetchone(
            "SELECT * FROM judgment_traces WHERE id = ?", (trace_id,),
        )
        return row_to_trace(row) if row else None

    def _j_exec(self, sql: str, params: tuple) -> None:
        raise NotImplementedError

    def _j_fetchone(self, sql: str, params: tuple) -> Any:
        raise NotImplementedError

    def _j_fetchall(self, sql: str, params: tuple) -> list:
        raise NotImplementedError

    def _j_commit(self) -> None:
        raise NotImplementedError
