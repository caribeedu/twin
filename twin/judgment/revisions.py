"""Immutable judgment revisions — never rewrite past content."""

from __future__ import annotations

from typing import Optional

from .. import ids
from ..clock import now_iso
from twin.store.store.base import MemoryStore
from .models import JudgmentItem, JudgmentRevision, JudgmentStatus
from .persistence import item_payload


def item_from_revision(rev: JudgmentRevision) -> JudgmentItem:
    data = dict(rev.payload)
    data["id"] = rev.judgment_id
    data["current_revision_id"] = rev.id
    data["revision"] = rev.revision
    return JudgmentItem(**data)


def create_revision(
    store: MemoryStore,
    item: JudgmentItem,
    *,
    actor: str = "user",
    reason: str = "",
    revision_number: Optional[int] = None,
) -> JudgmentRevision:
    """Persist an immutable revision and point the head item at it."""
    n = revision_number if revision_number is not None else max(1, int(item.revision or 1))
    rev = JudgmentRevision(
        id=ids.judgment_revision_id(),
        judgment_id=item.id,
        revision=n,
        payload=item_payload(item),
        created_at=now_iso(),
        actor=actor,
        reason=reason,
    )
    store.insert_judgment_revision(rev)
    item.current_revision_id = rev.id
    item.revision = n
    return rev


def commit_new_item(
    store: MemoryStore,
    item: JudgmentItem,
    *,
    actor: str = "user",
    reason: str = "create",
) -> tuple[JudgmentItem, JudgmentRevision]:
    item.revision = 1
    item.created_at = item.created_at or now_iso()
    item.updated_at = now_iso()
    rev = create_revision(store, item, actor=actor, reason=reason, revision_number=1)
    store.insert_judgment_item(item)
    return item, rev


def commit_new_revision(
    store: MemoryStore,
    item: JudgmentItem,
    *,
    actor: str = "user",
    reason: str = "update",
) -> tuple[JudgmentItem, JudgmentRevision]:
    """Create next immutable revision and refresh head fields (status etc.)."""
    existing = store.get_judgment_item(item.id)
    next_n = (existing.revision + 1) if existing else max(1, item.revision)
    item.revision = next_n
    item.updated_at = now_iso()
    rev = create_revision(store, item, actor=actor, reason=reason, revision_number=next_n)
    if existing is None:
        store.insert_judgment_item(item)
    else:
        store.update_judgment_item(
            item.id,
            **{
                k: v for k, v in item.model_dump(mode="json").items()
                if k != "id"
            },
        )
    return item, rev


def clone_revision_as_new(
    store: MemoryStore,
    source: JudgmentRevision,
    *,
    actor: str = "user",
    reason: str = "restore",
    status: Optional[str] = None,
) -> tuple[JudgmentItem, JudgmentRevision]:
    """Restore historical content by appending a new revision (never rewrite)."""
    item = item_from_revision(source)
    if status:
        item.status = JudgmentStatus(status)
    return commit_new_revision(store, item, actor=actor, reason=reason)
