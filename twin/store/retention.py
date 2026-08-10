"""Retention, archival and deletion propagation.

Deletion uses explicit artifact↔percept links only — never content-hash ownership.
Shared percepts are tombstoned only when no remaining artifact links exist.
"""

from __future__ import annotations

from typing import Any, Optional

from ..clock import now_iso
from .models import ClaimStatus
from .store.base import MemoryStore


def delete_artifact(
    store: MemoryStore,
    artifact_id: str,
    *,
    dry_run: bool = False,
    destroy_content: bool = True,
    reason: str = "source_removed",
) -> dict[str, Any]:
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
        "percepts_unlinked_only": [],
        "writes": 0,
    }

    if hasattr(store, "list_percept_ids_for_artifact"):
        percept_ids = store.list_percept_ids_for_artifact(artifact_id)  # type: ignore[attr-defined]
    else:
        percept_ids = []
        if art.metadata.get("percept_id"):
            percept_ids.append(art.metadata["percept_id"])
        if hasattr(store, "list_evidence_for_artifact"):
            for ev in store.list_evidence_for_artifact(artifact_id):  # type: ignore[attr-defined]
                percept_ids.append(ev.percept_id)
        percept_ids = list(dict.fromkeys(percept_ids))

    plan["percepts"] = list(percept_ids)

    # indexed evidence lookup when available
    if hasattr(store, "list_evidence_by_percept_ids"):
        evidence_rows = store.list_evidence_by_percept_ids(percept_ids)  # type: ignore[attr-defined]
    else:
        evidence_rows = []
        for mid_mem in store.list_claims(limit=1_000_000):
            for ev in store.get_evidence(mid_mem.id):
                if ev.percept_id in percept_ids or ev.artifact_id == artifact_id:
                    evidence_rows.append(ev)

    # only evidence that belongs to this artifact (explicit artifact_id) or
    # to percepts solely linked to this artifact
    affected_memories: dict[str, list[str]] = {}
    for ev in evidence_rows:
        if ev.artifact_id and ev.artifact_id != artifact_id:
            continue
        if ev.artifact_id == artifact_id or ev.percept_id in percept_ids:
            plan["evidence"].append(ev.id)
            affected_memories.setdefault(ev.claim_id, []).append(ev.id)

    for mid, ev_ids in affected_memories.items():
        all_ev = store.get_evidence(mid)
        remaining = [e for e in all_ev if e.id not in ev_ids]
        if not remaining:
            plan["memories_unsupported"].append(mid)
        else:
            plan["memories_recalculated"].append(mid)

    if dry_run:
        return plan

    with store.transaction():
        if hasattr(store, "tombstone_artifact"):
            store.tombstone_artifact(artifact_id, reason=reason, destroy_content=destroy_content)  # type: ignore[attr-defined]
            plan["writes"] += 1

        for pid in percept_ids:
            if hasattr(store, "unlink_artifact_percept"):
                store.unlink_artifact_percept(artifact_id, pid)  # type: ignore[attr-defined]
            remaining_links = 0
            if hasattr(store, "count_artifact_links_for_percept"):
                remaining_links = store.count_artifact_links_for_percept(pid)  # type: ignore[attr-defined]
            # also count other artifacts that explicitly list this percept
            if remaining_links == 0 and hasattr(store, "list_artifacts"):
                for other in store.list_artifacts():  # type: ignore[attr-defined]
                    if other.id == artifact_id or other.deleted_at:
                        continue
                    if other.metadata.get("percept_id") == pid:
                        remaining_links += 1
            if remaining_links > 0:
                plan["percepts_unlinked_only"].append(pid)
                continue
            if hasattr(store, "tombstone_percept"):
                store.tombstone_percept(pid, reason=reason, destroy_content=destroy_content)  # type: ignore[attr-defined]
                plan["writes"] += 1
                try:
                    from twin.cognize.acl import tombstone_narratives_for_percept

                    touched = tombstone_narratives_for_percept(
                        store, pid, reason=reason,
                    )
                    plan.setdefault("narratives_tombstoned", []).extend(touched)
                    plan["writes"] += len(touched)
                except Exception:
                    pass

        for mid, ev_ids in affected_memories.items():
            if hasattr(store, "tombstone_evidence"):
                for eid in ev_ids:
                    store.tombstone_evidence(eid, reason=reason)  # type: ignore[attr-defined]
                    plan["writes"] += 1
            mem = store.get_claim(mid)
            if mem is None:
                continue
            remaining = [e for e in store.get_evidence(mid) if e.id not in set(ev_ids)]
            if mid in plan["memories_unsupported"] or not remaining:
                store.update_claim(
                    mid,
                    status=ClaimStatus.unsupported.value,
                    needs_review=True,
                    review_reason="all supporting evidence removed",
                    confidence=0.0,
                )
                if hasattr(store, "delete_embedding"):
                    store.delete_embedding(mid)  # type: ignore[attr-defined]
                plan["writes"] += 1
            else:
                groups = {e.independence_group or e.percept_id for e in remaining if e.supports}
                new_conf = min(0.95, 0.5 + 0.1 * len(groups))
                store.update_claim(mid, confidence=round(new_conf, 3))
                plan["writes"] += 1

    return plan


def delete_by_source_system(
    store: MemoryStore,
    source_system: str,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
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


def mark_stale(store: MemoryStore, claim_id: str, reason: str = "stale") -> None:
    store.update_claim(
        claim_id,
        status=ClaimStatus.stale.value,
        needs_review=True,
        review_reason=reason,
    )


def apply_retention_policies(
    store: MemoryStore,
    *,
    dry_run: bool = True,
    archive_completed_tasks: bool = True,
    min_age_days: int = 30,
) -> dict[str, Any]:
    from datetime import datetime, timezone
    actions: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for mem in store.list_claims(limit=1_000_000):
        if mem.status.value == ClaimStatus.unsupported.value:
            actions.append({"id": mem.id, "action": "archive", "reason": "unsupported"})
        elif (
            archive_completed_tasks
            and mem.type.value == "task"
            and mem.payload.get("status") in ("done", "completed", "cancelled")
            and mem.valid_until
        ):
            try:
                until = datetime.fromisoformat(mem.valid_until.replace("Z", "+00:00"))
                if until.tzinfo is None:
                    until = until.replace(tzinfo=timezone.utc)
                if (now - until).days >= min_age_days:
                    actions.append({"id": mem.id, "action": "archive", "reason": "expired_task"})
            except ValueError:
                pass
    if dry_run:
        return {"dry_run": True, "actions": actions, "count": len(actions)}
    from .lifecycle import archive_memory
    for a in actions:
        archive_memory(store, a["id"], reason=a["reason"], actor="retention")
    return {"dry_run": False, "actions": actions, "count": len(actions)}
