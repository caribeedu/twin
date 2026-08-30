"""Fireflies cursor helpers.

``creation_watermark`` tracks the latest *meeting creation* time safely
observed via ``transcripts(fromDate:…)``. It is NOT an update cursor —
incomplete / changing transcripts are tracked in ``pending_transcripts``
and re-fetched by ID.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from twin.clock import now_iso

TERMINAL_STATUSES = frozenset({"complete", "failed"})
INCOMPLETE_STATUSES = frozenset({"live", "processing", "partial"})

DEFAULT_RECONCILE_DAYS = 14
DEFAULT_PAGE_OVERLAP = 5
DEFAULT_MAX_KNOWN = 500


def creation_watermark(cursor: dict[str, Any]) -> Optional[str]:
    """Prefer explicit creation_watermark; fall back to legacy ``watermark``."""
    return cursor.get("creation_watermark") or cursor.get("watermark")


def bump_creation_seen(cursor: dict[str, Any], started_at: Optional[str]) -> None:
    if not started_at:
        return
    cur = cursor.get("window_max_seen") or creation_watermark(cursor)
    if not cur or str(started_at) > str(cur):
        cursor["window_max_seen"] = started_at


def promote_creation_watermark(cursor: dict[str, Any]) -> dict[str, Any]:
    """Promote window max into creation_watermark when a discover window ends."""
    out = dict(cursor)
    seen = out.pop("window_max_seen", None)
    if seen:
        prev = creation_watermark(out)
        if not prev or str(seen) > str(prev):
            out["creation_watermark"] = seen
    # Drop legacy key once migrated.
    out.pop("watermark", None)
    out.pop("_from_date", None)
    out["progress"] = {}
    return out


def pending_map(cursor: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = cursor.get("pending_transcripts") or {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}


def known_map(cursor: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = cursor.get("known_transcripts") or {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}


def note_transcript(
    pending: dict[str, dict[str, Any]],
    known: dict[str, dict[str, Any]],
    *,
    tid: str,
    status: str,
    started_at: Optional[str],
    max_known: int = DEFAULT_MAX_KNOWN,
) -> None:
    """Update pending/known after observing a transcript (pre-commit cursor)."""
    now = now_iso()
    status = (status or "unknown").lower()
    known[tid] = {
        "started_at": started_at,
        "last_status": status,
        "last_seen_at": now,
    }
    if status in TERMINAL_STATUSES:
        pending.pop(tid, None)
    else:
        # live / processing / partial / unknown — keep observing by ID
        prev = pending.get(tid) or {}
        pending[tid] = {
            "status": status,
            "last_checked_at": now,
            "generation": int(prev.get("generation") or 0) + 1,
            "started_at": started_at or prev.get("started_at"),
        }
    _cap_known(known, max_known)


def _cap_known(known: dict[str, dict[str, Any]], max_known: int) -> None:
    if len(known) <= max_known:
        return
    ordered = sorted(
        known.items(),
        key=lambda kv: str(kv[1].get("started_at") or kv[1].get("last_seen_at") or ""),
    )
    for key, _ in ordered[: max(0, len(known) - max_known)]:
        known.pop(key, None)


def reconcile_due(cursor: dict[str, Any], *, interval_seconds: int) -> bool:
    last = cursor.get("last_reconciliation_at")
    if not last:
        return True
    try:
        dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
    except ValueError:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt) >= timedelta(seconds=interval_seconds)


def reconcile_candidates(
    known: dict[str, dict[str, Any]],
    pending: dict[str, dict[str, Any]],
    *,
    reconcile_days: int,
    limit: int = 40,
) -> list[str]:
    """Complete transcripts from the recent window that are not already pending."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=reconcile_days)
    cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    out: list[str] = []
    for tid, meta in sorted(
        known.items(),
        key=lambda kv: str(kv[1].get("started_at") or ""),
        reverse=True,
    ):
        if tid in pending:
            continue
        started = str(meta.get("started_at") or "")
        if started and started < cutoff_iso:
            continue
        if str(meta.get("last_status") or "") in INCOMPLETE_STATUSES:
            continue
        out.append(tid)
        if len(out) >= limit:
            break
    return out


def next_skip_with_overlap(
    skip: int, page_len: int, *, overlap: int, limit: int,
) -> Optional[int]:
    """Advance skip with overlap so concurrent inserts are less likely to gap."""
    if page_len < limit:
        return None
    advance = max(1, page_len - max(0, overlap))
    return skip + advance
