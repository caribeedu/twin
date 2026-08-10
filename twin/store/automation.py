"""Safe low-risk automation for quality findings.

Exact duplicates are handled as groups with a single canonical survivor.
Beliefs, conflicts and sensitive merges are never auto-applied.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from ..clock import now_iso
from .calibration import DEFAULT_CALIBRATION
from .lifecycle import archive_memory
from .models import MemoryStatus, Sensitivity
from .provenance import attach_corroborating_evidence
from .store.base import MemoryStore
from twin.cognize.services.quality import build_duplicate_groups

_SENS_ORDER = ["public", "internal", "private", "restricted"]


def _sens_ok(mem_sens: str, max_sens: str) -> bool:
    try:
        return _SENS_ORDER.index(mem_sens) <= _SENS_ORDER.index(max_sens)
    except ValueError:
        return False


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def apply_safe_automations(
    store: MemoryStore,
    *,
    calibration: Optional[dict[str, Any]] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    cal = calibration or DEFAULT_CALIBRATION
    policy = cal.get("quality_automation", {})
    actions: list[dict[str, Any]] = []
    rejected_this_run: set[str] = set()

    # --- exact duplicate groups ------------------------------------------
    rule = policy.get("exact_duplicate", {})
    if rule.get("action") == "reject":
        pool = [
            m for m in store.list_memories(limit=10_000)
            if "exact_duplicate" in m.quality_flags
            and m.status.value not in ("rejected", "merged", "split", "deleted", "archived")
        ]
        for group in build_duplicate_groups(store, pool):
            survivor = store.get_memory(group.canonical_memory_id)
            if survivor is None:
                continue
            if not _sens_ok(survivor.sensitivity.value, rule.get("max_sensitivity", "internal")):
                actions.append({
                    "group": group.memory_ids, "action": "skip",
                    "reason": "sensitivity_gate",
                })
                continue
            for mid in group.memory_ids:
                if mid == survivor.id or mid in rejected_this_run:
                    continue
                other = store.get_memory(mid)
                if other is None:
                    continue
                actions.append({
                    "id": mid, "action": "reject", "reason": "exact_duplicate",
                    "survivor": survivor.id,
                })
                if dry_run:
                    continue
                # attach evidence to survivor then reject duplicate
                for ev in store.get_evidence(mid):
                    attach_corroborating_evidence(
                        store, survivor.id, ev.percept_id, ev.quote,
                        independence_group=ev.independence_group,
                        source_trust=ev.source_trust,
                        bump_confidence=True,
                    )
                store.set_status(mid, MemoryStatus.rejected)
                rejected_this_run.add(mid)
            actions.append({
                "id": survivor.id, "action": "keep", "reason": "canonical_survivor",
                "group": group.memory_ids,
            })

    # --- expired tasks (policy-gated) ------------------------------------
    task_rule = policy.get("expired_task", {})
    if task_rule.get("action") == "archive":
        min_age_days = int(task_rule.get("min_age_days", 30))
        require_valid_until = bool(task_rule.get("require_valid_until", True))
        allowed = set(task_rule.get("allowed_terminal_states", ["completed", "cancelled"]))
        now = datetime.now(timezone.utc)
        for mem in store.list_memories(type_="task", limit=5_000):
            if mem.status.value in ("archived", "deleted", "rejected", "merged", "split"):
                continue
            terminal = mem.payload.get("status")
            if terminal not in allowed:
                continue
            if require_valid_until and not mem.valid_until:
                continue
            anchor = _parse_iso(mem.valid_until) or _parse_iso(mem.updated_at) or _parse_iso(mem.created_at)
            if anchor is None:
                continue
            if anchor.tzinfo is None:
                anchor = anchor.replace(tzinfo=timezone.utc)
            age_days = (now - anchor).days
            if age_days < min_age_days:
                continue
            actions.append({
                "id": mem.id, "action": "archive", "reason": "expired_task",
                "age_days": age_days,
            })
            if not dry_run:
                archive_memory(store, mem.id, reason="expired_task", actor="automation")

    return {
        "dry_run": dry_run,
        "at": now_iso(),
        "actions": actions,
        "applied": 0 if dry_run else sum(
            1 for a in actions if a.get("action") in ("reject", "archive")
        ),
    }


def _memory_version_slice(m) -> dict[str, Any]:
    """Stable per-memory state included in preview tokens (TOCTOU guard)."""
    import hashlib

    content_hash = hashlib.sha256(
        f"{m.title}\n{m.summary}".encode()
    ).hexdigest()[:16]
    return {
        "id": m.id,
        "updated_at": m.updated_at or "",
        "status": m.status.value if hasattr(m.status, "value") else str(m.status),
        "domain": m.domain,
        "sensitivity": (
            m.sensitivity.value if hasattr(m.sensitivity, "value") else str(m.sensitivity)
        ),
        "project_id": m.project_id or "",
        "quality_flags": sorted(m.quality_flags or []),
        "content_hash": content_hash,
    }


def compute_preview_token(action: str, memories: list) -> str:
    """Hash action + ordered memory version slices."""
    import hashlib
    import json

    payload = {
        "action": action,
        "count": len(memories),
        "memories": sorted(
            (_memory_version_slice(m) for m in memories),
            key=lambda row: row["id"],
        ),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def batch_preview(
    store: MemoryStore,
    memory_ids: list[str],
    action: str,
) -> dict[str, Any]:
    memories = []
    projects: set[str] = set()
    sensitive = 0
    conflicts = 0
    domains: set[str] = set()
    for mid in memory_ids:
        m = store.get_memory(mid)
        if m is None:
            continue
        memories.append(m)
        domains.add(m.domain)
        if m.project_id:
            projects.add(m.project_id)
        if m.sensitivity in (Sensitivity.private, Sensitivity.restricted):
            sensitive += 1
        if "possible_conflict" in m.quality_flags:
            conflicts += 1

    individual_only = action in (
        "merge", "split", "contradict", "supersede", "confirm_belief",
    ) or sensitive > 0 or conflicts > 0 or len(domains) > 1

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
        "preview_token": compute_preview_token(action, memories),
    }


def batch_apply(
    store: MemoryStore,
    memory_ids: list[str],
    action: str,
    *,
    force: bool = False,
    actor: str = "user",
    preview_token: Optional[str] = None,
    require_preview_token: bool = True,
) -> dict[str, Any]:
    """Apply a batch action previously previewed.

    ``preview_token`` is mandatory for external/API callers (default). Pass
    ``require_preview_token=False`` only for privileged internal automations.
    The token covers selection *and* reviewed memory state (updated_at, status,
    domain, sensitivity, content, project, quality flags).
    """
    preview = batch_preview(store, memory_ids, action)
    if require_preview_token:
        if not preview_token:
            return {**preview, "applied": 0, "error": "preview_token_required"}
        if preview_token != preview["preview_token"]:
            return {**preview, "applied": 0, "error": "preview_token_mismatch"}
    elif preview_token and preview_token != preview["preview_token"]:
        return {**preview, "applied": 0, "error": "preview_token_mismatch"}
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
