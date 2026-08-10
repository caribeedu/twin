"""YAML ↔ judgment store import/export with explicit classification preview."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

from .. import ids
from ..clock import now_iso
from twin.store.store.base import MemoryStore
from .models import (
    JudgmentItem,
    JudgmentKind,
    JudgmentProvenance,
    JudgmentScope,
    JudgmentStability,
    JudgmentStatus,
)
from .profile import load_profile
from .revisions import commit_new_item
from .versions import create_version


# Heuristic YAML section → kind suggestions (never auto-committed).
_SECTION_KIND = {
    "principles": JudgmentKind.principle,
    "technical_preferences": JudgmentKind.preference,
    "decision_criteria": JudgmentKind.heuristic,
    "promoted_preferences": JudgmentKind.preference,
    "promoted_beliefs": JudgmentKind.belief,
    "promoted_procedures": JudgmentKind.heuristic,
}


def classify_yaml_entry(section: str, text: str) -> dict[str, Any]:
    """Suggest kind/stability/strength for a free-text YAML entry."""
    kind = _SECTION_KIND.get(section, JudgmentKind.preference)
    lower = text.lower()
    stability = JudgmentStability.evolving
    strength = 0.55
    if section == "principles":
        stability = JudgmentStability.stable
        strength = 0.85
        if any(k in lower for k in ("não misturar", "not mix", "nunca", "never", "must not")):
            kind = JudgmentKind.constraint
            stability = JudgmentStability.constitutional
            strength = 1.0
        elif any(k in lower for k in ("privacidade", "privacy", "export")):
            stability = JudgmentStability.constitutional
            strength = 0.95
    elif section == "decision_criteria":
        kind = JudgmentKind.heuristic
        strength = 0.7
    elif section == "technical_preferences":
        if any(k in lower for k in ("evitar", "avoid", "não", "never")):
            kind = JudgmentKind.heuristic
            strength = 0.65
    domain = "technical"
    if section == "communication_style" or "comunica" in lower or "resposta" in lower:
        domain = "assistant_preferences"
        kind = JudgmentKind.preference
    return {
        "kind": kind.value,
        "stability": stability.value,
        "strength": strength,
        "confidence": 0.8 if section.startswith("promoted_") else 0.9,
        "domain": domain,
        "statement": text if isinstance(text, str) else str(text),
        "source_section": section,
    }


def preview_yaml_import(path: Path | str) -> list[dict[str, Any]]:
    """Classify every YAML entry into candidate JudgmentItems — no writes."""
    profile = load_profile(path)
    candidates: list[dict[str, Any]] = []
    for section, value in profile.items():
        if section == "communication_style" and isinstance(value, dict):
            for key, val in value.items():
                text = f"{key}: {val}"
                c = classify_yaml_entry(section, text)
                c["id"] = ids.judgment_id()
                candidates.append(c)
            continue
        if not isinstance(value, list):
            continue
        for entry in value:
            if isinstance(entry, dict):
                text = entry.get("text") or entry.get("statement") or str(entry)
                mem_id = entry.get("memory_id")
            else:
                text = str(entry)
                mem_id = None
            c = classify_yaml_entry(section, text)
            c["id"] = ids.judgment_id()
            if mem_id:
                c["memory_ids"] = [mem_id]
                c["source"] = "promoted_memory"
            else:
                c["source"] = "yaml_import"
            candidates.append(c)
    return candidates


def apply_yaml_import(
    store: MemoryStore,
    path: Path | str,
    *,
    classifications: Optional[list[dict[str, Any]]] = None,
    actor: str = "user",
    activate: bool = True,
) -> dict[str, Any]:
    """Commit a previously previewed classification set as judgment version 1+."""
    preview = classifications or preview_yaml_import(path)
    now = now_iso()
    created: list[str] = []
    revision_ids: list[str] = []
    for raw in preview:
        kind = JudgmentKind(raw["kind"])
        item = JudgmentItem(
            id=raw.get("id") or ids.judgment_id(),
            kind=kind,
            statement=raw["statement"],
            description=raw.get("description", ""),
            domain=raw.get("domain", "technical"),
            strength=float(raw.get("strength", 0.5)),
            confidence=float(raw.get("confidence", 0.8)),
            stability=JudgmentStability(raw.get("stability", "evolving")),
            status=JudgmentStatus.active if activate else JudgmentStatus.candidate,
            created_at=now,
            updated_at=now,
            approved_at=now if activate else None,
            approved_by=actor if activate else None,
            scope=JudgmentScope(domains=[raw.get("domain", "technical")]),
            provenance=JudgmentProvenance(
                memory_ids=list(raw.get("memory_ids") or []),
                source=raw.get("source", "yaml_import"),
            ),
            metadata={"yaml_section": raw.get("source_section")},
        )
        item, rev = commit_new_item(store, item, actor=actor, reason="yaml_import")
        created.append(item.id)
        revision_ids.append(rev.id)
    version = create_version(
        store,
        reason=f"import from {Path(path).name}",
        revision_ids=revision_ids,
        item_ids=created,
        actor=actor,
    )
    return {
        "created": created,
        "revision_ids": revision_ids,
        "version_id": version.id,
        "version": version.version,
        "count": len(created),
    }


def export_judgment_yaml(store: MemoryStore) -> str:
    """Human-readable projection of active judgment items."""
    items = store.list_judgment_items(status=JudgmentStatus.active.value)
    out: dict[str, Any] = {
        "principles": [],
        "technical_preferences": [],
        "decision_criteria": [],
        "constraints": [],
        "heuristics": [],
        "beliefs": [],
        "values": [],
        "preferences": [],
    }
    for item in items:
        entry = {
            "id": item.id,
            "statement": item.statement,
            "strength": item.strength,
            "confidence": item.confidence,
            "stability": item.stability.value,
            "domain": item.domain,
        }
        if item.kind == JudgmentKind.principle:
            out["principles"].append(entry)
        elif item.kind == JudgmentKind.constraint:
            out["constraints"].append(entry)
        elif item.kind == JudgmentKind.heuristic:
            out["heuristics"].append(entry)
            out["decision_criteria"].append(entry)
        elif item.kind == JudgmentKind.belief:
            out["beliefs"].append(entry)
        elif item.kind == JudgmentKind.value:
            out["values"].append(entry)
        elif item.kind == JudgmentKind.preference:
            out["preferences"].append(entry)
            if item.domain == "technical":
                out["technical_preferences"].append(entry)
    return yaml.safe_dump(out, allow_unicode=True, sort_keys=False)
