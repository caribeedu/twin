"""Partitionable BackfillJob planning for mail (v0.6 §34).

Historical backfill is separated from continuous sync. Partitions are
year-month windows so a large mailbox can pause/resume without redoing
completed months. The cognitive ingest path remains ``run_sync`` — a
partition simply supplies ``backfill_since`` / ``backfill_until`` bounds
for one stream sync window.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timezone
from typing import Any, Optional


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
    """Return year-month partitions covering ``[range_start, range_end]``.

    ``range_start=None`` means "unknown earliest" — caller must supply a
    concrete floor (preview can estimate; jobs require a bound).
    """
    start = _parse_date(range_start)
    end = _parse_date(range_end) or datetime.now(timezone.utc).date()
    if start is None:
        # Conservative floor when the provider does not advertise history
        # depth — ten years back, matching typical professional mailboxes.
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
        })
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return partitions


def next_runnable_partition(progress: dict[str, Any]) -> Optional[dict[str, Any]]:
    """First non-completed partition from a job's progress document."""
    for part in progress.get("partitions") or []:
        if part.get("status") in (None, "planned", "running", "failed"):
            return part
    return None


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
