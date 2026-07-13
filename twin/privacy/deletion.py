"""Deletion preview / lineage accounting for privacy governance."""

from __future__ import annotations

from typing import Any, Optional

from .. import ids
from ..clock import now_iso
from ..memory.store.base import MemoryStore
from .models import DeletionMode, DeletionRequest, DeletionStatus


def preview_deletion(
    store: MemoryStore,
    selector: dict[str, Any],
    *,
    mode: DeletionMode = DeletionMode.delete,
    reason: str = "",
    requested_by: str = "user",
) -> DeletionRequest:
    artifact_id = selector.get("artifact_id")
    source_account = selector.get("source_account")
    domain = selector.get("domain")
    project_id = selector.get("project_id")

    artifacts = 0
    percepts = 0
    evidence = 0
    memories_unique = 0
    memories_partial = 0
    embeddings = 0
    proposals = 0

    memories = store.list_memories(limit=100000)
    matched_mem_ids: list[str] = []
    for m in memories:
        payload = m.payload or {}
        if domain and m.domain != domain:
            continue
        if project_id and m.project_id != project_id:
            continue
        if source_account and payload.get("source_account") != source_account:
            continue
        if artifact_id:
            # check evidence/percept linkage when available
            evs = store.get_evidence(m.id) if hasattr(store, "get_evidence") else []
            linked = False
            for ev in evs:
                if getattr(ev, "artifact_id", None) == artifact_id:
                    linked = True
                    break
                if artifact_id in (getattr(ev, "source_ids", None) or []):
                    linked = True
                    break
            if not linked and artifact_id not in (m.source_ids or []):
                continue
        matched_mem_ids.append(m.id)
        memories_unique += 1
        evidence += len(store.get_evidence(m.id)) if hasattr(store, "get_evidence") else 0

    if hasattr(store, "list_judgment_proposals"):
        for p in store.list_judgment_proposals(status="pending"):
            if any(mid in (p.supporting_memory_ids or []) for mid in matched_mem_ids):
                proposals += 1

    # embeddings approx = matched memories
    embeddings = len(matched_mem_ids)

    preview = {
        "artifacts": artifacts,
        "percepts": percepts,
        "evidence_records": evidence,
        "memories_uniquely_supported": memories_unique,
        "memories_partially_supported": memories_partial,
        "embeddings": embeddings,
        "judgment_proposals_affected": proposals,
        "exports": 0,
        "backups": 0,
        "matched_memory_ids": matched_mem_ids[:50],  # capped preview ids
        "matched_memory_count": len(matched_mem_ids),
        "mode": mode.value,
        "note": "Preview only — no content values included",
    }
    req = DeletionRequest(
        id=ids.new_id("delreq"),
        selector=selector,
        mode=mode,
        requested_by=requested_by,
        reason=reason,
        status=DeletionStatus.preview,
        preview=preview,
        created_at=now_iso(),
    )
    if hasattr(store, "insert_deletion_request"):
        store.insert_deletion_request(req)
    return req


def execute_deletion(
    store: MemoryStore,
    deletion_id: str,
    *,
    confirm: bool = False,
) -> DeletionRequest:
    if not confirm:
        raise ValueError("deletion_execute requires confirm=True")
    req = store.get_deletion_request(deletion_id)
    if req is None:
        raise ValueError(f"deletion {deletion_id} not found")
    if req.status not in (DeletionStatus.preview, DeletionStatus.approved):
        raise ValueError(f"deletion is {req.status.value}")

    store.update_deletion_request(deletion_id, status=DeletionStatus.running.value)
    mem_ids = list((req.preview or {}).get("matched_memory_ids") or [])
    if (req.preview or {}).get("matched_memory_count", 0) > len(mem_ids):
        refreshed = preview_deletion(store, req.selector, mode=req.mode)
        mem_ids = list((refreshed.preview or {}).get("matched_memory_ids") or [])

    for mid in mem_ids:
        try:
            store.update_memory(mid, deleted_at=now_iso(), deletion_reason=req.reason or "privacy_deletion")
            if hasattr(store, "delete_embeddings"):
                try:
                    store.delete_embeddings(mid)  # type: ignore[attr-defined]
                except Exception:
                    pass
        except Exception:
            store.update_deletion_request(deletion_id, status=DeletionStatus.failed.value)
            raise

    store.update_deletion_request(
        deletion_id,
        status=DeletionStatus.completed.value,
        completed_at=now_iso(),
    )
    return store.get_deletion_request(deletion_id)  # type: ignore[return-value]
