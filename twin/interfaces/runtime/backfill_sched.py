"""Enqueue BackfillJob partition work onto the cognitive runtime queue.

Historical backfill stays separate from continuous ``connector_reconcile``:
each runtime job advances exactly one partition claim via
``run_backfill_partition``. The scheduler re-enqueues while the job is
``planned`` / ``running`` and a partition is free to run.
"""

from __future__ import annotations

from typing import Any, Optional

from twin.interfaces.runtime.models import JobKind
from twin.interfaces.runtime.queue import RuntimeQueue


def enqueue_backfill_partition_jobs(
    queue: RuntimeQueue,
    store: Any,
    *,
    vault_id: str = "vault_general",
    backfill_job_id: Optional[str] = None,
) -> list[str]:
    """Enqueue at most one ``backfill_partition`` job per active BackfillJob.

    Idempotency keys include ``BackfillJob.version`` so a completed partition
    run (which CAS-bumps version) naturally unlocks the next enqueue, while a
    still-pending/running runtime job is reused.
    """
    if not hasattr(store, "list_active_backfill_jobs"):
        return []

    from twin.sense.connectors.mail.backfill import (
        has_live_partition_claim,
        next_runnable_partition,
    )
    from twin.sense.connectors.models import BackfillJobStatus

    if backfill_job_id:
        job = store.get_backfill_job(backfill_job_id)
        jobs = [job] if job is not None else []
    else:
        jobs = store.list_active_backfill_jobs()

    created: list[str] = []
    for job in jobs:
        if job is None:
            continue
        if job.status not in (
            BackfillJobStatus.planned,
            BackfillJobStatus.running,
            BackfillJobStatus.failed,
        ):
            continue
        progress = job.progress or {}
        if has_live_partition_claim(progress):
            continue
        part = next_runnable_partition(progress)
        if part is None:
            continue
        meta = job.metadata or {}
        job_vault = str(meta.get("vault_id") or vault_id or "vault_general")
        partition_key = str(part.get("partition_key") or "")
        enqueued = queue.enqueue(
            JobKind.backfill_partition,
            payload={
                "backfill_job_id": job.id,
                "connector_id": job.connector_id,
                "partition_key": partition_key,
                "emit_percepts": True,
            },
            idempotency_key=(
                f"sched:backfill_partition:{job.id}:v{job.version}"
            ),
            vault_id=job_vault,
            priority=70,
        )
        created.append(enqueued.id)
    return created
