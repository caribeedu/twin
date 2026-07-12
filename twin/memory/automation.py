"""Safe low-risk automation for quality findings.

Allowed under policy: reject exact duplicates, attach corroboration,
archive expired tasks, normalize aliases. Never auto-confirm beliefs,
resolve contradictions, or merge sensitive memories.
"""

from __future__ import annotations

from typing import Any, Optional

from ..clock import now_iso
from ..memory.calibration import DEFAULT_CALIBRATION, load_calibration
from ..memory.lifecycle import archive_memory
from ..memory.models import MemoryStatus, Sensitivity
from ..memory.store.base import MemoryStore

_SENS_ORDER = ["public", "internal", "private", "restricted"]


def _sens_ok(mem_sens: str, max_sens: str) -> bool:
    try:
        return _SENS_ORDER.index(mem_sens) <= _SENS_ORDER.index(max_sens)
    except ValueError:
        return False


def apply_safe_automations(
    store: MemoryStore,
    *,
    calibration: Optional[dict[str, Any]] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    cal = calibration or DEFAULT_CALIBRATION
    policy = cal.get("quality_automation", {})
    actions: list[dict[str, Any]] = []

    # exact duplicates flagged on candidates
    for mem in store.list_memories(status="candidate", limit=5_000):
        if "exact_duplicate" not in mem.quality_flags:
            continue
        rule = policy.get("exact_duplicate", {})
        if rule.get("action") != "reject":
            continue
        if not _sens_ok(mem.sensitivity.value, rule.get("max_sensitivity", "internal")):
            actions.append({"id": mem.id, "action": "skip", "reason": "sensitivity_gate"})
            continue
        actions.append({"id": mem.id, "action": "reject", "reason": "exact_duplicate"})
        if not dry_run:
            store.set_status(mem.id, MemoryStatus.rejected)

    # expired completed tasks
    if policy.get("expired_task", {}).get("action") == "archive":
        for mem in store.list_memories(type_="task", limit=5_000):
            if mem.status.value in ("archived", "deleted", "rejected"):
                continue
            if mem.payload.get("status") in ("done", "completed", "cancelled"):
                actions.append({"id": mem.id, "action": "archive", "reason": "expired_task"})
                if not dry_run:
                    archive_memory(store, mem.id, reason="expired_task", actor="automation")

    return {
        "dry_run": dry_run,
        "at": now_iso(),
        "actions": actions,
        "applied": 0 if dry_run else sum(1 for a in actions if a["action"] != "skip"),
    }


def batch_preview(
    store: MemoryStore,
    memory_ids: list[str],
    action: str,
) -> dict[str, Any]:
    """Preview a batch curation action before apply."""
    memories = []
    projects: set[str] = set()
    sensitive = 0
    conflicts = 0
    for mid in memory_ids:
        m = store.get_memory(mid)
        if m is None:
            continue
        memories.append(m)
        if m.project_id:
            projects.add(m.project_id)
        if m.sensitivity in (Sensitivity.private, Sensitivity.restricted):
            sensitive += 1
        if "possible_conflict" in m.quality_flags:
            conflicts += 1

    individual_only = action in (
        "merge", "split", "contradict", "supersede", "confirm_belief",
    ) or sensitive > 0 or conflicts > 0

    # beliefs / judgment always individual
    if any(m.type.value in ("belief",) for m in memories):
        individual_only = True

    return {
        "selected": len(memories),
        "action": action,
        "affected_projects": sorted(projects),
        "sensitive_memories": sensitive,
        "conflicts_detected": conflicts,
        "requires_individual_review": individual_only,
        "memory_ids": [m.id for m in memories],
    }


def batch_apply(
    store: MemoryStore,
    memory_ids: list[str],
    action: str,
    *,
    force: bool = False,
    actor: str = "user",
) -> dict[str, Any]:
    preview = batch_preview(store, memory_ids, action)
    if preview["requires_individual_review"] and not force:
        return {**preview, "applied": 0, "error": "requires_individual_review"}

    applied = []
    for mid in preview["memory_ids"]:
        m = store.get_memory(mid)
        if m is None:
            continue
        if action == "confirm":
            if m.type.value in ("belief",) and not force:
                continue
            store.set_status(mid, MemoryStatus.confirmed)
            store.update_memory(mid, reviewed_at=now_iso())
            applied.append(mid)
        elif action == "reject":
            store.set_status(mid, MemoryStatus.rejected)
            store.update_memory(mid, reviewed_at=now_iso())
            applied.append(mid)
        elif action == "archive":
            archive_memory(store, mid, actor=actor)
            applied.append(mid)
        elif action == "defer":
            store.update_memory(mid, needs_review=True, review_reason="deferred")
            applied.append(mid)
        else:
            return {**preview, "applied": 0, "error": f"unsupported batch action: {action}"}

    return {**preview, "applied": len(applied), "memory_ids_applied": applied}
