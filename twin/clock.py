"""Shared time helper (kept dependency-free; used by every layer)."""

from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
