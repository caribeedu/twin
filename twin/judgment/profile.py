"""Judgment profile — YAML bootstrap + promotion into proposals.

Durable judgment lives in the database (canonical). ``judgment.yaml`` remains
a human-readable bootstrap/export. Tools must not silently rewrite identity:
``promote_memory`` creates a *proposal*, never an active judgment item.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import yaml

from ..clock import now_iso

if TYPE_CHECKING:
    from ..memory.models import MemoryItem
    from ..memory.store.base import MemoryStore


def load_profile(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


# memory type → legacy YAML section (kept for export compatibility)
_PROMOTION_SECTIONS = {
    "preference": "promoted_preferences",
    "belief": "promoted_beliefs",
    "procedure": "promoted_procedures",
}


def promote_memory(path: Path | str, mem: "MemoryItem",
                   store: Optional["MemoryStore"] = None) -> str:
    """Promote a memory into judgment.

    When a store is provided (v0.4+), creates a pending JudgmentProposal and
    does **not** auto-activate judgment. Falls back to appending the legacy
    YAML section only when no store is available (tests / recovery).
    """
    section = _PROMOTION_SECTIONS.get(mem.type.value)
    if section is None:
        raise ValueError(
            f"memory type '{mem.type.value}' cannot be promoted to judgment "
            f"(only: {', '.join(_PROMOTION_SECTIONS)})"
        )

    if store is not None and hasattr(store, "insert_judgment_proposal"):
        from .proposals import propose_from_memory
        proposal = propose_from_memory(store, mem.id)
        return f"proposal:{proposal.id}"

    # Legacy YAML append (bootstrap / no DB)
    p = Path(path)
    profile = load_profile(p)
    entries: list[dict[str, Any]] = profile.setdefault(section, [])
    if any(isinstance(e, dict) and e.get("memory_id") == mem.id for e in entries):
        return section
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
    """Compact plain-text rendering for inclusion in a context pack (legacy YAML)."""
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
