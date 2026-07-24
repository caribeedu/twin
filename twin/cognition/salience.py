"""Salience, novelty and live contradiction cues.

Deterministic, cheap signals for the parallel workspace — not a second
quality analyzer.

Salience is an attention signal (confidence + finding pressure). Novelty is
separate and may boost ranking / inspection priority, but must not substitute
for retrieval relevance in recall gates.
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
        hay = f"{mem.title} {mem.summary}".lower()
        tokens = [t for t in q.replace(",", " ").split() if len(t) >= 4][:20]
        overlap = sum(1 for t in tokens if t in hay) if tokens else 0
        retrieval = float(getattr(mem, "retrieval_count", 0) or 0)
        nov = _clamp(
            0.55
            + 0.25 * (1.0 if overlap == 0 else 0.0)
            - min(0.35, retrieval / 40.0)
            + (0.15 if mid in conflict_touch else 0.0)
        )
        # Salience deliberately excludes novelty — relevance gate stays separate.
        sal = _clamp(
            0.55 * conf
            + (0.30 if mid in conflict_touch else 0.0)
            + min(0.15, float(getattr(mem, "quality_score", 0) or 0) / 2)
        )
        novelty[mid] = nov
        salience[mid] = sal
        if mid in conflict_touch:
            contradiction.append(mid)

    return SalienceScores(
        by_memory=salience, novelty=novelty, contradiction_ids=contradiction,
    )
