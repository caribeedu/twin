"""Memory quality metrics.

Answers "is the memory layer actually good?" with numbers the README's
success-metrics section asks for: extraction precision proxy, duplicate
rate, review load, confidence distribution and firewall activity.
"""

from __future__ import annotations

from typing import Any

from .store.base import MemoryStore


def compute_metrics(store: MemoryStore) -> dict[str, Any]:
    memories = store.list_memories(limit=1_000_000)
    percepts = store.list_percepts()
    unprocessed = store.unprocessed_percepts()

    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    confidences: list[float] = []
    needs_review = 0
    for m in memories:
        by_status[m.status.value] = by_status.get(m.status.value, 0) + 1
        by_type[m.type.value] = by_type.get(m.type.value, 0) + 1
        by_domain[m.domain] = by_domain.get(m.domain, 0) + 1
        confidences.append(m.confidence)
        if m.needs_review:
            needs_review += 1

    confirmed = by_status.get("confirmed", 0)
    rejected = by_status.get("rejected", 0)
    reviewed = confirmed + rejected
    evidence_total = store.count_evidence()
    total = len(memories)

    return {
        "percepts": {
            "total": len(percepts),
            "unprocessed": len(unprocessed),
            "by_sensor": _count(percepts, lambda p: p.source_sensor),
        },
        "memories": {
            "total": total,
            "by_status": by_status,
            "by_type": by_type,
            "by_domain": by_domain,
            "needs_review": needs_review,
            "avg_confidence": round(sum(confidences) / total, 3) if total else 0.0,
        },
        "quality": {
            # share of human-reviewed memories that were approved — proxy for
            # extraction precision (README: "precisão de extração")
            "approval_rate": round(confirmed / reviewed, 3) if reviewed else None,
            # evidence rows beyond 1 per memory come from dedupe merging —
            # proxy for duplicate rate (README: "taxa de memórias duplicadas")
            "duplicate_evidence_ratio": round((evidence_total - total) / total, 3) if total else 0.0,
            "review_backlog_ratio": round(needs_review / total, 3) if total else 0.0,
        },
        "firewall": {
            "blocks_logged": store.count_firewall_blocks(),
        },
    }


def _count(items, key) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        k = key(item)
        out[k] = out.get(k, 0) + 1
    return out
