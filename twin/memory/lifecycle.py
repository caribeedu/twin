"""Explicit memory lifecycle transitions.

Opinions change and decisions get replaced — the graph must say so
explicitly instead of letting stale memories compete with current ones.

- ``supersede``: the new memory replaces the old one.
- ``contradict``: two memories conflict and a human must arbitrate.
- ``merge``: several memories consolidate into one new memory.
- ``split``: one compound memory becomes several atomic memories.
- ``archive``: remove from retrieval while keeping history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .. import ids
from ..clock import now_iso
from .models import Evidence, MemoryItem, MemoryStatus, Relation
from .store.base import MemoryStore


@dataclass
class LifecycleResult:
    action: str
    subject_id: str
    object_id: str
    relation_id: str
    operation_id: Optional[str] = None
    extras: dict[str, Any] = field(default_factory=dict)


def _snapshot(mem: MemoryItem) -> dict[str, Any]:
    return mem.model_dump(mode="json")


def _record_op(store: MemoryStore, operation: str, inputs: list[str],
               output: Optional[str], before: dict, after: dict,
               actor: str = "user") -> Optional[str]:
    if not hasattr(store, "insert_operation"):
        return None
    from .models import MemoryOperation
    op = MemoryOperation(
        id=ids.operation_id(),
        operation=operation,
        actor=actor,
        at=now_iso(),
        inputs=inputs,
        output=output,
        before=before,
        after=after,
        undoable=True,
    )
    store.insert_operation(op)  # type: ignore[attr-defined]
    return op.id


def supersede(store: MemoryStore, new_id: str, old_id: str,
              actor: str = "user") -> LifecycleResult:
    """``new_id`` supersedes ``old_id``."""
    new_mem = store.get_memory(new_id)
    old_mem = store.get_memory(old_id)
    if new_mem is None or old_mem is None:
        raise ValueError("both memories must exist")
    if new_id == old_id:
        raise ValueError("a memory cannot supersede itself")
    before = {"old": _snapshot(old_mem), "new": _snapshot(new_mem)}
    cutoff = new_mem.valid_from or now_iso()[:10]
    relation_id = store.insert_relation(Relation(
        id=ids.relation_id(),
        subject_id=new_id, predicate="supersedes", object_id=old_id,
        memory_id=new_id, valid_from=cutoff,
    ))
    store.update_memory(
        old_id,
        status=MemoryStatus.deprecated.value,
        valid_until=cutoff,
        needs_review=False,
        review_reason=None,
    )
    op_id = _record_op(store, "supersede", [new_id, old_id], new_id, before, {
        "old_status": MemoryStatus.deprecated.value,
        "relation_id": relation_id,
    }, actor=actor)
    return LifecycleResult("supersede", new_id, old_id, relation_id, op_id)


def contradict(store: MemoryStore, memory_id: str, contradicted_id: str,
               actor: str = "user") -> LifecycleResult:
    """``memory_id`` contradicts ``contradicted_id`` — both go to review."""
    mem = store.get_memory(memory_id)
    other = store.get_memory(contradicted_id)
    if mem is None or other is None:
        raise ValueError("both memories must exist")
    if memory_id == contradicted_id:
        raise ValueError("a memory cannot contradict itself")
    before = {"a": _snapshot(mem), "b": _snapshot(other)}
    relation_id = store.insert_relation(Relation(
        id=ids.relation_id(),
        subject_id=memory_id, predicate="contradicts", object_id=contradicted_id,
        memory_id=memory_id,
    ))
    store.update_memory(
        contradicted_id,
        status=MemoryStatus.contradicted.value,
        needs_review=True,
        review_reason=f"contradicted by {memory_id}",
    )
    store.update_memory(
        memory_id,
        needs_review=True,
        review_reason=f"contradicts {contradicted_id} — confirm which holds",
    )
    op_id = _record_op(store, "contradict", [memory_id, contradicted_id], None, before, {
        "relation_id": relation_id,
    }, actor=actor)
    return LifecycleResult("contradict", memory_id, contradicted_id, relation_id, op_id)


def merge_memories(
    store: MemoryStore,
    memory_ids: list[str],
    *,
    title: Optional[str] = None,
    summary: Optional[str] = None,
    actor: str = "user",
    embedder=None,
) -> LifecycleResult:
    """Merge multiple memories into a new consolidated memory.

    Originals become ``merged`` with ``merged_into`` edges. Evidence and
    percept links are aggregated onto the new memory. Embeddings of sources
    are removed when the store supports it.
    """
    if len(memory_ids) < 2:
        raise ValueError("merge requires at least two memories")
    mems: list[MemoryItem] = []
    for mid in memory_ids:
        m = store.get_memory(mid)
        if m is None:
            raise ValueError(f"memory {mid} not found")
        if m.status.value in ("merged", "deleted", "split"):
            raise ValueError(f"memory {mid} cannot be merged (status={m.status.value})")
        mems.append(m)

    before = {m.id: _snapshot(m) for m in mems}
    primary = mems[0]
    entities: list[str] = []
    for m in mems:
        for e in m.entities:
            if e not in entities:
                entities.append(e)

    new = MemoryItem(
        id=ids.memory_id(),
        type=primary.type,
        title=title or primary.title,
        summary=summary or " ".join(dict.fromkeys(m.summary for m in mems)),
        domain=primary.domain,
        persona=primary.persona,
        sensitivity=max(mems, key=lambda m: (
            {"public": 0, "internal": 1, "private": 2, "restricted": 3}[m.sensitivity.value]
        )).sensitivity,
        confidence=max(m.confidence for m in mems),
        status=MemoryStatus.candidate if any(m.needs_review for m in mems) else MemoryStatus.confirmed,
        valid_from=min((m.valid_from for m in mems if m.valid_from), default=None),
        payload={
            **primary.payload,
            "merged_from": memory_ids,
        },
        needs_review=False,
        project_id=primary.project_id,
        entities=entities,
        impact=max(mems, key=lambda m: {"low": 0, "medium": 1, "high": 2}.get(m.impact, 1)).impact,
        canonical_claim=primary.canonical_claim,
        extractor_version=primary.extractor_version,
    )
    store.insert_memory(new)

    # aggregate evidence
    seen_quotes: set[str] = set()
    for m in mems:
        for ev in store.get_evidence(m.id):
            key = f"{ev.percept_id}:{ev.quote}"
            if key in seen_quotes:
                continue
            seen_quotes.add(key)
            store.insert_evidence(Evidence(
                id=ids.evidence_id(),
                memory_id=new.id,
                percept_id=ev.percept_id,
                quote=ev.quote,
                evidence_type=ev.evidence_type,
                directness=ev.directness,
                source_trust=ev.source_trust,
                independence_group=ev.independence_group,
                supports=ev.supports,
                span_start=ev.span_start,
                span_end=ev.span_end,
                artifact_id=ev.artifact_id,
            ))

    relation_ids: list[str] = []
    for m in mems:
        rid = store.insert_relation(Relation(
            id=ids.relation_id(),
            subject_id=m.id, predicate="merged_into", object_id=new.id,
            memory_id=new.id,
        ))
        relation_ids.append(rid)
        store.update_memory(
            m.id,
            status=MemoryStatus.merged.value,
            needs_review=False,
            review_reason=None,
        )
        # redirect relations that pointed at sources toward the merge result
        for rel in store.relations_for(m.id):
            if rel.predicate in ("merged_into", "split_into"):
                continue
            if rel.subject_id == m.id and rel.object_id != new.id:
                store.insert_relation(Relation(
                    id=ids.relation_id(),
                    subject_id=new.id, predicate=rel.predicate, object_id=rel.object_id,
                    memory_id=new.id, valid_from=rel.valid_from, valid_until=rel.valid_until,
                ))
            elif rel.object_id == m.id and rel.subject_id != new.id:
                store.insert_relation(Relation(
                    id=ids.relation_id(),
                    subject_id=rel.subject_id, predicate=rel.predicate, object_id=new.id,
                    memory_id=new.id, valid_from=rel.valid_from, valid_until=rel.valid_until,
                ))
        if hasattr(store, "delete_embedding"):
            store.delete_embedding(m.id)  # type: ignore[attr-defined]

    if embedder is not None:
        store.store_embedding(
            new.id, "memory", embedder.name,
            embedder.embed(f"{new.title}\n{new.summary}"),
        )

    op_id = _record_op(store, "merge_memories", memory_ids, new.id, before, {
        "merged_id": new.id, "relation_ids": relation_ids,
    }, actor=actor)
    return LifecycleResult(
        "merge", new.id, memory_ids[0], relation_ids[0] if relation_ids else "",
        op_id, extras={"merged_id": new.id, "sources": memory_ids},
    )


def split_memory(
    store: MemoryStore,
    memory_id: str,
    parts: list[dict[str, Any]],
    *,
    actor: str = "user",
    embedder=None,
) -> LifecycleResult:
    """Split a compound memory into atomic parts.

    Each part dict: ``{title, summary, type?, domain?, entities?}``.
    """
    if len(parts) < 2:
        raise ValueError("split requires at least two parts")
    mem = store.get_memory(memory_id)
    if mem is None:
        raise ValueError(f"memory {memory_id} not found")
    before = {memory_id: _snapshot(mem)}
    evidence = store.get_evidence(memory_id)
    child_ids: list[str] = []
    relation_ids: list[str] = []

    for part in parts:
        child = MemoryItem(
            id=ids.memory_id(),
            type=part.get("type", mem.type.value),  # type: ignore[arg-type]
            title=part["title"],
            summary=part.get("summary", part["title"]),
            domain=part.get("domain", mem.domain),
            persona=mem.persona,
            sensitivity=mem.sensitivity,
            confidence=mem.confidence,
            status=MemoryStatus.candidate,
            valid_from=mem.valid_from,
            valid_until=mem.valid_until,
            payload={**mem.payload, "split_from": memory_id},
            needs_review=True,
            review_reason="split from compound memory — confirm each part",
            project_id=mem.project_id,
            entities=part.get("entities", mem.entities),
            impact=mem.impact,
            extractor_version=mem.extractor_version,
        )
        store.insert_memory(child)
        child_ids.append(child.id)
        # share evidence (same percepts) — corroboration across parts
        for ev in evidence:
            store.insert_evidence(Evidence(
                id=ids.evidence_id(),
                memory_id=child.id,
                percept_id=ev.percept_id,
                quote=ev.quote,
                evidence_type=ev.evidence_type,
                directness=ev.directness,
                source_trust=ev.source_trust,
                independence_group=ev.independence_group,
                supports=ev.supports,
                artifact_id=ev.artifact_id,
            ))
        rid = store.insert_relation(Relation(
            id=ids.relation_id(),
            subject_id=memory_id, predicate="split_into", object_id=child.id,
            memory_id=child.id,
        ))
        relation_ids.append(rid)
        if embedder is not None:
            store.store_embedding(
                child.id, "memory", embedder.name,
                embedder.embed(f"{child.title}\n{child.summary}"),
            )

    store.update_memory(
        memory_id,
        status=MemoryStatus.split.value,
        needs_review=False,
        review_reason=None,
        payload={**mem.payload, "split_into": child_ids},
    )
    if hasattr(store, "delete_embedding"):
        store.delete_embedding(memory_id)  # type: ignore[attr-defined]

    op_id = _record_op(store, "split_memory", [memory_id], child_ids[0], before, {
        "child_ids": child_ids, "relation_ids": relation_ids,
    }, actor=actor)
    return LifecycleResult(
        "split", memory_id, child_ids[0], relation_ids[0] if relation_ids else "",
        op_id, extras={"source": memory_id, "children": child_ids},
    )


def archive_memory(store: MemoryStore, memory_id: str, *,
                   reason: str = "archived", actor: str = "user") -> LifecycleResult:
    mem = store.get_memory(memory_id)
    if mem is None:
        raise ValueError(f"memory {memory_id} not found")
    before = {memory_id: _snapshot(mem)}
    store.update_memory(
        memory_id,
        status=MemoryStatus.archived.value,
        needs_review=False,
        review_reason=reason,
    )
    if hasattr(store, "delete_embedding"):
        store.delete_embedding(memory_id)  # type: ignore[attr-defined]
    op_id = _record_op(store, "archive", [memory_id], None, before, {
        "status": MemoryStatus.archived.value,
    }, actor=actor)
    return LifecycleResult("archive", memory_id, memory_id, "", op_id)


def undo_operation(store: MemoryStore, operation_id: str) -> dict[str, Any]:
    """Best-effort undo for recorded structural operations."""
    if not hasattr(store, "get_operation"):
        raise ValueError("store does not support operations")
    op = store.get_operation(operation_id)  # type: ignore[attr-defined]
    if op is None:
        raise ValueError(f"operation {operation_id} not found")
    if not op.undoable or op.undone_at:
        raise ValueError(f"operation {operation_id} is not undoable")

    if op.operation == "archive":
        mid = op.inputs[0]
        snap = op.before.get(mid) or op.before.get("old") or {}
        if snap:
            store.update_memory(
                mid,
                status=snap.get("status", MemoryStatus.confirmed.value),
                needs_review=snap.get("needs_review", False),
                review_reason=snap.get("review_reason"),
            )
    elif op.operation == "merge_memories":
        merged_id = op.output
        if merged_id:
            store.update_memory(merged_id, status=MemoryStatus.deleted.value,
                                deleted_at=now_iso(), deletion_reason="merge_undone")
            if hasattr(store, "delete_embedding"):
                store.delete_embedding(merged_id)  # type: ignore[attr-defined]
        for mid, snap in op.before.items():
            store.update_memory(
                mid,
                status=snap.get("status", MemoryStatus.candidate.value),
                needs_review=snap.get("needs_review", False),
                review_reason=snap.get("review_reason"),
            )
    elif op.operation == "split_memory":
        source = op.inputs[0]
        snap = op.before.get(source, {})
        store.update_memory(
            source,
            status=snap.get("status", MemoryStatus.candidate.value),
            needs_review=snap.get("needs_review", False),
            review_reason=snap.get("review_reason"),
            payload=snap.get("payload", {}),
        )
        for cid in op.after.get("child_ids", []):
            store.update_memory(cid, status=MemoryStatus.deleted.value,
                                deleted_at=now_iso(), deletion_reason="split_undone")
            if hasattr(store, "delete_embedding"):
                store.delete_embedding(cid)  # type: ignore[attr-defined]
    elif op.operation == "supersede":
        old_id = op.inputs[1] if len(op.inputs) > 1 else None
        if old_id and old_id in op.before.get("old", {}) or True:
            old_snap = op.before.get("old", {})
            if old_id and old_snap:
                store.update_memory(
                    old_id,
                    status=old_snap.get("status", MemoryStatus.confirmed.value),
                    valid_until=old_snap.get("valid_until"),
                    needs_review=old_snap.get("needs_review", False),
                    review_reason=old_snap.get("review_reason"),
                )
    else:
        raise ValueError(f"undo not implemented for {op.operation}")

    if hasattr(store, "mark_operation_undone"):
        store.mark_operation_undone(operation_id)  # type: ignore[attr-defined]
    return {"undone": operation_id, "operation": op.operation}
