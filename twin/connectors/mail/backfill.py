"""Partitionable BackfillJob planning + claim helpers (v0.6 §34).

Historical backfill is separated from continuous sync. Partitions are
year-month windows so a large mailbox can pause/resume without redoing
completed months. Each partition runs on a namespaced stream
(``backfill:{job}:{partition}:{base}``) so continuous checkpoints never
regress.

Partition claims use CAS on ``BackfillJob.version`` plus a fencing
``claim_token`` so two workers cannot complete the same month.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

CLAIM_TTL_SECONDS = 600


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        if "T" in text:
            return datetime.fromisoformat(text).date()
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def plan_year_month_partitions(
    *,
    range_start: Optional[str],
    range_end: Optional[str] = None,
    max_partitions: int = 240,
) -> list[dict[str, Any]]:
    """Return year-month partitions covering ``[range_start, range_end]``."""
    start = _parse_date(range_start)
    end = _parse_date(range_end) or datetime.now(timezone.utc).date()
    if start is None:
        start = date(end.year - 10, end.month, 1)
    if start > end:
        return []

    partitions: list[dict[str, Any]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month) and len(partitions) < max_partitions:
        last_day = monthrange(y, m)[1]
        p_start = date(y, m, 1)
        p_end = date(y, m, last_day)
        if p_start < start:
            p_start = start
        if p_end > end:
            p_end = end
        key = f"{y:04d}-{m:02d}"
        partitions.append({
            "partition_key": key,
            "range_start": p_start.isoformat(),
            "range_end": p_end.isoformat() + "T23:59:59Z",
            "status": "planned",
            "continuation_pending": False,
            "claimed_by": None,
            "claim_token": None,
            "claim_expires_at": None,
        })
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return partitions


def _claim_expired(part: dict[str, Any], *, now: Optional[datetime] = None) -> bool:
    expires = part.get("claim_expires_at")
    if not expires:
        return True
    now = now or datetime.now(timezone.utc)
    try:
        exp = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
    except ValueError:
        return True
    return exp <= now


def next_runnable_partition(
    progress: dict[str, Any], *, now: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    """First partition that is free to run (or whose claim expired)."""
    for part in progress.get("partitions") or []:
        status = part.get("status")
        if status == "completed":
            continue
        if status in (None, "planned", "failed"):
            return part
        if status in ("running", "continuation_pending"):
            if part.get("continuation_pending") or _claim_expired(part, now=now):
                return part
            # live claim held by another worker
            continue
    return None


def has_live_partition_claim(
    progress: dict[str, Any], *, now: Optional[datetime] = None,
) -> bool:
    for part in progress.get("partitions") or []:
        if part.get("status") not in ("running", "continuation_pending"):
            continue
        if part.get("continuation_pending"):
            continue
        if not _claim_expired(part, now=now):
            return True
    return False


def mark_partition(progress: dict[str, Any], partition_key: str,
                   status: str, **extra: Any) -> dict[str, Any]:
    out = dict(progress or {})
    parts = []
    for part in out.get("partitions") or []:
        row = dict(part)
        if row.get("partition_key") == partition_key:
            row["status"] = status
            row.update(extra)
        parts.append(row)
    out["partitions"] = parts
    completed = sum(1 for p in parts if p.get("status") == "completed")
    out["completed_partitions"] = completed
    out["total_partitions"] = len(parts)
    return out


def apply_partition_claim(
    progress: dict[str, Any],
    partition_key: str,
    *,
    worker_id: str,
    claim_token: int,
    ttl_seconds: int = CLAIM_TTL_SECONDS,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    expires = (now + timedelta(seconds=ttl_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return mark_partition(
        progress, partition_key, "running",
        claimed_by=worker_id,
        claim_token=claim_token,
        claim_expires_at=expires,
        continuation_pending=False,
    )


def release_partition_claim(
    progress: dict[str, Any], partition_key: str, *,
    status: str, claim_token: int, **extra: Any,
) -> dict[str, Any]:
    """Complete/fail a partition only when the claim_token still matches."""
    out = dict(progress or {})
    parts = []
    for part in out.get("partitions") or []:
        row = dict(part)
        if row.get("partition_key") == partition_key:
            if row.get("claim_token") != claim_token:
                # stale worker — leave progress untouched
                parts.append(row)
                continue
            row["status"] = status
            if status == "completed":
                row["continuation_pending"] = False
                row["claimed_by"] = None
                row["claim_expires_at"] = None
            elif status in ("running", "continuation_pending"):
                row["continuation_pending"] = True
            row.update(extra)
        parts.append(row)
    out["partitions"] = parts
    completed = sum(1 for p in parts if p.get("status") == "completed")
    out["completed_partitions"] = completed
    out["total_partitions"] = len(parts)
    return out
