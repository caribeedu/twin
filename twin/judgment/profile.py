"""Judgment profile — principles, decision criteria and style that make
different LLMs act consistently. Stored as YAML the user edits directly;
exposed read-only through the API/MCP.

Memories can be *promoted* into the profile: a confirmed
preference/belief/procedure that proved stable graduates from "something
that happened" to "how the user thinks" and starts riding along in every
context pack.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from ..clock import now_iso

if TYPE_CHECKING:
    from ..memory.models import MemoryItem


def load_profile(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


# memory type → profile section a promoted memory lands in
_PROMOTION_SECTIONS = {
    "preference": "promoted_preferences",
    "belief": "promoted_beliefs",
    "procedure": "promoted_procedures",
}


def promote_memory(path: Path | str, mem: "MemoryItem") -> str:
    """Append a memory to the judgment profile.

    Returns the profile section it was added to. Idempotent per memory id.
    Raises ValueError for memory types that don't belong in judgment.
    """
    section = _PROMOTION_SECTIONS.get(mem.type.value)
    if section is None:
        raise ValueError(
            f"memory type '{mem.type.value}' cannot be promoted to judgment "
            f"(only: {', '.join(_PROMOTION_SECTIONS)})"
        )
    p = Path(path)
    profile = load_profile(p)
    entries: list[dict[str, Any]] = profile.setdefault(section, [])
    if any(isinstance(e, dict) and e.get("memory_id") == mem.id for e in entries):
        return section  # already promoted
    entries.append({
        "memory_id": mem.id,
        "text": mem.summary,
        "domain": mem.domain,
        "promoted_at": now_iso(),
    })
    p.write_text(yaml.safe_dump(profile, allow_unicode=True, sort_keys=False),
                 encoding="utf-8")
    return section


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
