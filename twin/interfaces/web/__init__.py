"""Static web UI for ``twin serve`` (purple + white exocortex design)."""

from __future__ import annotations

from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parent
STATIC_DIR = WEB_ROOT / "static"
INDEX_HTML = STATIC_DIR / "index.html"


def read_index() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")
