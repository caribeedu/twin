"""Judgment profile — principles, decision criteria and style that make
different LLMs act consistently. Stored as YAML the user edits directly;
exposed read-only through the API/MCP."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_profile(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def render_profile(profile: dict[str, Any]) -> str:
    """Compact plain-text rendering for inclusion in a context pack."""
    if not profile:
        return ""
    lines: list[str] = ["## Judgment profile"]

    def walk(node: Any, indent: int = 0) -> None:
        pad = "  " * indent
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, (dict, list)):
                    lines.append(f"{pad}{key}:")
                    walk(value, indent + 1)
                else:
                    lines.append(f"{pad}{key}: {value}")
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, (dict, list)):
                    walk(item, indent)
                else:
                    lines.append(f"{pad}- {item}")

    walk(profile)
    return "\n".join(lines)
