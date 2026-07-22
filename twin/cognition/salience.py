"""Salience, novelty and live contradiction cues (v0.8).

Deterministic, cheap signals for the parallel workspace — not a second
quality analyzer. Contradiction cues reuse open review findings when present;
novelty is inverse retrieval familiarity; salience blends confidence, novelty
and finding pressure.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..memory.models import INACTIVE_STATUSES
from ..memory.store.base import MemoryStore


@dataclass
class SalienceScores:
    by_memory: dict[str, float]
    novelty: dict[str, float]
    contradiction_ids: list[str]


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def score_memories(
    store: MemoryStore,
    memory_ids: list[str],
    *,
    query_text: str = "",
) -> SalienceScores:
    """Compute per-memory salience/novelty and list contradiction-touched ids."""
    novelty: dict[str, float] = {}
    salience: dict[str, float] = {}
    contradiction: list[str] = []

    conflict_kinds = frozenset({
        "possible_conflict", "conflict", "contradiction",
        "cross_source_temporal_conflict",
    })
    conflict_touch: set[str] = set()
    q = (query_text or "").lower()
    for mid in memory_ids:
        mem = store.get_memory(mid)
        if mem is None:
            continue
        st = getattr(mem.status, "value", mem.status)
        if st in INACTIVE_STATUSES:
            continue
        if hasattr(store, "get_findings"):
            for f in store.get_findings(mid, unresolved_only=True):
                ftype = getattr(f.type, "value", f.type) if hasattr(f, "type") else ""
                if ftype in conflict_kinds:
                    conflict_touch.add(mid)
                    meta = getattr(f, "metadata", None) or {}
                    for key in ("neighbor_ids", "related_ids", "memory_ids"):
                        for other in meta.get(key) or []:
                            conflict_touch.add(str(other))
                    break
        if "possible_conflict" in (mem.quality_flags or []):
            conflict_touch.add(mid)
        conf = float(mem.confidence or 0.0)
        # Novelty: less overlap with query tokens → slightly higher novelty;
        # brand-new low-retrieval memories also score higher.
        hay = f"{mem.title} {mem.summary}".lower()
        tokens = [t for t in q.replace(",", " ").split() if len(t) >= 4][:20]
        overlap = sum(1 for t in tokens if t in hay) if tokens else 0
        retrieval = float(getattr(mem, "retrieval_count", 0) or 0)
        nov = _clamp(0.55 + 0.25 * (1.0 if overlap == 0 else 0.0)
                     - min(0.35, retrieval / 40.0)
                     + (0.15 if mid in conflict_touch else 0.0))
        sal = _clamp(
            0.45 * conf
            + 0.35 * nov
            + (0.25 if mid in conflict_touch else 0.0)
            + min(0.15, float(getattr(mem, "quality_score", 0) or 0) / 2)
        )
        novelty[mid] = nov
        salience[mid] = sal
        if mid in conflict_touch:
            contradiction.append(mid)

    return SalienceScores(
        by_memory=salience, novelty=novelty, contradiction_ids=contradiction,
    )
