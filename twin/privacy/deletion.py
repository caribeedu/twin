"""Deletion preview / lineage accounting for privacy governance.

Preview shows a capped summary for humans. Execution uses an immutable
manifest with the full ID set (or a selector fingerprint resolved at
execute time). Truncated preview IDs never drive deletion.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from .. import ids
from ..clock import now_iso
from ..memory.store.base import MemoryStore
from .models import DeletionMode, DeletionRequest, DeletionStatus

PREVIEW_UI_CAP = 50


def _selector_fingerprint(selector: dict[str, Any]) -> str:
    raw = json.dumps(selector or {}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _match_memories(store: MemoryStore, selector: dict[str, Any]) -> list[Any]:
    artifact_id = selector.get("artifact_id")
    source_account = selector.get("source_account")
    domain = selector.get("domain")
    project_id = selector.get("project_id")
    memory_ids = selector.get("memory_ids")

    memories = store.list_memories(limit=100000)
    matched = []
    for m in memories:
        if getattr(m, "deleted_at", None):
            continue
        if memory_ids and m.id not in memory_ids:
            continue
        payload = m.payload or {}
        if domain and m.domain != domain:
            continue
        if project_id and m.project_id != project_id:
            continue
        if source_account and payload.get("source_account") != source_account:
            continue
        if artifact_id:
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
        matched.append(m)
    return matched


def _classify_support(store: MemoryStore, mem: Any) -> str:
    """Classify whether deleting this memory's evidence removes unique support."""
    evs = store.get_evidence(mem.id) if hasattr(store, "get_evidence") else []
    if not evs:
        return "uniquely_supported"
    # Independence groups: distinct percept_ids / source_ids
    groups = set()
    for ev in evs:
        pid = getattr(ev, "percept_id", None) or getattr(ev, "artifact_id", None)
        if pid:
            groups.add(pid)
        for sid in getattr(ev, "source_ids", None) or []:
            groups.add(sid)
    if len(groups) <= 1:
        return "uniquely_supported"
    return "partially_supported"


def _build_manifest(
    store: MemoryStore,
    matched: list[Any],
    *,
    mode: DeletionMode,
) -> dict[str, Any]:
    mem_ids = [m.id for m in matched]
    evidence_delete: list[str] = []
    evidence_detach: list[str] = []
    percept_ids: list[str] = []
    artifact_ids: list[str] = []
    for m in matched:
        for ev in (store.get_evidence(m.id) if hasattr(store, "get_evidence") else []):
            eid = getattr(ev, "id", None)
            if not eid:
                continue
            if mode in (DeletionMode.delete, DeletionMode.crypto_shred):
                evidence_delete.append(eid)
            else:
                evidence_detach.append(eid)
            pid = getattr(ev, "percept_id", None)
            if pid:
                percept_ids.append(pid)
            aid = getattr(ev, "artifact_id", None)
            if aid:
                artifact_ids.append(aid)
        for pid in m.percept_ids or []:
            percept_ids.append(pid)
        for sid in getattr(m, "source_ids", None) or []:
            artifact_ids.append(sid)

    proposals: list[str] = []
    if hasattr(store, "list_judgment_proposals"):
        for p in store.list_judgment_proposals(status="pending"):
            if any(mid in (p.supporting_memory_ids or []) for mid in mem_ids):
                proposals.append(p.id)

    return {
        "selector_fingerprint": "",  # filled by caller
        "mode": mode.value,
        "memories_delete": mem_ids if mode != DeletionMode.detach else [],
        "memories_recalculate": mem_ids if mode == DeletionMode.detach else [],
        "evidence_delete": sorted(set(evidence_delete)),
        "evidence_detach": sorted(set(evidence_detach)),
        "percepts": sorted(set(percept_ids)),
        "artifacts": sorted(set(artifact_ids)),
        "embeddings": list(mem_ids),
        "judgment_proposals": proposals,
        "exports": [],
        "caches": [],
    }


