"""Runtime job / lease / DLQ persistence (SQLite + Postgres)."""

from __future__ import annotations

import json
import secrets
from typing import Any, Optional

from twin.clock import now_iso
from twin.runtime.models import DeadLetterItem, JobStatus, RuntimeJob, WorkerLease


RUNTIME_SCHEMA = """
CREATE TABLE IF NOT EXISTS runtime_jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    priority INTEGER NOT NULL DEFAULT 100,
    vault_id TEXT NOT NULL DEFAULT 'vault_general',
    idempotency_key TEXT NOT NULL DEFAULT '',
    causal_parent_id TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',
    result TEXT NOT NULL DEFAULT '{}',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 8,
    stage TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    error_class TEXT NOT NULL DEFAULT '',
    worker_id TEXT NOT NULL DEFAULT '',
    lease_token TEXT NOT NULL DEFAULT '',
    lease_expires_at TEXT NOT NULL DEFAULT '',
    not_before TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT '',
    completed_at TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_runtime_job_idem
    ON runtime_jobs(idempotency_key)
    WHERE idempotency_key != '';
CREATE INDEX IF NOT EXISTS idx_runtime_jobs_claim
    ON runtime_jobs(status, not_before, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_runtime_jobs_vault
    ON runtime_jobs(vault_id, status);

CREATE TABLE IF NOT EXISTS runtime_worker_leases (
    id TEXT PRIMARY KEY,
    worker_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    lease_token TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL DEFAULT '',
    expires_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_runtime_lease_job
    ON runtime_worker_leases(job_id);
CREATE INDEX IF NOT EXISTS idx_runtime_lease_worker
    ON runtime_worker_leases(worker_id);

CREATE TABLE IF NOT EXISTS runtime_dead_letters (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT '',
    vault_id TEXT NOT NULL DEFAULT 'vault_general',
    attempts INTEGER NOT NULL DEFAULT 0,
    stage TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    error_class TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open'
);
CREATE INDEX IF NOT EXISTS idx_runtime_dlq_status
    ON runtime_dead_letters(status, created_at);
"""


def _dumps(obj: Any) -> str:
    return json.dumps(obj or {}, default=str)


