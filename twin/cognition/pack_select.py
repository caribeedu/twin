"""Selection helpers for mature context packs."""

from __future__ import annotations

from typing import Any, Optional

from twin.memory.search import SearchHit
from twin.privacy.quarantine import detect_injection


def cognitive_label(mem) -> str:
    """Classify pack entry: fact | hypothesis | decision | proposal | …"""
    payload = mem.payload or {}
    act = (payload.get("cognitive_act") or "").lower()
    if act in ("proposal", "question", "hypothesis", "opinion"):
        return act
    if payload.get("rejected_alternative"):
        return "rejected_alternative"
    type_s = mem.type.value if hasattr(mem.type, "value") else str(mem.type)
    if type_s == "decision":
        return "decision"
    if type_s == "belief":
        return "hypothesis" if mem.confidence < 0.7 else "belief"
    if type_s == "task":
        return "open_task"
    if type_s == "procedure":
        return "procedure"
    if type_s == "constraint":
        return "constraint"
    return type_s or "fact"


def screen_injection(hits: list[SearchHit]) -> tuple[list[SearchHit], list[dict[str, Any]]]:
    """Drop memories whose stored text looks like prompt injection."""
    kept: list[SearchHit] = []
    blocked: list[dict[str, Any]] = []
    for hit in hits:
        text = f"{hit.memory.title}\n{hit.memory.summary}"
        patterns = detect_injection(text)
        if patterns:
            blocked.append({
                "memory_id": hit.memory.id,
                "reason": f"prompt_injection:{','.join(patterns[:3])}",
                "rule": "pack_injection_screen",
            })
            continue
        kept.append(hit)
    return kept, blocked


def dedupe_and_diversify(
    hits: list[SearchHit],
    *,
    max_per_type: int = 12,
    near_title_prefix: int = 48,
) -> tuple[list[SearchHit], dict[str, int]]:
    """Prefer higher score; drop near-duplicate titles; soft-cap per memory type.

    Soft caps stay high enough that section budget redistribution can still
    fill ``Additional context``; they mainly stop one type from flooding the
    candidate pool before packing.
    """
    dropped = {"duplicate_title": 0, "type_cap": 0}
    seen_titles: set[str] = set()
    type_counts: dict[str, int] = {}
    out: list[SearchHit] = []
    for hit in sorted(hits, key=lambda h: h.score, reverse=True):
        title_key = (hit.memory.title or "").strip().lower()[:near_title_prefix]
        if title_key and title_key in seen_titles:
            dropped["duplicate_title"] += 1
            continue
        type_s = hit.memory.type.value if hasattr(hit.memory.type, "value") else str(hit.memory.type)
        if type_counts.get(type_s, 0) >= max_per_type:
            dropped["type_cap"] += 1
            continue
        if title_key:
            seen_titles.add(title_key)
        type_counts[type_s] = type_counts.get(type_s, 0) + 1
        out.append(hit)
    return out, dropped


def prefer_current(hits: list[SearchHit]) -> list[SearchHit]:
    """Stable sort: higher score, then more recent updated/created."""
    def key(h: SearchHit):
        mem = h.memory
        stamp = mem.updated_at or mem.created_at or ""
        return (h.score, stamp)

    return sorted(hits, key=key, reverse=True)


def build_provenance_summary(
    store, hits: list[SearchHit], *, limit: int = 20,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for hit in hits[:limit]:
        ev_n = len(store.get_evidence(hit.memory.id)) if hasattr(store, "get_evidence") else 0
        out.append({
            "memory_id": hit.memory.id,
            "title": hit.memory.title,
            "label": cognitive_label(hit.memory),
            "evidence_n": ev_n,
            "inspect_path": f"/api/memory/{hit.memory.id}/explain",
            "confidence": hit.memory.confidence,
        })
    return out


def project_goals(store, project_id: Optional[str]) -> list[str]:
    if not project_id or not hasattr(store, "get_project"):
        return []
    project = store.get_project(project_id)
    if project is None:
        return []
    return list(getattr(project, "goals", None) or [])
