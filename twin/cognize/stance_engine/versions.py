"""Judgment versioning, snapshots, supersedence and restore.

Versions point at immutable revision IDs. Restore appends restoring revisions;
it never rewrites historical revision rows.
"""

from __future__ import annotations

from typing import Any, Optional

from twin import ids
from twin.clock import now_iso
from twin.store.models import ClaimOperation
from twin.store.store.base import TwinStore
from .models import (
    AppliedRevisionRef,
    JudgmentItem,
    JudgmentSnapshot,
    JudgmentStatus,
    JudgmentVersion,
)
from .revisions import clone_revision_as_new, commit_new_item, commit_new_revision, item_from_revision


def active_items(store: TwinStore) -> list[JudgmentItem]:
    if not hasattr(store, "list_judgment_items"):
        return []
    return store.list_judgment_items(status=JudgmentStatus.active.value)


def active_revision_ids(store: TwinStore) -> list[str]:
    ids_out: list[str] = []
    for item in active_items(store):
        if item.current_revision_id:
            ids_out.append(item.current_revision_id)
    return ids_out


def create_version(
    store: TwinStore,
    *,
    reason: str,
    revision_ids: Optional[list[str]] = None,
    item_ids: Optional[list[str]] = None,
    actor: str = "user",
    parent: Optional[JudgmentVersion] = None,
    expected_parent_version_id: Optional[str] = None,
) -> JudgmentVersion:
    """Activate a new judgment version inside the caller's transaction if any."""
    parent = parent or store.get_active_judgment_version()
    if expected_parent_version_id is not None:
        current_id = parent.id if parent else None
        if current_id != expected_parent_version_id:
            raise ValueError(
                f"optimistic concurrency conflict: expected parent "
                f"{expected_parent_version_id}, found {current_id}"
            )
    next_n = (parent.version + 1) if parent else 1
    if revision_ids is None:
        revision_ids = active_revision_ids(store)
    if item_ids is None:
        item_ids = []
        for rid in revision_ids:
            rev = store.get_judgment_revision(rid)
            if rev:
                item_ids.append(rev.judgment_id)
    store.deactivate_judgment_versions()
    version = JudgmentVersion(
        id=ids.judgment_version_id(),
        version=next_n,
        created_at=now_iso(),
        reason=reason,
        parent_version_id=parent.id if parent else None,
        active=True,
        revision_ids=list(revision_ids),
        item_ids=list(dict.fromkeys(item_ids)),
        actor=actor,
    )
    try:
        store.insert_judgment_version(version)
    except ValueError:
        raise
    except Exception as exc:
        msg = str(exc).lower()
        if "unique" in msg or "duplicate" in msg or "constraint" in msg:
            raise ValueError(f"version conflict creating v{next_n}: {exc}") from exc
        raise
    _audit(store, "create_judgment_version", version.id, {
        "version": version.version,
        "revision_ids": version.revision_ids,
        "reason": reason,
    }, actor=actor, undoable=False)
    return version


def make_snapshot(
    store: TwinStore,
    applied: list[AppliedRevisionRef],
    *,
    context: Optional[dict[str, Any]] = None,
    persist: bool = True,
) -> JudgmentSnapshot:
    ctx = context or {}
    version = store.get_active_judgment_version()
    if version is None and persist:
        version = create_version(store, reason="auto-bootstrap for snapshot")
    snap = JudgmentSnapshot(
        id=ids.judgment_snapshot_id(),
        judgment_version_id=version.id if version else "",
        item_ids=[a.judgment_id for a in applied],
        applied_revisions=applied,
        target_domain=ctx.get("domain", "technical"),
        persona=ctx.get("persona", "individual"),
        task_profile=ctx.get("task_profile", "general"),
        project_id=ctx.get("project_id"),
        audience=ctx.get("audience"),
        client=ctx.get("client"),
        project_stage=ctx.get("project_stage"),
        application_engine="judgment-app-v2",
        created_at=now_iso(),
    )
    if persist:
        store.insert_judgment_snapshot(snap)
    return snap


def supersede_item(
    store: TwinStore,
    old_id: str,
    new_item: JudgmentItem,
    *,
    actor: str = "user",
    reason: str = "",
    confirm_constitutional: bool = False,
    expected_parent_version_id: Optional[str] = None,
) -> tuple[JudgmentItem, JudgmentVersion]:
    old = store.get_judgment_item(old_id)
    if old is None:
        raise ValueError(f"judgment {old_id} not found")
    if old.stability.value == "constitutional" and not confirm_constitutional:
        raise ValueError("constitutional judgment requires confirm_constitutional=True")
    now = now_iso()
    old_next = old.model_copy(deep=True)
    old_next.status = JudgmentStatus.superseded
    old_next.valid_until = now
    commit_new_revision(
        store, old_next, actor=actor, reason="superseded by new item",
    )
    new_item.supersedes = old_id
    new_item.status = JudgmentStatus.active
    new_item.approved_at = now
    new_item.approved_by = actor
    if not new_item.id:
        new_item.id = ids.judgment_id()
    new_item, new_rev = commit_new_item(
        store, new_item, actor=actor, reason=reason or f"supersede {old_id}",
    )
    version = create_version(
        store,
        reason=reason or f"supersede {old_id} → {new_item.id}",
        revision_ids=active_revision_ids(store),
        actor=actor,
        expected_parent_version_id=expected_parent_version_id,
    )
    _audit(store, "supersede_judgment", new_item.id, {
        "old_id": old_id, "new_id": new_item.id, "new_revision": new_rev.id,
    }, actor=actor, undoable=False)
    return new_item, version


def restore_version(
    store: TwinStore,
    version_id: str,
    *,
    actor: str = "user",
) -> JudgmentVersion:
    """Restore composition by cloning historical revisions into new revisions."""
    target = store.get_judgment_version(version_id)
    if target is None:
        raise ValueError(f"version {version_id} not found")
    source_revs = target.revision_ids or []
    if not source_revs:
        # legacy versions that only stored item_ids — clone current heads of those ids
        for jid in target.item_ids:
            item = store.get_judgment_item(jid)
            if item and item.current_revision_id:
                source_revs.append(item.current_revision_id)

    new_revision_ids: list[str] = []
    restored_ids: set[str] = set()
    for rid in source_revs:
        src = store.get_judgment_revision(rid)
        if src is None:
            continue
        item, rev = clone_revision_as_new(
            store, src, actor=actor,
            reason=f"restore from {rid}",
            status=JudgmentStatus.active.value,
        )
        new_revision_ids.append(rev.id)
        restored_ids.add(item.id)

    # Deprecate currently-active identities not in the restore set via new revisions
    for item in active_items(store):
        if item.id in restored_ids:
            continue
        nxt = item.model_copy(deep=True)
        nxt.status = JudgmentStatus.deprecated
        _, rev = commit_new_revision(
            store, nxt, actor=actor, reason=f"deprecated by restore of {version_id}",
        )
        # not included in restored active set

    return create_version(
        store,
        reason=f"restore version {target.version}",
        revision_ids=new_revision_ids,
        actor=actor,
        parent=store.get_active_judgment_version(),
    )


def _audit(store: TwinStore, operation: str, output: str, after: dict[str, Any],
           *, actor: str, undoable: bool = False) -> None:
    if not hasattr(store, "insert_operation"):
        return
    store.insert_operation(ClaimOperation(
        id=ids.operation_id(),
        operation=operation,
        actor=actor,
        at=now_iso(),
        inputs=[],
        output=output,
        before={},
        after=after,
        undoable=undoable,
    ))