def _loads(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    return json.loads(raw or "{}")


def job_to_row(job: RuntimeJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "kind": job.kind.value if hasattr(job.kind, "value") else str(job.kind),
        "status": job.status.value if hasattr(job.status, "value") else str(job.status),
        "priority": int(job.priority),
        "vault_id": job.vault_id or "vault_general",
        "idempotency_key": job.idempotency_key or "",
        "causal_parent_id": job.causal_parent_id or "",
        "payload": _dumps(job.payload),
        "result": _dumps(job.result),
        "attempts": int(job.attempts),
        "max_attempts": int(job.max_attempts),
        "stage": job.stage or "",
        "error": job.error or "",
        "error_class": job.error_class or "",
        "worker_id": job.worker_id or "",
        "lease_token": job.lease_token or "",
        "lease_expires_at": job.lease_expires_at or "",
        "not_before": job.not_before or "",
        "created_at": job.created_at or "",
        "updated_at": job.updated_at or "",
        "started_at": job.started_at or "",
        "completed_at": job.completed_at or "",
    }


def row_to_job(row: Any) -> RuntimeJob:
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    return RuntimeJob(
        id=row["id"],
        kind=row["kind"],
        status=row["status"],
        priority=int(row["priority"]),
        vault_id=row["vault_id"] or "vault_general",
        idempotency_key=row["idempotency_key"] or "",
        causal_parent_id=row["causal_parent_id"] or "",
        payload=_loads(row["payload"]),
        result=_loads(row["result"]),
        attempts=int(row["attempts"]),
        max_attempts=int(row["max_attempts"]),
        stage=row["stage"] or "",
        error=row["error"] or "",
        error_class=row["error_class"] or "",
        worker_id=row["worker_id"] or "",
        lease_token=row["lease_token"] or "",
        lease_expires_at=row["lease_expires_at"] or "",
        not_before=row["not_before"] or "",
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
        started_at=row["started_at"] or "",
        completed_at=row["completed_at"] or "",
    )


def lease_to_row(lease: WorkerLease) -> dict[str, Any]:
    return {
        "id": lease.id,
        "worker_id": lease.worker_id,
        "job_id": lease.job_id,
        "lease_token": lease.lease_token,
        "heartbeat_at": lease.heartbeat_at or "",
        "expires_at": lease.expires_at or "",
        "created_at": lease.created_at or "",
    }


def row_to_lease(row: Any) -> WorkerLease:
    return WorkerLease(
        id=row["id"],
        worker_id=row["worker_id"],
        job_id=row["job_id"],
        lease_token=row["lease_token"],
        heartbeat_at=row["heartbeat_at"] or "",
        expires_at=row["expires_at"] or "",
        created_at=row["created_at"] or "",
    )


def dlq_to_row(item: DeadLetterItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "job_id": item.job_id,
        "kind": item.kind,
        "vault_id": item.vault_id or "vault_general",
        "attempts": int(item.attempts),
        "stage": item.stage or "",
        "error": item.error or "",
        "error_class": item.error_class or "",
        "payload": _dumps(item.payload),
        "created_at": item.created_at or "",
        "status": item.status or "open",
    }


def row_to_dlq(row: Any) -> DeadLetterItem:
    return DeadLetterItem(
        id=row["id"],
        job_id=row["job_id"],
        kind=row["kind"] or "",
        vault_id=row["vault_id"] or "vault_general",
        attempts=int(row["attempts"]),
        stage=row["stage"] or "",
        error=row["error"] or "",
        error_class=row["error_class"] or "",
        payload=_loads(row["payload"]),
        created_at=row["created_at"] or "",
        status=row["status"] or "open",
    )


class RuntimeStoreMixin:
    """Duck-typed runtime persistence via connector SQL helpers."""

    def insert_runtime_job(self, job: RuntimeJob) -> str:
        if not job.created_at:
            job.created_at = now_iso()
        job.updated_at = now_iso()
        self._c_insert("runtime_jobs", job_to_row(job))
        return job.id

    def update_runtime_job(self, job: RuntimeJob) -> None:
        job.updated_at = now_iso()
        self._c_update("runtime_jobs", job.id, job_to_row(job))

    def get_runtime_job(self, job_id: str) -> Optional[RuntimeJob]:
        row = self._j_fetchone(
            "SELECT * FROM runtime_jobs WHERE id = ?", (job_id,),
        )
        return row_to_job(row) if row else None

    def get_runtime_job_by_idempotency_key(self, key: str) -> Optional[RuntimeJob]:
        if not key:
            return None
        row = self._j_fetchone(
            "SELECT * FROM runtime_jobs WHERE idempotency_key = ?", (key,),
        )
        return row_to_job(row) if row else None

    def list_runtime_jobs(
        self,
        *,
        status: Optional[str] = None,
        kind: Optional[str] = None,
        vault_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[RuntimeJob]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if vault_id:
            clauses.append("vault_id = ?")
            params.append(vault_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        rows = self._j_fetchall(
            f"SELECT * FROM runtime_jobs{where}"
            " ORDER BY priority ASC, created_at ASC LIMIT ?",
            tuple(params),
        )
        return [row_to_job(r) for r in rows]

    def claim_runtime_job(
        self,
        *,
        worker_id: str,
        vault_id: Optional[str] = None,
        lease_seconds: int = 60,
        now: Optional[str] = None,
    ) -> Optional[RuntimeJob]:
        """Atomically claim the next runnable job for ``worker_id``.

        Runnable = pending/failed with ``not_before <= now``, or running with
        an expired lease (dead-worker recovery).
        """
        from datetime import datetime, timedelta, timezone

        now = now or now_iso()
        token = secrets.token_hex(16)
        expires = (
            datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
        ).isoformat(timespec="seconds")

        # Prefer pending/failed; also reclaim expired running leases.
        candidates = self._j_fetchall(
            "SELECT id FROM runtime_jobs WHERE ("
            " (status IN ('pending', 'failed') AND (not_before = '' OR not_before <= ?))"
            " OR (status = 'running' AND lease_expires_at != '' AND lease_expires_at < ?)"
            ")"
            + (" AND vault_id = ?" if vault_id else "")
            + " ORDER BY priority ASC, created_at ASC LIMIT 20",
            (now, now, vault_id) if vault_id else (now, now),
        )
        for crow in candidates:
            job_id = crow["id"]
            cur = self._j_exec(
                "UPDATE runtime_jobs SET status = ?, worker_id = ?, lease_token = ?,"
                " lease_expires_at = ?, started_at = CASE WHEN started_at = '' THEN ? ELSE started_at END,"
                " attempts = attempts + 1, updated_at = ?, error = '', error_class = '', stage = 'claimed'"
                " WHERE id = ? AND ("
                "  (status IN ('pending', 'failed') AND (not_before = '' OR not_before <= ?))"
                "  OR (status = 'running' AND lease_expires_at != '' AND lease_expires_at < ?)"
                " )",
                (
                    JobStatus.running.value, worker_id, token, expires, now, now,
                    job_id, now, now,
                ),
            )
            self._j_commit()
            if getattr(cur, "rowcount", 0) != 1:
                continue
            job = self.get_runtime_job(job_id)
            if job is None:
                continue
            # Upsert lease row
            self._j_exec("DELETE FROM runtime_worker_leases WHERE job_id = ?", (job_id,))
            lease = WorkerLease(
                worker_id=worker_id,
                job_id=job_id,
                lease_token=token,
                heartbeat_at=now,
                expires_at=expires,
            )
            self._c_insert("runtime_worker_leases", lease_to_row(lease))
            return job
        return None

    def heartbeat_runtime_job(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        lease_seconds: int = 60,
    ) -> bool:
        from datetime import datetime, timedelta, timezone

        now = now_iso()
        expires = (
            datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
        ).isoformat(timespec="seconds")
        cur = self._j_exec(
            "UPDATE runtime_jobs SET lease_expires_at = ?, updated_at = ?"
            " WHERE id = ? AND worker_id = ? AND lease_token = ? AND status = ?",
            (expires, now, job_id, worker_id, lease_token, JobStatus.running.value),
        )
        self._j_commit()
        if getattr(cur, "rowcount", 0) != 1:
            return False
        self._j_exec(
            "UPDATE runtime_worker_leases SET heartbeat_at = ?, expires_at = ?"
            " WHERE job_id = ? AND worker_id = ? AND lease_token = ?",
            (now, expires, job_id, worker_id, lease_token),
        )
        self._j_commit()
        return True

    def complete_runtime_job(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        result: Optional[dict[str, Any]] = None,
        stage: str = "done",
    ) -> bool:
        now = now_iso()
        cur = self._j_exec(
            "UPDATE runtime_jobs SET status = ?, result = ?, stage = ?,"
            " completed_at = ?, updated_at = ?, lease_token = '', lease_expires_at = '',"
            " worker_id = '', error = '', error_class = ?"
            " WHERE id = ? AND worker_id = ? AND lease_token = ? AND status = ?",
            (
                JobStatus.completed.value, _dumps(result or {}), stage, now, now, "",
                job_id, worker_id, lease_token, JobStatus.running.value,
            ),
        )
        self._j_commit()
        if getattr(cur, "rowcount", 0) != 1:
            return False
        self._j_exec("DELETE FROM runtime_worker_leases WHERE job_id = ?", (job_id,))
        self._j_commit()
        return True

    def fail_runtime_job(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        error: str,
        error_class: str,
        stage: str,
        not_before: str = "",
        dead_letter: bool = False,
    ) -> bool:
        now = now_iso()
        status = JobStatus.dead_letter.value if dead_letter else JobStatus.failed.value
        cur = self._j_exec(
            "UPDATE runtime_jobs SET status = ?, error = ?, error_class = ?, stage = ?,"
            " not_before = ?, updated_at = ?, lease_token = '', lease_expires_at = '',"
            " worker_id = '', completed_at = CASE WHEN ? = 1 THEN ? ELSE completed_at END"
            " WHERE id = ? AND worker_id = ? AND lease_token = ? AND status = ?",
            (
                status, error, error_class, stage, not_before, now,
                1 if dead_letter else 0, now,
                job_id, worker_id, lease_token, JobStatus.running.value,
            ),
        )
        self._j_commit()
        if getattr(cur, "rowcount", 0) != 1:
            return False
        self._j_exec("DELETE FROM runtime_worker_leases WHERE job_id = ?", (job_id,))
        self._j_commit()
        if dead_letter:
            job = self.get_runtime_job(job_id)
            if job is not None:
                self.insert_runtime_dead_letter(DeadLetterItem(
                    job_id=job.id,
                    kind=job.kind.value if hasattr(job.kind, "value") else str(job.kind),
                    vault_id=job.vault_id,
                    attempts=job.attempts,
                    stage=stage,
                    error=error,
                    error_class=error_class,
                    payload=dict(job.payload or {}),
                ))
        return True

    def cancel_runtime_job(self, job_id: str) -> bool:
        now = now_iso()
        cur = self._j_exec(
            "UPDATE runtime_jobs SET status = ?, updated_at = ?, completed_at = ?,"
            " error_class = ?, stage = 'cancelled'"
            " WHERE id = ? AND status IN ('pending', 'failed')",
            (JobStatus.cancelled.value, now, now, "cancelled", job_id),
        )
        self._j_commit()
        return getattr(cur, "rowcount", 0) == 1

    def insert_runtime_dead_letter(self, item: DeadLetterItem) -> str:
        if not item.created_at:
            item.created_at = now_iso()
        self._c_insert("runtime_dead_letters", dlq_to_row(item))
        return item.id

    def list_runtime_dead_letters(
        self, *, status: str = "open", limit: int = 100,
    ) -> list[DeadLetterItem]:
        rows = self._j_fetchall(
            "SELECT * FROM runtime_dead_letters WHERE status = ?"
            " ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        )
        return [row_to_dlq(r) for r in rows]

    def runtime_queue_depth(self) -> dict[str, int]:
        out: dict[str, int] = {}
        rows = self._j_fetchall(
            "SELECT status, COUNT(*) AS n FROM runtime_jobs GROUP BY status",
            (),
        )
        for r in rows:
            out[str(r["status"])] = int(r["n"])
        return out
