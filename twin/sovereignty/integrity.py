"""Integrity checks for sovereignty / runtime integrity_check job."""

from __future__ import annotations

from typing import Any

from twin.memory.store.base import MemoryStore


def run_integrity_checks(store: MemoryStore) -> dict[str, Any]:
    problems: list[str] = []
    stats: dict[str, int] = {}

    memories = []
    for status in ("candidate", "confirmed", "rejected"):
        memories.extend(store.list_memories(status=status, limit=5_000))
    stats["memories"] = len(memories)

    orphan_evidence = 0
    missing_evidence = 0
    for mem in memories:
        evs = store.get_evidence(mem.id)
        if not evs and mem.status.value == "confirmed":
            missing_evidence += 1
            problems.append(f"confirmed memory {mem.id} has no evidence")
        for ev in evs:
            if hasattr(store, "get_percept") and store.get_percept(ev.percept_id) is None:
                orphan_evidence += 1
                problems.append(
                    f"evidence {ev.id} references missing percept {ev.percept_id}"
                )
    stats["orphan_evidence"] = orphan_evidence
    stats["confirmed_without_evidence"] = missing_evidence

    if hasattr(store, "runtime_queue_depth"):
        stats.update({f"queue_{k}": v for k, v in store.runtime_queue_depth().items()})

    if hasattr(store, "list_runtime_dead_letters"):
        dlq = store.list_runtime_dead_letters(limit=500)
        stats["dead_letters_open"] = len(dlq)

    return {
        "ok": len(problems) == 0,
        "problems": problems[:100],
        "problem_count": len(problems),
        "stats": stats,
    }
