"""Incremental sync cursor helpers for mail adapters.

Watermark is the maximum observed message timestamp (RFC3339 or epoch ms
string). Page-budget exhaustion produces a durable continuation cursor;
the watermark advances only when the window finishes.
"""

from __future__ import annotations

from typing import Any, Optional

SUBSTREAMS = ("messages",)


def next_substream(current: str) -> Optional[str]:
    try:
        idx = SUBSTREAMS.index(current)
    except ValueError:
        return None
    if idx + 1 >= len(SUBSTREAMS):
        return None
    return SUBSTREAMS[idx + 1]


def init_cursor(*, watermark: Optional[str],
                window_oldest: Optional[str]) -> dict[str, Any]:
    return {
        "watermark": watermark,
        "window_oldest": window_oldest,
        "window_max_seen": watermark,
        "substream": SUBSTREAMS[0],
        "progress": {name: {} for name in SUBSTREAMS},
    }


def in_progress(cursor: Optional[dict[str, Any]]) -> bool:
    return bool(cursor and cursor.get("substream") and "progress" in cursor)


def normalize_cursor(
    cursor: Optional[dict[str, Any]], *, window_oldest: Optional[str],
) -> dict[str, Any]:
    cur = dict(cursor or {})
    if in_progress(cur):
        return cur
    return init_cursor(watermark=cur.get("watermark"),
                       window_oldest=window_oldest)


def bump_window_max(cursor: dict[str, Any], candidate: Optional[str]) -> None:
    if not candidate:
        return
    current = cursor.get("window_max_seen")
    if not current or str(candidate) > str(current):
        cursor["window_max_seen"] = candidate


def finalize_cursor(cursor: dict[str, Any]) -> dict[str, Any]:
    watermark = cursor.get("window_max_seen") or cursor.get("watermark")
    return {"watermark": watermark} if watermark else {}


def substream_state(cursor: dict[str, Any], name: str) -> dict[str, Any]:
    progress = cursor.setdefault("progress", {})
    return progress.setdefault(name, {})
