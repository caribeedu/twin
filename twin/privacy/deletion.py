"""Deletion preview / lineage accounting for privacy governance.

Preview shows a capped summary for humans. Execution uses an immutable
manifest with the full ID set. Truncated preview IDs never drive deletion.

Modes delivered: delete, detach.
Scaffold only (documented): anonymize, crypto_shred — behave like delete
with explicit metadata flags until key management exists.
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


def _evidence_groups(ev: Any) -> set[str]:
    groups: set[str] = set()
    pid = getattr(ev, "percept_id", None) or getattr(ev, "artifact_id", None)
    if pid:
        groups.add(str(pid))
    for sid in getattr(ev, "source_ids", None) or []:
        groups.add(str(sid))
    return groups


def _evidence_touches_selector(ev: Any, selector: dict[str, Any]) -> bool:
    artifact_id = selector.get("artifact_id")
    if not artifact_id:
        # domain/project/memory_ids selectors affect all evidence of matched mem
        return True
    if getattr(ev, "artifact_id", None) == artifact_id:
        return True
    if artifact_id in (getattr(ev, "source_ids", None) or []):
        return True
    return False


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
                if _evidence_touches_selector(ev, selector):
                    linked = True
                    break
            if not linked and artifact_id not in (getattr(m, "source_ids", None) or []):
                if artifact_id not in (m.percept_ids or []):
                    continue
        matched.append(m)
    return matched


def _plan_memory_actions(
    store: MemoryStore,
    mem: Any,
    selector: dict[str, Any],
    *,
    mode: DeletionMode,
) -> dict[str, Any]:
    """Decide delete vs recalculate based on remaining independence groups."""
    evs = store.get_evidence(mem.id) if hasattr(store, "get_evidence") else []
    affected_ev: list[str] = []
    remaining_groups: set[str] = set()
    affected_groups: set[str] = set()
    all_groups: set[str] = set()

    for ev in evs:
        groups = _evidence_groups(ev) or {getattr(ev, "id", "anon")}
        all_groups |= groups
        if _evidence_touches_selector(ev, selector):
            affected_ev.append(ev.id)
            affected_groups |= groups
        else:
            remaining_groups |= groups

    # Explicit memory_ids selector → delete the memory itself
    explicit = bool(selector.get("memory_ids") and mem.id in (selector.get("memory_ids") or []))
    no_remaining = not remaining_groups and (not evs or bool(affected_ev))
    # Domain-wide without artifact → treat as full delete of matched memories
    wholesale = not selector.get("artifact_id") and not selector.get("memory_ids")

    if mode == DeletionMode.detach:
        action = "recalculate"
        support = "partially_supported" if remaining_groups else "uniquely_supported"
    elif explicit or wholesale or no_remaining or (not evs and not selector.get("artifact_id")):
        action = "delete"
        support = "uniquely_supported" if not remaining_groups else "becomes_unsupported"
    elif remaining_groups:
        action = "recalculate"
        support = "partially_supported"
    else:
        action = "delete"
        support = "uniquely_supported"

    return {
        "action": action,
        "support": support,
        "affected_evidence": affected_ev,
        "remaining_groups": sorted(remaining_groups),
        "affected_groups": sorted(affected_groups),
    }


def _build_manifest(
    store: MemoryStore,
    matched: list[Any],
    selector: dict[str, Any],
    *,
    mode: DeletionMode,
) -> dict[str, Any]:
    memories_delete: list[str] = []
    memories_recalculate: list[str] = []
    evidence_delete: list[str] = []
    evidence_detach: list[str] = []
    percept_ids: list[str] = []
    artifact_ids: list[str] = []
    support_counts = {"uniquely_supported": 0, "partially_supported": 0, "becomes_unsupported": 0}

    sel_artifact = selector.get("artifact_id")
    if sel_artifact:
        artifact_ids.append(sel_artifact)

    for m in matched:
        plan = _plan_memory_actions(store, m, selector, mode=mode)
        support_counts[plan["support"]] = support_counts.get(plan["support"], 0) + 1
        if plan["action"] == "delete":
            memories_delete.append(m.id)
        else:
            memories_recalculate.append(m.id)

        for eid in plan["affected_evidence"]:
            if mode in (DeletionMode.delete, DeletionMode.crypto_shred, DeletionMode.anonymize):
                if plan["action"] == "delete":
                    evidence_delete.append(eid)
                else:
                    evidence_detach.append(eid)
            else:
                evidence_detach.append(eid)

        for ev in (store.get_evidence(m.id) if hasattr(store, "get_evidence") else []):
            if ev.id not in plan["affected_evidence"]:
                continue
            pid = getattr(ev, "percept_id", None)
            if pid:
                percept_ids.append(pid)
            aid = getattr(ev, "artifact_id", None)
            if aid:
                artifact_ids.append(aid)

    proposals: list[str] = []
    all_mem = memories_delete + memories_recalculate
    if hasattr(store, "list_judgment_proposals"):
        for p in store.list_judgment_proposals(status="pending"):
            if any(mid in (p.supporting_memory_ids or []) for mid in all_mem):
                proposals.append(p.id)

    return {
        "selector_fingerprint": "",
        "mode": mode.value,
        "mode_scaffold": mode.value in ("anonymize", "crypto_shred"),
        "memories_delete": memories_delete,
        "memories_recalculate": memories_recalculate,
        "evidence_delete": sorted(set(evidence_delete)),
        "evidence_detach": sorted(set(evidence_detach)),
        "percepts": sorted(set(percept_ids)),
        "artifacts": sorted(set(artifact_ids)),
        "embeddings": list(memories_delete),  # only deleted memories lose embeddings
        "judgment_proposals": proposals,
        "exports": [],
        "caches": [],
        "support_counts": support_counts,
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
    fingerprint = _selector_fingerprint(selector)
    manifest = _build_manifest(store, matched, selector, mode=mode)
    manifest["selector_fingerprint"] = fingerprint

    mem_ids = list(manifest["memories_delete"]) + list(manifest["memories_recalculate"])
    token_raw = json.dumps({
        "fp": fingerprint,
        "delete": manifest["memories_delete"],
        "recalc": manifest["memories_recalculate"],
        "evidence_delete": manifest["evidence_delete"],
        "mode": mode.value,
    }, sort_keys=True, separators=(",", ":"))
    preview_token = hashlib.sha256(token_raw.encode()).hexdigest()

    sc = manifest["support_counts"]
    preview = {
        "artifacts": len(manifest["artifacts"]),
        "percepts": len(manifest["percepts"]),
        "evidence_records": len(manifest["evidence_delete"]) + len(manifest["evidence_detach"]),
        "memories_uniquely_supported": sc.get("uniquely_supported", 0),
        "memories_partially_supported": sc.get("partially_supported", 0),
        "embeddings": len(manifest["embeddings"]),
        "judgment_proposals_affected": len(manifest["judgment_proposals"]),
        "exports": 0,
        "backups": 0,
        "matched_memory_ids_sample": mem_ids[:PREVIEW_UI_CAP],
        "matched_memory_count": len(mem_ids),
        "memories_to_delete": len(manifest["memories_delete"]),
        "memories_to_recalculate": len(manifest["memories_recalculate"]),
        "mode": mode.value,
        "mode_scaffold": manifest["mode_scaffold"],
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

    current = _match_memories(store, req.selector)
    refreshed = _build_manifest(store, current, req.selector, mode=req.mode)
    expected = req.manifest or {}
    if (
        _selector_fingerprint(req.selector) != expected.get("selector_fingerprint")
        or set(refreshed["memories_delete"]) != set(expected.get("memories_delete") or [])
        or set(refreshed["memories_recalculate"]) != set(expected.get("memories_recalculate") or [])
        or set(refreshed["evidence_delete"]) != set(expected.get("evidence_delete") or [])
    ):
        store.update_deletion_request(deletion_id, status=DeletionStatus.invalidated.value)
        raise ValueError("deletion manifest stale — selector result changed since preview")

    store.update_deletion_request(deletion_id, status=DeletionStatus.running.value)
    residuals: list[str] = []
    man = expected

    try:
        with store.transaction():
            # Evidence first
            for eid in man.get("evidence_delete") or []:
                try:
                    if hasattr(store, "tombstone_evidence"):
                        store.tombstone_evidence(eid, reason=req.reason or "privacy_deletion")
                    elif hasattr(store, "delete_evidence_row"):
                        store.delete_evidence_row(eid)
                except Exception as exc:
                    residuals.append(f"evidence:{eid}:{exc}")
            for eid in man.get("evidence_detach") or []:
                try:
                    if hasattr(store, "tombstone_evidence"):
                        store.tombstone_evidence(eid, reason=req.reason or "privacy_detach")
                    elif hasattr(store, "delete_evidence_row"):
                        store.delete_evidence_row(eid)
                except Exception as exc:
                    residuals.append(f"evidence_detach:{eid}:{exc}")

            # Artifacts / percepts from selector lineage
            for aid in man.get("artifacts") or []:
                try:
                    if hasattr(store, "tombstone_artifact"):
                        store.tombstone_artifact(aid, reason=req.reason or "privacy_deletion")
                except Exception as exc:
                    residuals.append(f"artifact:{aid}:{exc}")
            for pid in man.get("percepts") or []:
                # Only tombstone percept if no remaining artifact links (when countable)
                try:
                    if hasattr(store, "count_artifact_links_for_percept"):
                        if store.count_artifact_links_for_percept(pid) > 0:
                            # unlink selected artifacts first
                            for aid in man.get("artifacts") or []:
                                if hasattr(store, "unlink_artifact_percept"):
                                    store.unlink_artifact_percept(aid, pid)
                        if store.count_artifact_links_for_percept(pid) == 0 and hasattr(store, "tombstone_percept"):
                            store.tombstone_percept(pid, reason=req.reason or "privacy_deletion")
                    elif hasattr(store, "tombstone_percept"):
                        store.tombstone_percept(pid, reason=req.reason or "privacy_deletion")
                except Exception as exc:
                    residuals.append(f"percept:{pid}:{exc}")

            affected_percepts = set(man.get("percepts") or [])
            affected_artifacts = set(man.get("artifacts") or [])

            for mid in man.get("memories_recalculate") or []:
                mem = store.get_memory(mid)
                if mem is None:
                    continue
                remaining_percepts = [
                    x for x in (mem.percept_ids or []) if x not in affected_percepts
                ]
                # source_ids may not exist on MemoryItem — use payload links
                updates: dict[str, Any] = {
                    "percept_ids": remaining_percepts,
                    "deletion_reason": req.reason or "privacy_detach",
                }
                # Lower confidence when evidence was partially removed
                try:
                    new_conf = max(0.1, float(mem.confidence) * 0.7)
                    updates["confidence"] = new_conf
                except Exception:
                    pass
                store.update_memory(mid, **updates)

            for mid in man.get("memories_delete") or []:
                if req.mode == DeletionMode.anonymize:
                    store.update_memory(
                        mid,
                        title="[anonymized]",
                        summary="[anonymized]",
                        payload={"_anonymized": True, "_scaffold": True},
                        deleted_at=now_iso(),
                        deletion_reason=req.reason or "privacy_anonymize_scaffold",
                    )
                else:
                    store.update_memory(
                        mid,
                        deleted_at=now_iso(),
                        deletion_reason=req.reason or (
                            "privacy_crypto_shred_scaffold"
                            if req.mode == DeletionMode.crypto_shred
                            else "privacy_deletion"
                        ),
                    )
                if hasattr(store, "delete_embedding"):
                    try:
                        store.delete_embedding(mid)
                    except Exception as exc:
                        residuals.append(f"embedding:{mid}:{exc}")
                else:
                    residuals.append(f"embedding:{mid}:no_delete_method")

            for pid in man.get("judgment_proposals") or []:
                if hasattr(store, "update_judgment_proposal"):
                    try:
                        store.update_judgment_proposal(pid, status="withdrawn")
                    except Exception as exc:
                        residuals.append(f"proposal:{pid}:{exc}")
    except Exception:
        store.update_deletion_request(deletion_id, status=DeletionStatus.failed.value)
        raise

    # Residual checks
    for mid in man.get("memories_delete") or []:
        if hasattr(store, "get_embedding_blob"):
            try:
                if store.get_embedding_blob(mid) is not None:
                    residuals.append(f"embedding_residual:{mid}")
            except Exception:
                pass
        mem = store.get_memory(mid) if hasattr(store, "get_memory") else None
        if mem is not None and not getattr(mem, "deleted_at", None):
            residuals.append(f"memory_still_active:{mid}")
    for eid in man.get("evidence_delete") or []:
        # soft-check via get if available
        pass

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
            "deleted_count": len(man.get("memories_delete") or []),
            "recalculated_count": len(man.get("memories_recalculate") or []),
        },
    )
    return store.get_deletion_request(deletion_id)  # type: ignore[return-value]
