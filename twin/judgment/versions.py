"""Judgment versioning, snapshots, supersedence and restore."""

from __future__ import annotations

from typing import Any, Optional

from .. import ids
from ..clock import now_iso
from ..memory.models import MemoryOperation
from ..memory.store.base import MemoryStore
from .models import JudgmentItem, JudgmentSnapshot, JudgmentStatus, JudgmentVersion


def active_items(store: MemoryStore) -> list[JudgmentItem]:
    if not hasattr(store, "list_judgment_items"):
        return []
    return store.list_judgment_items(status=JudgmentStatus.active.value)


def create_version(
    store: MemoryStore,
    *,
    reason: str,
    item_ids: Optional[list[str]] = None,
    actor: str = "user",
    parent: Optional[JudgmentVersion] = None,
) -> JudgmentVersion:
    """Activate a new judgment version (never mutates history in place)."""
    parent = parent or store.get_active_judgment_version()
    next_n = (parent.version + 1) if parent else 1
    if item_ids is None:
        item_ids = [i.id for i in active_items(store)]
    store.deactivate_judgment_versions()
    version = JudgmentVersion(
        id=ids.judgment_version_id(),
        version=next_n,
        created_at=now_iso(),
        reason=reason,
        parent_version_id=parent.id if parent else None,
        active=True,
        item_ids=list(item_ids),
        actor=actor,
    )
    store.insert_judgment_version(version)
    _audit(store, "create_judgment_version", version.id, {
        "version": version.version, "item_ids": version.item_ids, "reason": reason,
    }, actor=actor)
    return version


def make_snapshot(
    store: MemoryStore,
    items: list[JudgmentItem],
    *,
    target_domain: str = "technical",
    persona: str = "individual",
    task_profile: str = "general",
    project_id: Optional[str] = None,
) -> JudgmentSnapshot:
    version = store.get_active_judgment_version()
    if version is None:
        version = create_version(store, reason="auto-bootstrap for snapshot")
    snap = JudgmentSnapshot(
        id=ids.judgment_snapshot_id(),
        judgment_version_id=version.id,
        item_ids=[i.id for i in items],
        target_domain=target_domain,
        persona=persona,
        task_profile=task_profile,
        project_id=project_id,
        created_at=now_iso(),
    )
    store.insert_judgment_snapshot(snap)
    return snap


def supersede_item(
    store: MemoryStore,
    old_id: str,
    new_item: JudgmentItem,
    *,
    actor: str = "user",
    reason: str = "",
) -> JudgmentItem:
    old = store.get_judgment_item(old_id)
    if old is None:
        raise ValueError(f"judgment {old_id} not found")
    if old.stability.value == "constitutional":
        raise ValueError(
            "constitutional judgment requires explicit confirmation via "
            "approve_constitutional_change"
        )
    now = now_iso()
    new_item.supersedes = old_id
    new_item.status = JudgmentStatus.active
    new_item.approved_at = now
    new_item.approved_by = actor
    new_item.created_at = new_item.created_at or now
    new_item.updated_at = now
    if not new_item.id:
        new_item.id = ids.judgment_id()
    store.insert_judgment_item(new_item)
    store.update_judgment_item(
        old_id,
        status=JudgmentStatus.superseded.value,
        valid_until=now,
        updated_at=now,
    )
    create_version(
        store,
        reason=reason or f"supersede {old_id} → {new_item.id}",
        actor=actor,
    )
    _audit(store, "supersede_judgment", new_item.id, {
        "old_id": old_id, "new_id": new_item.id,
    }, actor=actor)
    return new_item


def restore_version(
    store: MemoryStore,
    version_id: str,
    *,
    actor: str = "user",
) -> JudgmentVersion:
    """Restore by creating a new active version pointing at the prior item set."""
    target = store.get_judgment_version(version_id)
    if target is None:
        raise ValueError(f"version {version_id} not found")
    # Reactivate items that were active in that version; deprecate others currently active.
    now = now_iso()
    target_set = set(target.item_ids)
    for item in store.list_judgment_items(status=JudgmentStatus.active.value):
        if item.id not in target_set:
            store.update_judgment_item(
                item.id, status=JudgmentStatus.deprecated.value, updated_at=now,
            )
    for jid in target.item_ids:
        item = store.get_judgment_item(jid)
        if item and item.status != JudgmentStatus.active:
            store.update_judgment_item(
                jid, status=JudgmentStatus.active.value, updated_at=now,
            )
    return create_version(
        store,
        reason=f"restore version {target.version}",
        item_ids=list(target.item_ids),
        actor=actor,
        parent=store.get_active_judgment_version(),
    )


def _audit(store: MemoryStore, operation: str, output: str, after: dict[str, Any],
           *, actor: str) -> None:
    if not hasattr(store, "insert_operation"):
        return
    store.insert_operation(MemoryOperation(
        id=ids.operation_id(),
        operation=operation,
        actor=actor,
        at=now_iso(),
        inputs=[],
        output=output,
        before={},
        after=after,
        undoable=True,
    ))