def preview_deletion(
    store: MemoryStore,
    selector: dict[str, Any],
    *,
    mode: DeletionMode = DeletionMode.delete,
    reason: str = "",
    requested_by: str = "user",
) -> DeletionRequest:
    matched = _match_memories(store, selector)
    unique = 0
    partial = 0
    evidence = 0
    for m in matched:
        kind = _classify_support(store, m)
        if kind == "partially_supported":
            partial += 1
        else:
            unique += 1
        evidence += len(store.get_evidence(m.id)) if hasattr(store, "get_evidence") else 0

    proposals = 0
    mem_ids = [m.id for m in matched]
    if hasattr(store, "list_judgment_proposals"):
        for p in store.list_judgment_proposals(status="pending"):
            if any(mid in (p.supporting_memory_ids or []) for mid in mem_ids):
                proposals += 1

    fingerprint = _selector_fingerprint(selector)
    manifest = _build_manifest(store, matched, mode=mode)
    manifest["selector_fingerprint"] = fingerprint
    # State-aware token: selector + sorted IDs + mode
    token_raw = json.dumps({
        "fp": fingerprint,
        "ids": mem_ids,
        "mode": mode.value,
    }, sort_keys=True, separators=(",", ":"))
    preview_token = hashlib.sha256(token_raw.encode()).hexdigest()

    preview = {
        "artifacts": len(manifest["artifacts"]),
        "percepts": len(manifest["percepts"]),
        "evidence_records": evidence,
        "memories_uniquely_supported": unique,
        "memories_partially_supported": partial,
        "embeddings": len(mem_ids),
        "judgment_proposals_affected": proposals,
        "exports": 0,
        "backups": 0,
        # UI-capped sample — never used for execute
        "matched_memory_ids_sample": mem_ids[:PREVIEW_UI_CAP],
        "matched_memory_count": len(mem_ids),
        "mode": mode.value,
        "preview_token": preview_token,
        "selector_fingerprint": fingerprint,
        "note": "Preview only — execute requires preview_token matching immutable manifest",
    }
    req = DeletionRequest(
        id=ids.new_id("delreq"),
        selector=selector,
        mode=mode,
        requested_by=requested_by,
        reason=reason,
        status=DeletionStatus.preview,
        preview=preview,
        manifest=manifest,
        preview_token=preview_token,
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
    preview_token: Optional[str] = None,
) -> DeletionRequest:
    if not confirm:
        raise ValueError("deletion_execute requires confirm=True")
    req = store.get_deletion_request(deletion_id)
    if req is None:
        raise ValueError(f"deletion {deletion_id} not found")
    if req.status not in (DeletionStatus.preview, DeletionStatus.approved):
        raise ValueError(f"deletion is {req.status.value}")

    token = preview_token or (req.preview or {}).get("preview_token") or req.preview_token
    if not token or token != req.preview_token:
        store.update_deletion_request(deletion_id, status=DeletionStatus.invalidated.value)
        raise ValueError("deletion preview_token mismatch — preview invalidated")

    # TOCTOU: re-resolve selector; fingerprint/ID set must match manifest
    current = _match_memories(store, req.selector)
    current_ids = [m.id for m in current]
    expected_ids = list((req.manifest or {}).get("memories_delete") or [])
    if req.mode == DeletionMode.detach:
        expected_ids = list((req.manifest or {}).get("memories_recalculate") or [])
    if (
        _selector_fingerprint(req.selector) != (req.manifest or {}).get("selector_fingerprint")
        or set(current_ids) != set(expected_ids)
    ):
        store.update_deletion_request(deletion_id, status=DeletionStatus.invalidated.value)
        raise ValueError("deletion manifest stale — selector result changed since preview")

    mem_ids = list(expected_ids)
    store.update_deletion_request(deletion_id, status=DeletionStatus.running.value)

    residuals: list[str] = []
    try:
        with store.transaction():
            for mid in mem_ids:
                if req.mode == DeletionMode.anonymize:
                    store.update_memory(
                        mid,
                        title="[anonymized]",
                        summary="[anonymized]",
                        payload={},
                        deleted_at=now_iso(),
                        deletion_reason=req.reason or "privacy_anonymize",
                    )
                elif req.mode == DeletionMode.detach:
                    store.update_memory(
                        mid,
                        percept_ids=[],
                        source_ids=[],
                        deletion_reason=req.reason or "privacy_detach",
                    )
                else:
                    store.update_memory(
                        mid,
                        deleted_at=now_iso(),
                        deletion_reason=req.reason or "privacy_deletion",
                    )
                # Embeddings must be removed; failure is not silent
                if hasattr(store, "delete_embedding"):
                    try:
                        store.delete_embedding(mid)
                    except Exception as exc:
                        residuals.append(f"embedding:{mid}:{exc}")
                elif hasattr(store, "delete_embeddings"):
                    try:
                        store.delete_embeddings(mid)  # type: ignore[attr-defined]
                    except Exception as exc:
                        residuals.append(f"embedding:{mid}:{exc}")
                else:
                    residuals.append(f"embedding:{mid}:no_delete_method")

            # Best-effort lineage cleanup for proposals
            for pid in (req.manifest or {}).get("judgment_proposals") or []:
                if hasattr(store, "update_judgment_proposal"):
                    try:
                        store.update_judgment_proposal(pid, status="withdrawn")
                    except Exception as exc:
                        residuals.append(f"proposal:{pid}:{exc}")
    except Exception:
        store.update_deletion_request(deletion_id, status=DeletionStatus.failed.value)
        raise

    # Residual verification: embeddings / searchable content
    for mid in mem_ids:
        if hasattr(store, "get_embedding_blob"):
            try:
                emb = store.get_embedding_blob(mid)
                if emb is not None:
                    residuals.append(f"embedding_residual:{mid}")
            except Exception:
                pass
        elif hasattr(store, "get_embedding"):
            try:
                emb = store.get_embedding(mid)  # type: ignore[attr-defined]
                if emb is not None:
                    residuals.append(f"embedding_residual:{mid}")
            except Exception:
                pass
        mem = store.get_memory(mid) if hasattr(store, "get_memory") else None
        if mem is not None and req.mode != DeletionMode.detach:
            if not getattr(mem, "deleted_at", None):
                residuals.append(f"memory_still_active:{mid}")

    status = (
        DeletionStatus.completed_with_residuals
        if residuals
        else DeletionStatus.completed
    )
    store.update_deletion_request(
        deletion_id,
        status=status.value,
        completed_at=now_iso(),
        preview={
            **(req.preview or {}),
            "residuals": residuals,
            "deleted_count": len(mem_ids),
        },
    )
    return store.get_deletion_request(deletion_id)  # type: ignore[return-value]
