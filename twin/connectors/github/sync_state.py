"""Incremental sync cursor helpers for the GitHub adapter.

Invariant: page budget exhausted ≠ stream fully consumed.

A durable batch may commit a *continuation* cursor (``substream`` +
``progress`` / ``next_url``) without promoting ``watermark``. The
watermark advances only after every substream finishes the lookback
window (``finalize_cursor``).
"""

from __future__ import annotations

from typing import Any, Optional

SUBSTREAMS: dict[str, tuple[str, ...]] = {
    "issues": ("issues", "issue_comments"),
    "pulls": ("pr_scan", "pr_enrich", "pull_comments"),
    "commits": ("commits_incremental", "commits_reconcile"),
    "releases": ("releases",),
}


def _max_ts(current: Optional[str], candidate: Optional[str]) -> Optional[str]:
    if not candidate:
        return current
    if not current or candidate > current:
        return candidate
    return current


def next_substream(family: str, current: str) -> Optional[str]:
    subs = SUBSTREAMS[family]
    try:
        idx = subs.index(current)
    except ValueError:
        return None
    if idx + 1 >= len(subs):
        return None
    return subs[idx + 1]


def init_cursor(
    family: str,
    *,
    watermark: Optional[str],
    window_since: Optional[str],
) -> dict[str, Any]:
    subs = SUBSTREAMS[family]
    return {
        "watermark": watermark,
        "window_since": window_since,
        "window_max_seen": watermark,
        "substream": subs[0],
        "progress": {name: {} for name in subs},
    }


def in_progress(cursor: Optional[dict[str, Any]]) -> bool:
    return bool(cursor and cursor.get("substream") and "progress" in cursor)


def normalize_cursor(
    cursor: Optional[dict[str, Any]],
    *,
    family: str,
    window_since: Optional[str],
) -> dict[str, Any]:
    cur = dict(cursor or {})
    if in_progress(cur):
        return cur
    return init_cursor(
        family,
        watermark=cur.get("watermark"),
        window_since=window_since,
    )


def bump_window_max(cursor: dict[str, Any], candidate: Optional[str]) -> None:
    cursor["window_max_seen"] = _max_ts(cursor.get("window_max_seen"), candidate)


def finalize_cursor(cursor: dict[str, Any]) -> dict[str, Any]:
    watermark = cursor.get("window_max_seen") or cursor.get("watermark")
    return {"watermark": watermark} if watermark else {}


def substream_state(cursor: dict[str, Any], name: str) -> dict[str, Any]:
    progress = cursor.setdefault("progress", {})
    return progress.setdefault(name, {})
