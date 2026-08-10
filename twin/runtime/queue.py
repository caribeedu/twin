"""Enqueue / claim / complete surface over the runtime store."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from twin.clock import now_iso
from twin.sense.connectors.errors import sanitize_error
from twin.memory.store.host_binding_mixin import is_unique_violation
from twin.runtime.models import (
    ErrorClass,
    JobKind,
    JobStatus,
    MODEL_GATED_KINDS,
    RuntimeJob,
)


class RuntimeQueue:
    def __init__(self, store):
        self.store = store

    def enqueue(
        self,
        kind: JobKind | str,
        *,
        payload: Optional[dict[str, Any]] = None,
        idempotency_key: str = "",
        vault_id: str = "vault_general",
        priority: int = 100,
        causal_parent_id: str = "",
        max_attempts: int = 8,
        not_before: str = "",
    ) -> RuntimeJob:
        kind = JobKind(kind) if not isinstance(kind, JobKind) else kind
        if idempotency_key:
            existing = self.store.get_runtime_job_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing
        job = RuntimeJob(
            kind=kind,
            payload=payload or {},
            idempotency_key=idempotency_key or "",
            vault_id=vault_id,
            priority=priority,
            causal_parent_id=causal_parent_id or "",
            max_attempts=max_attempts,
            not_before=not_before or "",
        )
        try:
            self.store.insert_runtime_job(job)
        except Exception as exc:
            if idempotency_key and is_unique_violation(exc):
                existing = self.store.get_runtime_job_by_idempotency_key(idempotency_key)
                if existing is not None:
                    return existing
            raise
        return job

    def claim(
        self,
        worker_id: str,
        *,
        vault_id: Optional[str] = None,
        lease_seconds: int = 60,
    ) -> Optional[RuntimeJob]:
        return self.store.claim_runtime_job(
            worker_id=worker_id, vault_id=vault_id, lease_seconds=lease_seconds,
        )

    def heartbeat(
        self, job: RuntimeJob, *, lease_seconds: int = 60,
    ) -> bool:
        return self.store.heartbeat_runtime_job(
            job.id,
            worker_id=job.worker_id,
            lease_token=job.lease_token,
            lease_seconds=lease_seconds,
        )

    def complete(self, job: RuntimeJob, result: Optional[dict[str, Any]] = None) -> bool:
        return self.store.complete_runtime_job(
            job.id,
            worker_id=job.worker_id,
            lease_token=job.lease_token,
            result=result,
        )

    def fail(
        self,
        job: RuntimeJob,
        exc: BaseException | str,
        *,
        stage: str,
        error_class: ErrorClass | str = ErrorClass.transient,
    ) -> bool:
        ec = error_class.value if isinstance(error_class, ErrorClass) else str(error_class)
        err = sanitize_error(exc)

        # Model outages: backoff without burning the attempt budget forever.
        # We already incremented attempts on claim; for model_unavailable, refund
        # one attempt by clamping and still scheduling backoff.
        dead = False
        not_before = ""
        attempts = job.attempts
        if ec == ErrorClass.model_unavailable.value and job.kind in MODEL_GATED_KINDS:
            # Do not dead-letter solely on model outage — keep retrying with backoff.
            delay = min(3600, 30 * (2 ** max(0, attempts - 1)))
            not_before = (
                datetime.now(timezone.utc) + timedelta(seconds=delay)
            ).isoformat(timespec="seconds")
            # Soften attempt consumption: store max_attempts effectively infinite for this class
            # by never dead-lettering on model_unavailable.
            dead = False
        elif ec in (ErrorClass.permanent.value, ErrorClass.invariant.value):
            dead = True
        elif attempts >= job.max_attempts:
            dead = True
        else:
            delay = min(1800, 5 * (2 ** max(0, attempts - 1)))
            not_before = (
                datetime.now(timezone.utc) + timedelta(seconds=delay)
            ).isoformat(timespec="seconds")

        return self.store.fail_runtime_job(
            job.id,
            worker_id=job.worker_id,
            lease_token=job.lease_token,
            error=err,
            error_class=ec,
            stage=stage,
            not_before=not_before,
            dead_letter=dead,
        )

    def cancel(self, job_id: str) -> bool:
        return self.store.cancel_runtime_job(job_id)

    def retry(self, job_id: str) -> Optional[RuntimeJob]:
        """Re-queue a failed/dead-letter job as pending (explicit)."""
        job = self.store.get_runtime_job(job_id)
        if job is None:
            return None
        st = job.status.value if hasattr(job.status, "value") else str(job.status)
        if st not in (JobStatus.failed.value, JobStatus.dead_letter.value):
            return job
        job.status = JobStatus.pending
        job.not_before = ""
        job.error = ""
        job.error_class = ""
        job.stage = "requeued"
        job.completed_at = ""
        job.worker_id = ""
        job.lease_token = ""
        job.lease_expires_at = ""
        job.updated_at = now_iso()
        self.store.update_runtime_job(job)
        return job
