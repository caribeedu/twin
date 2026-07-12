"""Retention, archival and deletion propagation.

When a source/artifact disappears, derived percepts, evidence and memories
must follow — either tombstoned (audit preserved, content destroyed) or
recalculated when corroborating evidence remains.
"""

from __future__ import annotations

from typing import Any, Optional

from ..clock import now_iso
from .models import MemoryStatus
from .store.base import MemoryStore


def delete_artifact(
    store: MemoryStore,
    artifact_id: str,
    *,
    dry_run: bool = False,
    destroy_content: bool = True,
    reason: str = "source_removed",
) -> dict[str, Any]:
    """Propagate artifact deletion through percepts → evidence → memories."""
    if not hasattr(store, "get_artifact"):
        raise ValueError("store does not support artifacts")
    art = store.get_artifact(artifact_id)  # type: ignore[attr-defined]
    if art is None:
        raise ValueError(f"artifact {artifact_id} not found")

    plan: dict[str, Any] = {
        "artifact_id": artifact_id,
        "dry_run": dry_run,
        "percepts": [],
        "evidence": [],
        "memories_unsupported": [],
        "memories_recalculated": [],
        "writes": 0,
    }

    # find percepts linked via artifact metadata or evidence.artifact_id
    percept_ids: set[str] = set()
    if art.metadata.get("percept_id"):
        percept_ids.add(art.metadata["percept_id"])
    if hasattr(store, "list_evidence_for_artifact"):
        for ev in store.list_evidence_for_artifact(artifact_id):  # type: ignore[attr-defined]
            plan["evidence"].append(ev.id)
            percept_ids.add(ev.percept_id)

    # also match by content hash
    if art.content_hash:
        for p in store.list_percepts():
            if p.content_hash == art.content_hash:
                percept_ids.add(p.id)

    affected_memories: dict[str, list[str]] = {}  # memory_id → evidence ids from this source
    for pid in percept_ids:
        plan["percepts"].append(pid)
        # evidence rows referencing this percept
        for mem in store.list_memories(limit=1_000_000):
            for ev in store.get_evidence(mem.id):
                if ev.percept_id == pid or ev.artifact_id == artifact_id:
                    plan["evidence"].append(ev.id)
                    affected_memories.setdefault(mem.id, []).append(ev.id)

    for mid, ev_ids in affected_memories.items():
        all_ev = store.get_evidence(mid)
        remaining = [e for e in all_ev if e.id not in ev_ids]
        if not remaining:
            plan["memories_unsupported"].append(mid)
        else:
            plan["memories_recalculated"].append(mid)

    if dry_run:
        return plan

    # tombstone artifact
    if hasattr(store, "tombstone_artifact"):
        store.tombstone_artifact(artifact_id, reason=reason, destroy_content=destroy_content)  # type: ignore[attr-defined]
        plan["writes"] += 1

    for pid in percept_ids:
        if hasattr(store, "tombstone_percept"):
            store.tombstone_percept(pid, reason=reason, destroy_content=destroy_content)  # type: ignore[attr-defined]
            plan["writes"] += 1

    for mid, ev_ids in affected_memories.items():
        if hasattr(store, "tombstone_evidence"):
            for eid in ev_ids:
                store.tombstone_evidence(eid, reason=reason)  # type: ignore[attr-defined]
                plan["writes"] += 1
        mem = store.get_memory(mid)
        if mem is None:
            continue
        remaining = [e for e in store.get_evidence(mid) if e.id not in ev_ids]
        # After tombstone, get_evidence may still return rows — prefer recount via flag
        if mid in plan["memories_unsupported"] or not remaining:
            store.update_memory(
                mid,
                status=MemoryStatus.unsupported.value,
                needs_review=True,
                review_reason="all supporting evidence removed",
                confidence=0.0,
            )
            if hasattr(store, "delete_embedding"):
                store.delete_embedding(mid)  # type: ignore[attr-defined]
            plan["writes"] += 1
        else:
            # recalculate confidence from remaining independent groups
            groups = {e.independence_group or e.percept_id for e in remaining if e.supports}
            new_conf = min(0.95, 0.5 + 0.1 * len(groups))
            store.update_memory(mid, confidence=round(new_conf, 3))
            plan["writes"] += 1

    return plan


def delete_by_source_system(
    store: MemoryStore,
    source_system: str,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Delete everything derived from a source system / account."""
    if not hasattr(store, "list_artifacts"):
        raise ValueError("store does not support artifacts")
    arts = [a for a in store.list_artifacts()  # type: ignore[attr-defined]
            if a.source_system == source_system and not a.deleted_at]
    results = []
    for art in arts:
        results.append(delete_artifact(store, art.id, dry_run=dry_run))
    return {
        "source_system": source_system,
        "dry_run": dry_run,
        "artifacts": len(arts),
        "details": results,
    }


def mark_stale(store: MemoryStore, memory_id: str, reason: str = "stale") -> None:
    store.update_memory(
        memory_id,
        status=MemoryStatus.stale.value,
        needs_review=True,
        review_reason=reason,
    )


def apply_retention_policies(
    store: MemoryStore,
    *,
    dry_run: bool = True,
    archive_completed_tasks: bool = True,
) -> dict[str, Any]:
    """Safe archival of expired completed tasks and unsupported memories."""
    actions: list[dict[str, Any]] = []
    for mem in store.list_memories(limit=1_000_000):
        if mem.status.value == MemoryStatus.unsupported.value:
            actions.append({"id": mem.id, "action": "archive", "reason": "unsupported"})
        elif (
            archive_completed_tasks
            and mem.type.value == "task"
            and mem.payload.get("status") in ("done", "completed", "cancelled")
            and mem.valid_until
        ):
            actions.append({"id": mem.id, "action": "archive", "reason": "expired_task"})
    if dry_run:
        return {"dry_run": True, "actions": actions, "count": len(actions)}
    from .lifecycle import archive_memory
    for a in actions:
        archive_memory(store, a["id"], reason=a["reason"], actor="retention")
    return {"dry_run": False, "actions": actions, "count": len(actions)}
