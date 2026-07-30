"""Provenance chain: Memory → Evidence → Percept → Artifact → source system."""

from __future__ import annotations

from typing import Any, Optional

from .. import ids
from ..clock import now_iso
from ..sensory.percept import Percept
from .models import Artifact, Evidence, MemoryItem
from .store.base import MemoryStore


def ensure_artifact_from_percept(store: MemoryStore, percept: Percept) -> Optional[str]:
    """Create or reuse an Artifact from a percept's content_refs / metadata."""
    if not hasattr(store, "insert_artifact"):
        return None
    refs = percept.content_refs or []
    meta = percept.metadata or {}
    external_id = (
        meta.get("commit") or meta.get("sha") or meta.get("external_id")
        or (refs[0] if refs else None)
    )
    uri = meta.get("uri") or meta.get("url") or (refs[0] if refs else None)
    kind = meta.get("artifact_kind") or {
        "git": "git_commit",
        "document": "document",
        "meeting": "meeting",
        "slack": "slack_message",
    }.get(percept.source_sensor, percept.percept_type or "artifact")

    content_hash = percept.content_hash
    # Reuse only within the same source_system — identical bytes from different
    # systems remain distinct artifacts (hash is not ownership).
    if hasattr(store, "find_artifact_by_hash") and content_hash:
        existing = store.find_artifact_by_hash(content_hash)  # type: ignore[attr-defined]
        if existing and existing.source_system == (percept.source_sensor or "local"):
            if hasattr(store, "link_artifact_percept"):
                store.link_artifact_percept(existing.id, percept.id)  # type: ignore[attr-defined]
            return existing.id

    art = Artifact(
        id=ids.artifact_id(),
        kind=kind,
        external_id=str(external_id) if external_id else None,
        source_system=percept.source_sensor or "local",
        uri=str(uri) if uri else None,
        content_hash=content_hash,
        occurred_at=percept.occurred_at,
        created_at=now_iso(),
        metadata={
            "percept_id": percept.id,
            "project_id": percept.project_id,
            **{k: v for k, v in meta.items() if k not in ("content",)},
        },
    )
    store.insert_artifact(art)  # type: ignore[attr-defined]
    if hasattr(store, "link_artifact_percept"):
        store.link_artifact_percept(art.id, percept.id)  # type: ignore[attr-defined]
    return art.id


def memory_provenance(store: MemoryStore, memory_id: str) -> dict[str, Any]:
    """Navigable lineage for 'why does twin believe this?'."""
    mem = store.get_memory(memory_id)
    if mem is None:
        raise ValueError(f"memory {memory_id} not found")

    evidence = store.get_evidence(memory_id)
    percepts: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    seen_art: set[str] = set()

    for ev in evidence:
        p = store.get_percept(ev.percept_id)
        p_dump: dict[str, Any] = {
            "id": ev.percept_id,
            "evidence_id": ev.id,
            "quote": ev.quote,
            "evidence_type": ev.evidence_type.value,
            "directness": ev.directness,
            "supports": ev.supports,
        }
        if p:
            p_dump.update({
                "source_sensor": p.source_sensor,
                "occurred_at": p.occurred_at,
                "source_trust": p.source_trust,
                "content_refs": p.content_refs,
                "artifact_id": ev.artifact_id,
            })
            art_id = ev.artifact_id
            if not art_id and hasattr(store, "find_artifact_by_hash") and p.content_hash:
                found = store.find_artifact_by_hash(p.content_hash)  # type: ignore[attr-defined]
                art_id = found.id if found else None
            if art_id and art_id not in seen_art and hasattr(store, "get_artifact"):
                art = store.get_artifact(art_id)  # type: ignore[attr-defined]
                if art:
                    artifacts.append(art.model_dump(mode="json"))
                    seen_art.add(art_id)
                    p_dump["artifact_id"] = art_id
        percepts.append(p_dump)

    relations = [
        r.model_dump(mode="json")
        for r in store.relations_for(memory_id)
        if r.predicate in (
            "supersedes", "contradicts", "merged_into", "split_into",
            "related_to", "supported_by",
        )
    ]

    return {
        "memory": mem.model_dump(mode="json"),
        "evidence": [e.model_dump(mode="json") for e in evidence],
        "percepts": percepts,
        "artifacts": artifacts,
        "relations": relations,
        "chain": "memory → evidence → percept → artifact → source_system",
    }


def attach_corroborating_evidence(
    store: MemoryStore,
    memory_id: str,
    percept_id: str,
    quote: str,
    *,
    independence_group: Optional[str] = None,
    source_trust: float = 0.8,
    bump_confidence: bool = True,
) -> Evidence:
    """Paraphrase/corroboration: same memory, additional evidence, capped confidence."""
    from twin.cognition.evidence_text import sanitize_evidence_quote

    mem = store.get_memory(memory_id)
    if mem is None:
        raise ValueError(f"memory {memory_id} not found")
    ev = Evidence(
        id=ids.evidence_id(),
        memory_id=memory_id,
        percept_id=percept_id,
        quote=sanitize_evidence_quote(quote),
        evidence_type="verbatim",  # type: ignore[arg-type]
        directness=0.9,
        source_trust=source_trust,
        independence_group=independence_group,
        supports=True,
    )
    store.insert_evidence(ev)
    if bump_confidence:
        # diminishing returns; independence groups share credit
        existing = store.get_evidence(memory_id)
        groups = {e.independence_group or e.percept_id for e in existing}
        # asymptotic toward 0.95
        n = len(groups)
        new_conf = min(0.95, mem.confidence + 0.08 / max(1, n - 1) if n > 1 else mem.confidence + 0.05)
        store.update_memory(memory_id, confidence=round(new_conf, 3))
    return ev
