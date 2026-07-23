"""Local scheduler — enqueue temporal/event cognitive jobs without autonomy."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from twin.clock import now_iso
from twin.runtime.models import JobKind
from twin.runtime.queue import RuntimeQueue

log = logging.getLogger("twin.runtime.scheduler")


def _day_key(now: Optional[datetime] = None) -> str:
    dt = now or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%d")


def _week_key(now: Optional[datetime] = None) -> str:
    dt = now or datetime.now(timezone.utc)
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


class RuntimeScheduler:
    """Enqueue due temporal jobs. Idempotency keys prevent duplicates."""

    def __init__(self, queue: RuntimeQueue, *, vault_id: str = "vault_general"):
        self.queue = queue
        self.vault_id = vault_id

    def tick(self, *, now: Optional[datetime] = None) -> list[str]:
        """Enqueue any due scheduled work. Returns job ids created or reused."""
        created: list[str] = []
        day = _day_key(now)
        week = _week_key(now)

        daily = self.queue.enqueue(
            JobKind.consolidate_daily,
            payload={"dry_run": False, "window": day},
            idempotency_key=f"sched:consolidate_daily:{day}:{self.vault_id}",
            vault_id=self.vault_id,
            priority=50,
        )
        created.append(daily.id)

        weekly = self.queue.enqueue(
            JobKind.consolidate_weekly,
            payload={"dry_run": False, "window": week},
            idempotency_key=f"sched:consolidate_weekly:{week}:{self.vault_id}",
            vault_id=self.vault_id,
            priority=60,
        )
        created.append(weekly.id)

        integrity = self.queue.enqueue(
            JobKind.integrity_check,
            payload={"scheduled_at": now_iso()},
            idempotency_key=f"sched:integrity:{day}:{self.vault_id}",
            vault_id=self.vault_id,
            priority=200,
        )
        created.append(integrity.id)
        return created
