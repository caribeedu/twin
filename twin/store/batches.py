"""Review batches — pause/resume curated review sets."""

from __future__ import annotations

from typing import Any, Optional

from .. import ids
from ..clock import now_iso
from .models import ReviewBatch
from .store.base import TwinStore


def create_batch(
    store: TwinStore,
    name: str,
    *,
    query: Optional[dict[str, Any]] = None,
    claim_ids: Optional[list[str]] = None,
) -> ReviewBatch:
    query = query or {}
    ids_list = list(claim_ids or [])
    if not ids_list:
        memories = store.list_claims(
            status=query.get("status", "candidate"),
            domain=query.get("domain"),
            type_=query.get("type"),
            project_id=query.get("project_id"),
            needs_review=query.get("needs_review", True),
            limit=query.get("limit", 500),
        )
        # optional source sensor filter via percept chain
        sensor = query.get("source_sensor")
        if sensor:
            filtered = []
            for m in memories:
                for pid in m.percept_ids:
                    p = store.get_percept(pid)
                    if p and p.source_sensor == sensor:
                        filtered.append(m)
                        break
            memories = filtered
        ids_list = [m.id for m in memories]

    batch = ReviewBatch(
        id=ids.review_batch_id(),
        name=name,
        query=query,
        claim_ids=ids_list,
        created_at=now_iso(),
        progress_total=len(ids_list),
        progress_reviewed=0,
    )
    if hasattr(store, "insert_review_batch"):
        store.insert_review_batch(batch)  # type: ignore[attr-defined]
        for mid in ids_list:
            store.update_claim(mid, review_batch_id=batch.id)
    return batch


def get_batch(store: TwinStore, batch_id: str) -> Optional[ReviewBatch]:
    if not hasattr(store, "get_review_batch"):
        return None
    return store.get_review_batch(batch_id)  # type: ignore[attr-defined]


def mark_reviewed(store: TwinStore, batch_id: str, claim_id: str) -> Optional[ReviewBatch]:
    batch = get_batch(store, batch_id)
    if batch is None:
        return None
    store.update_claim(claim_id, reviewed_at=now_iso(), review_batch_id=batch_id)
    reviewed = batch.progress_reviewed + 1
    completed = now_iso() if reviewed >= batch.progress_total else None
    if hasattr(store, "update_review_batch"):
        store.update_review_batch(  # type: ignore[attr-defined]
            batch_id, progress_reviewed=reviewed, completed_at=completed,
        )
    batch.progress_reviewed = reviewed
    batch.completed_at = completed
    return batch
