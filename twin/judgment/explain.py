"""Explain Judgment influence on packs / sessions."""

from __future__ import annotations

from typing import Any, Optional

from twin.store.store.base import MemoryStore


def explain_judgment_snapshot(
    store: MemoryStore, snapshot_id: str,
) -> dict[str, Any]:
    """Link a JudgmentSnapshot to applied revisions and influenced memories."""
    if not hasattr(store, "get_judgment_snapshot"):
        raise ValueError("judgment snapshots unavailable")
    snap = store.get_judgment_snapshot(snapshot_id)
    if snap is None:
        raise ValueError(f"snapshot {snapshot_id} not found")

    revisions: list[dict[str, Any]] = []
    for ref in snap.applied_revisions or []:
        if isinstance(ref, dict):
            rid = ref.get("revision_id")
            jid = ref.get("judgment_id")
            strength = ref.get("effective_strength")
        else:
            rid = ref.revision_id
            jid = ref.judgment_id
            strength = ref.effective_strength
        entry: dict[str, Any] = {
            "judgment_id": jid,
            "revision_id": rid,
            "effective_strength": strength,
        }
        if rid and hasattr(store, "get_judgment_revision"):
            rev = store.get_judgment_revision(rid)
            if rev is not None:
                entry["statement"] = getattr(rev, "statement", None) or getattr(
                    rev, "text", "",
                )
                entry["status"] = (
                    rev.status.value if hasattr(rev.status, "value") else str(rev.status)
                )
        revisions.append(entry)

    influenced: list[dict[str, Any]] = []
    for mem in store.list_memories(limit=500):
        payload = mem.payload or {}
        if payload.get("judgment_snapshot_id") == snapshot_id:
            influenced.append({
                "memory_id": mem.id,
                "status": mem.status.value if hasattr(mem.status, "value") else str(mem.status),
                "title": mem.title,
                "judgment_influenced": bool(payload.get("judgment_influenced")),
            })

    return {
        "snapshot_id": snap.id,
        "judgment_version_id": snap.judgment_version_id,
        "target_domain": snap.target_domain,
        "persona": snap.persona,
        "task_profile": snap.task_profile,
        "project_id": snap.project_id,
        "audience": snap.audience,
        "client": snap.client,
        "application_engine": snap.application_engine,
        "created_at": snap.created_at,
        "applied_revisions": revisions,
        "influenced_memories": influenced,
        "notes": [
            "Judgment in packs is advisory context under human-confirmed principles",
            "inference never widens persona/vault capabilities",
        ],
    }
