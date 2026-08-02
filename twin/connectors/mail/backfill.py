"""Partitionable BackfillJob planning + claim helpers.

Historical backfill is separated from continuous sync. Partitions are
year-month windows so a large mailbox can pause/resume without redoing
completed months. Each partition runs on a namespaced stream
(``backfill:{job}:{partition}:{base}``) so continuous checkpoints never
regress.

Partition claims use CAS on ``BackfillJob.version`` plus a fencing
``claim_token`` so two workers cannot complete the same month.
"""

from __future__ import annotations

import os
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

CLAIM_TTL_SECONDS = 600

# A single stream (e.g. one inaccessible Slack channel) must never wedge the
# whole partition. After this many consecutive non-committing attempts a stream
# is marked ``failed_terminal`` so the partition can complete *degraded* instead
# of re-enqueuing forever. Override with ``TWIN_BACKFILL_MAX_STREAM_ATTEMPTS``.
_DEFAULT_MAX_STREAM_ATTEMPTS = 5


def max_stream_attempts() -> int:
    raw = os.environ.get("TWIN_BACKFILL_MAX_STREAM_ATTEMPTS")
    if raw:
        try:
            n = int(raw)
            if n >= 1:
                return n
        except ValueError:
            pass
    return _DEFAULT_MAX_STREAM_ATTEMPTS


# Statuses that mean "this base stream will not run again for this partition".
_RESOLVED_STREAM_STATUSES = ("completed", "failed_terminal")


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


def discover_earliest_month(
    exists_before,
    *,
    max_years_back: int = 40,
    today: Optional[date] = None,
) -> Optional[str]:
    """Binary-search the earliest month that holds content.

    ``exists_before(d: date) -> bool`` must answer "is there any content
    strictly before the first day of month ``d``?" and be monotonic (False for
    old cutoffs, True once the cutoff passes the oldest item). Returns the first
    day of the earliest content month as ``YYYY-MM-DD``, or None when there is
    no content (or it cannot be determined). Costs ~log2(max_years_back*12)
    probes — a cheap alternative to paginating a whole mailbox for providers
    (Gmail) that expose no ascending order or creation timestamp."""
    today = today or datetime.now(timezone.utc).date()

    def _idx(y: int, m: int) -> int:
        return y * 12 + (m - 1)

    def _month(i: int) -> date:
        return date(i // 12, i % 12 + 1, 1)

    hi = _idx(today.year, today.month) + 1  # exclusive: "before next month" = all
    if not exists_before(_month(hi)):
        return None  # no content at all
    lo = _idx(max(1970, today.year - max_years_back), today.month)
    if exists_before(_month(lo)):
        return _month(lo).isoformat()  # content older than the search floor
    # Invariant: exists_before(lo) False, exists_before(hi) True. Narrow to the
    # boundary; the oldest content lives in the month just below it.
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if exists_before(_month(mid)):
            hi = mid
        else:
            lo = mid
    return _month(lo).isoformat()


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


def renew_partition_claim(
    progress: dict[str, Any], partition_key: str, *,
    worker_id: str, claim_token: int,
    ttl_seconds: int = CLAIM_TTL_SECONDS,
    now: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    """Extend claim TTL when token+worker still match. None if fence lost."""
    now = now or datetime.now(timezone.utc)
    expires = (now + timedelta(seconds=ttl_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = dict(progress or {})
    parts = []
    found = False
    for part in out.get("partitions") or []:
        row = dict(part)
        if row.get("partition_key") == partition_key:
            if (row.get("claimed_by") != worker_id
                    or row.get("claim_token") != claim_token
                    or _claim_expired(row, now=now)):
                return None
            row["claim_expires_at"] = expires
            found = True
        parts.append(row)
    if not found:
        return None
    out["partitions"] = parts
    return out


def claim_is_held(
    progress: dict[str, Any], partition_key: str, *,
    worker_id: str, claim_token: int,
    now: Optional[datetime] = None,
) -> bool:
    for part in progress.get("partitions") or []:
        if part.get("partition_key") != partition_key:
            continue
        if part.get("claimed_by") != worker_id:
            return False
        if part.get("claim_token") != claim_token:
            return False
        if _claim_expired(part, now=now):
            return False
        return True
    return False


def incomplete_base_streams(
    part: dict[str, Any], base_streams: list[str],
) -> list[str]:
    """Base streams still worth running: not completed and not terminally failed.

    A ``failed_terminal`` stream is skipped so a single broken source (e.g. an
    inaccessible channel) never re-runs and never blocks partition completion.
    """
    done = (part.get("streams") or {})
    return [
        s for s in base_streams
        if done.get(s) not in _RESOLVED_STREAM_STATUSES
    ]


def base_stream_resolved(part: dict[str, Any], base: str) -> bool:
    """True when a base stream is completed or terminally failed."""
    return (part.get("streams") or {}).get(base) in _RESOLVED_STREAM_STATUSES


def record_stream_results(
    progress: dict[str, Any], partition_key: str,
    stream_results: list[tuple[str, bool, bool]],
    *, claim_token: int, max_attempts: Optional[int] = None,
) -> dict[str, Any]:
    """Update per-base-stream status from ``(base_stream, committed, done)``.

    Tracks consecutive non-committing attempts per base stream. Once a stream
    reaches ``max_attempts`` failures without progress it is marked
    ``failed_terminal`` (a resolved state) so the partition can finish degraded
    rather than looping forever. Any commit (even a mid-pagination one) resets
    that stream's failure counter, since it is still making progress.
    """
    cap = max_attempts if max_attempts is not None else max_stream_attempts()
    out = dict(progress or {})
    parts = []
    for part in out.get("partitions") or []:
        row = dict(part)
        if row.get("partition_key") == partition_key:
            if row.get("claim_token") != claim_token:
                parts.append(row)
                continue
            streams = dict(row.get("streams") or {})
            attempts = dict(row.get("stream_attempts") or {})
            for base, committed, done in stream_results:
                if committed and done:
                    streams[base] = "completed"
                    attempts.pop(base, None)
                elif committed and not done:
                    streams[base] = "continuation_pending"
                    attempts.pop(base, None)
                elif streams.get(base) == "completed":
                    # Already finished; a transient empty result never regresses.
                    continue
                else:
                    n = int(attempts.get(base, 0)) + 1
                    attempts[base] = n
                    streams[base] = (
                        "failed_terminal" if n >= cap else "failed"
                    )
            row["streams"] = streams
            row["stream_attempts"] = attempts
        parts.append(row)
    out["partitions"] = parts
    return out
