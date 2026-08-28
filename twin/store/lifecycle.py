"""Explicit memory lifecycle transitions — atomic, auditable, reversible.

Structural ops (merge/split/supersede/contradict/archive/undo) run inside
``store.transaction()`` and record inverse payloads sufficient for full undo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from .. import ids
from ..clock import now_iso
from .models import Evidence, StoreClaim, ClaimStatus, Relation
from .store.base import TwinStore


@dataclass
class LifecycleResult:
    action: str
    subject_id: str
    object_id: str
    relation_id: str
    operation_id: Optional[str] = None
    extras: dict[str, Any] = field(default_factory=dict)


def _snapshot(mem: StoreClaim) -> dict[str, Any]:
    return mem.model_dump(mode="json")


def _restore_memory_fields(store: TwinStore, claim_id: str, snap: dict[str, Any]) -> None:
    store.update_claim(
        claim_id,
        title=snap.get("title"),
        summary=snap.get("summary"),
        domain=snap.get("domain"),
        persona=snap.get("persona"),
        sensitivity=snap.get("sensitivity"),
        confidence=snap.get("confidence"),
        status=snap.get("status"),
        valid_from=snap.get("valid_from"),
        valid_until=snap.get("valid_until"),
        needs_review=snap.get("needs_review", False),
        review_reason=snap.get("review_reason"),
        payload=snap.get("payload") or {},
        project_id=snap.get("project_id"),
        review_priority=snap.get("review_priority", 0),
        quality_score=snap.get("quality_score", 0),
        quality_flags=snap.get("quality_flags") or [],
        impact=snap.get("impact", "medium"),
        reviewed_at=snap.get("reviewed_at"),
        review_batch_id=snap.get("review_batch_id"),
        canonical_claim=snap.get("canonical_claim"),
        extractor_version=snap.get("extractor_version"),
        last_reconciled_at=snap.get("last_reconciled_at"),
        deleted_at=snap.get("deleted_at"),
        deletion_reason=snap.get("deletion_reason"),
    )


def _capture_embedding(store: TwinStore, claim_id: str) -> Optional[dict[str, Any]]:
    if not hasattr(store, "get_embedding_blob"):
        return None
    got = store.get_embedding_blob(claim_id)  # type: ignore[attr-defined]
    if not got:
        return None
    model, blob = got
    return {"ref_id": claim_id, "model": model, "blob": blob.hex()}


def _restore_embedding(store: TwinStore, payload: Optional[dict[str, Any]]) -> None:
    if not payload or not hasattr(store, "restore_embedding_blob"):
        return
    store.restore_embedding_blob(  # type: ignore[attr-defined]
        payload["ref_id"], "claim", payload["model"], bytes.fromhex(payload["blob"]),
    )


def _record_op(store: TwinStore, operation: str, inputs: list[str],
               output: Optional[str], before: dict, after: dict,
               actor: str = "user") -> Optional[str]:
    if not hasattr(store, "insert_operation"):
        return None
    from .models import ClaimOperation
    op = ClaimOperation(
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


def supersede(store: TwinStore, new_id: str, old_id: str,
              actor: str = "user") -> LifecycleResult:
    new_mem = store.get_claim(new_id)
    old_mem = store.get_claim(old_id)
    if new_mem is None or old_mem is None:
        raise ValueError("both memories must exist")
    if new_id == old_id:
        raise ValueError("a memory cannot supersede itself")

    with store.transaction():
        before = {
            "old": _snapshot(old_mem),
            "new": _snapshot(new_mem),
            "deleted_embedding_refs": [],
        }
        emb = _capture_embedding(store, old_id)
        if emb:
            before["deleted_embedding_refs"] = [emb]
        cutoff = new_mem.valid_from or now_iso()[:10]
        relation_id = store.insert_relation(Relation(
            id=ids.relation_id(),
            subject_id=new_id, predicate="supersedes", object_id=old_id,
            claim_id=new_id, valid_from=cutoff,
        ))
        store.update_claim(
            old_id,
            status=ClaimStatus.deprecated.value,
            valid_until=cutoff,
            needs_review=False,
            review_reason=None,
        )
        after = {
            "created_relation_ids": [relation_id],
            "created_claim_ids": [],
            "created_evidence_ids": [],
            "old_status": ClaimStatus.deprecated.value,
        }
        op_id = _record_op(store, "supersede", [new_id, old_id], new_id, before, after, actor=actor)
    return LifecycleResult("supersede", new_id, old_id, relation_id, op_id)


def contradict(store: TwinStore, claim_id: str, contradicted_id: str,
               actor: str = "user") -> LifecycleResult:
    mem = store.get_claim(claim_id)
    other = store.get_claim(contradicted_id)
    if mem is None or other is None:
        raise ValueError("both memories must exist")
    if claim_id == contradicted_id:
        raise ValueError("a memory cannot contradict itself")

    with store.transaction():
        before = {"a": _snapshot(mem), "b": _snapshot(other)}
        relation_id = store.insert_relation(Relation(
            id=ids.relation_id(),
            subject_id=claim_id, predicate="contradicts", object_id=contradicted_id,
            claim_id=claim_id,
        ))
        store.update_claim(
            contradicted_id,
            status=ClaimStatus.contradicted.value,
            needs_review=True,
            review_reason=f"contradicted by {claim_id}",
        )
        store.update_claim(
            claim_id,
            needs_review=True,
            review_reason=f"contradicts {contradicted_id} — confirm which holds",
        )
        after = {"created_relation_ids": [relation_id]}
        op_id = _record_op(store, "contradict", [claim_id, contradicted_id], None,
                           before, after, actor=actor)
    return LifecycleResult("contradict", claim_id, contradicted_id, relation_id, op_id)


_OUTPUT_UNSET = object()


def _assert_merge_compatible(
    mems: list[StoreClaim],
    *,
    confirm_cross_scope_merge: bool = False,
) -> None:
    domains = {m.domain for m in mems}
    types = {m.type.value for m in mems}
    personas = {m.persona for m in mems}
    projects = {m.project_id for m in mems}
    if len(domains) > 1 and not confirm_cross_scope_merge:
        raise ValueError(f"merge blocked: mixed domains {sorted(domains)}; "
                         "pass confirm_cross_scope_merge=True only after explicit review")
    if len(domains) > 1:
        # even with override, never silently merge personal/life domains into work
        sensitive = {"relationship", "family", "health", "emotional", "finance"}
        if domains & sensitive and domains - sensitive:
            raise ValueError("cross-domain merge involving life domains is forbidden")
    if len(types) > 1 and not confirm_cross_scope_merge:
        raise ValueError(f"merge blocked: mixed types {sorted(types)}")
    if len(personas) > 1 and not confirm_cross_scope_merge:
        raise ValueError(f"merge blocked: mixed personas {sorted(personas)}")
    # projects: allow if all None or all same; mixed project+None needs override
    nontrivial = {p for p in projects if p}
    if len(nontrivial) > 1:
        raise ValueError(f"merge blocked: mixed projects {sorted(nontrivial)}")
    if nontrivial and None in projects and not confirm_cross_scope_merge:
        raise ValueError("merge blocked: some memories lack project_id")


def _resolve_merge_semantics(
    mems: list[StoreClaim],
    *,
    output_type: Optional[str] = None,
    output_domain: Optional[str] = None,
    output_persona: Optional[str] = None,
    output_project_id: Any = _OUTPUT_UNSET,
    output_canonical_claim: Any = _OUTPUT_UNSET,
) -> dict[str, Any]:
    """Pick result semantics; mixed inputs require explicit outputs."""
    primary = mems[0]
    types = {m.type.value for m in mems}
    domains = {m.domain for m in mems}
    personas = {m.persona for m in mems}
    projects = {m.project_id for m in mems}
    def _claim_key(claim: Any) -> str:
        if claim is None:
            return ""
        if hasattr(claim, "model_dump"):
            return json.dumps(claim.model_dump(mode="json"), sort_keys=True)
        return str(claim)

    claims = {_claim_key(m.canonical_claim) for m in mems}

    if len(types) > 1 and output_type is None:
        raise ValueError(
            f"mixed types {sorted(types)} require explicit output_type "
            "(confirm_cross_scope_merge only authorizes the attempt)"
        )
    if len(domains) > 1 and output_domain is None:
        raise ValueError(
            f"mixed domains {sorted(domains)} require explicit output_domain"
        )
    if len(personas) > 1 and output_persona is None:
        raise ValueError(
            f"mixed personas {sorted(personas)} require explicit output_persona"
        )
    if len(projects) > 1 and output_project_id is _OUTPUT_UNSET:
        raise ValueError(
            f"mixed project_id values require explicit output_project_id"
        )
    if len(claims) > 1 and output_canonical_claim is _OUTPUT_UNSET:
        raise ValueError(
            "mixed canonical_claim values require explicit output_canonical_claim"
        )

    resolved_type = output_type if output_type is not None else primary.type
    resolved_domain = output_domain if output_domain is not None else primary.domain
    resolved_persona = output_persona if output_persona is not None else primary.persona
    if output_project_id is _OUTPUT_UNSET:
        resolved_project = primary.project_id
    else:
        resolved_project = output_project_id
    if output_canonical_claim is _OUTPUT_UNSET:
        resolved_claim = primary.canonical_claim
    else:
        resolved_claim = output_canonical_claim

    return {
        "type": resolved_type,
        "domain": resolved_domain,
        "persona": resolved_persona,
        "project_id": resolved_project,
        "canonical_claim": resolved_claim,
    }


def merge_claims(
    store: TwinStore,
    claim_ids: list[str],
    *,
    title: Optional[str] = None,
    summary: Optional[str] = None,
    actor: str = "user",
    embedder=None,
    confirm_cross_scope_merge: bool = False,
    human_confirmed_synthesis: bool = False,
    output_type: Optional[str] = None,
    output_domain: Optional[str] = None,
    output_persona: Optional[str] = None,
    output_project_id: Any = _OUTPUT_UNSET,
    output_canonical_claim: Any = _OUTPUT_UNSET,
) -> LifecycleResult:
    if len(claim_ids) < 2:
        raise ValueError("merge requires at least two memories")
    mems: list[StoreClaim] = []
    for mid in claim_ids:
        m = store.get_claim(mid)
        if m is None:
            raise ValueError(f"memory {mid} not found")
        if m.status.value in ("merged", "deleted", "split"):
            raise ValueError(f"memory {mid} cannot be merged (status={m.status.value})")
        mems.append(m)
    _assert_merge_compatible(mems, confirm_cross_scope_merge=confirm_cross_scope_merge)
    semantics = _resolve_merge_semantics(
        mems,
        output_type=output_type,
        output_domain=output_domain,
        output_persona=output_persona,
        output_project_id=output_project_id,
        output_canonical_claim=output_canonical_claim,
    )

    with store.transaction():
        before: dict[str, Any] = {
            "claims": {m.id: _snapshot(m) for m in mems},
            "embeddings": {},
        }
        for m in mems:
            emb = _capture_embedding(store, m.id)
            if emb:
                before["embeddings"][m.id] = emb

        primary = mems[0]
        entities: list[str] = []
        for m in mems:
            for e in m.entities:
                if e not in entities:
                    entities.append(e)

        status = (
            ClaimStatus.confirmed
            if human_confirmed_synthesis and title and summary
            else ClaimStatus.candidate
        )
        new = StoreClaim(
            id=ids.claim_id(),
            type=semantics["type"],
            title=title or primary.title,
            summary=summary or " ".join(dict.fromkeys(m.summary for m in mems)),
            domain=semantics["domain"],
            persona=semantics["persona"],
            sensitivity=max(mems, key=lambda m: (
                {"public": 0, "internal": 1, "private": 2, "restricted": 3}[m.sensitivity.value]
            )).sensitivity,
            confidence=max(m.confidence for m in mems),
            status=status,
            valid_from=min((m.valid_from for m in mems if m.valid_from), default=None),
            payload={**primary.payload, "merged_from": claim_ids},
            needs_review=status == ClaimStatus.candidate,
            review_reason="merged synthesis — confirm" if status == ClaimStatus.candidate else None,
            project_id=semantics["project_id"],
            entities=entities,
            impact=max(mems, key=lambda m: {"low": 0, "medium": 1, "high": 2}.get(m.impact, 1)).impact,
            canonical_claim=semantics["canonical_claim"],
            extractor_version=primary.extractor_version,
        )
        store.insert_claim(new)

        created_evidence: list[str] = []
        seen_groups: set[str] = set()
        for m in mems:
            for ev in store.get_evidence(m.id):
                group = ev.independence_group or ev.artifact_id or ev.percept_id
                key = f"{group}:{ev.quote}"
                if key in seen_groups:
                    continue
                seen_groups.add(key)
                eid = ids.evidence_id()
                store.insert_evidence(Evidence(
                    id=eid, claim_id=new.id, percept_id=ev.percept_id, quote=ev.quote,
                    evidence_type=ev.evidence_type, directness=ev.directness,
                    source_trust=ev.source_trust, independence_group=group,
                    supports=ev.supports, span_start=ev.span_start, span_end=ev.span_end,
                    artifact_id=ev.artifact_id,
                ))
                created_evidence.append(eid)

        created_relations: list[str] = []
        redirected: list[str] = []
        for m in mems:
            rid = store.insert_relation(Relation(
                id=ids.relation_id(),
                subject_id=m.id, predicate="merged_into", object_id=new.id,
                claim_id=new.id,
            ))
            created_relations.append(rid)
            store.update_claim(
                m.id, status=ClaimStatus.merged.value,
                needs_review=False, review_reason=None,
            )
            for rel in store.relations_for(m.id):
                if rel.predicate in ("merged_into", "split_into"):
                    continue
                if rel.subject_id == m.id and rel.object_id != new.id:
                    nr = ids.relation_id()
                    store.insert_relation(Relation(
                        id=nr, subject_id=new.id, predicate=rel.predicate,
                        object_id=rel.object_id, claim_id=new.id,
                        valid_from=rel.valid_from, valid_until=rel.valid_until,
                    ))
                    redirected.append(nr)
                elif rel.object_id == m.id and rel.subject_id != new.id:
                    nr = ids.relation_id()
                    store.insert_relation(Relation(
                        id=nr, subject_id=rel.subject_id, predicate=rel.predicate,
                        object_id=new.id, claim_id=new.id,
                        valid_from=rel.valid_from, valid_until=rel.valid_until,
                    ))
                    redirected.append(nr)
            if hasattr(store, "delete_embedding"):
                store.delete_embedding(m.id)  # type: ignore[attr-defined]

        if embedder is not None:
            store.store_embedding(
                new.id, "claim", embedder.name,
                embedder.embed(f"{new.title}\n{new.summary}"),
            )

        after = {
            "created_claim_ids": [new.id],
            "created_evidence_ids": created_evidence,
            "created_relation_ids": created_relations + redirected,
            "deleted_embedding_refs": list(before["embeddings"].keys()),
        }
        op_id = _record_op(store, "merge_memories", claim_ids, new.id, before, after, actor=actor)

    return LifecycleResult(
        "merge", new.id, claim_ids[0],
        created_relations[0] if created_relations else "",
        op_id, extras={"merged_id": new.id, "sources": claim_ids},
    )


def split_claim(
    store: TwinStore,
    claim_id: str,
    parts: list[dict[str, Any]],
    *,
    actor: str = "user",
    embedder=None,
) -> LifecycleResult:
    """Split a compound claim. Each part may declare ``evidence_ids`` it owns.

    Without an evidence map, children stay candidates with
    ``evidence_mapping_required`` and only contextual (non-supporting) copies.
    """
    if len(parts) < 2:
        raise ValueError("split requires at least two parts")
    mem = store.get_claim(claim_id)
    if mem is None:
        raise ValueError(f"memory {claim_id} not found")

    with store.transaction():
        before = {
            "claims": {claim_id: _snapshot(mem)},
            "embeddings": {},
        }
        emb = _capture_embedding(store, claim_id)
        if emb:
            before["embeddings"][claim_id] = emb

        evidence = store.get_evidence(claim_id)
        by_id = {e.id: e for e in evidence}
        child_ids: list[str] = []
        created_relations: list[str] = []
        created_evidence: list[str] = []

        for part in parts:
            mapped_ids = part.get("evidence_ids") or []
            has_map = bool(mapped_ids)
            child = StoreClaim(
                id=ids.claim_id(),
                type=part.get("type", mem.type.value),  # type: ignore[arg-type]
                title=part["title"],
                summary=part.get("summary", part["title"]),
                domain=part.get("domain", mem.domain),
                persona=mem.persona,
                sensitivity=mem.sensitivity,
                confidence=mem.confidence if has_map else min(mem.confidence, 0.55),
                status=ClaimStatus.candidate,
                valid_from=mem.valid_from,
                valid_until=mem.valid_until,
                payload={**mem.payload, "split_from": claim_id},
                needs_review=True,
                review_reason=(
                    "split part — confirm"
                    if has_map else "split part — evidence mapping required"
                ),
                project_id=mem.project_id,
                entities=part.get("entities", mem.entities),
                impact=mem.impact,
                extractor_version=mem.extractor_version,
                quality_flags=[] if has_map else ["evidence_mapping_required"],
            )
            store.insert_claim(child)
            child_ids.append(child.id)

            if has_map:
                for eid in mapped_ids:
                    ev = by_id.get(eid)
                    if ev is None:
                        continue
                    new_eid = ids.evidence_id()
                    store.insert_evidence(Evidence(
                        id=new_eid, claim_id=child.id, percept_id=ev.percept_id,
                        quote=ev.quote, evidence_type=ev.evidence_type,
                        directness=ev.directness, source_trust=ev.source_trust,
                        independence_group=ev.independence_group, supports=True,
                        span_start=ev.span_start, span_end=ev.span_end,
                        artifact_id=ev.artifact_id,
                    ))
                    created_evidence.append(new_eid)
            else:
                # contextual only — does not claim to prove the child
                for ev in evidence:
                    new_eid = ids.evidence_id()
                    store.insert_evidence(Evidence(
                        id=new_eid, claim_id=child.id, percept_id=ev.percept_id,
                        quote=ev.quote, evidence_type="derived",  # type: ignore[arg-type]
                        directness=min(0.4, ev.directness),
                        source_trust=ev.source_trust,
                        independence_group=ev.independence_group,
                        supports=False,
                        artifact_id=ev.artifact_id,
                    ))
                    created_evidence.append(new_eid)

            rid = store.insert_relation(Relation(
                id=ids.relation_id(),
                subject_id=claim_id, predicate="split_into", object_id=child.id,
                claim_id=child.id,
            ))
            created_relations.append(rid)
            if embedder is not None:
                store.store_embedding(
                    child.id, "claim", embedder.name,
                    embedder.embed(f"{child.title}\n{child.summary}"),
                )

        store.update_claim(
            claim_id,
            status=ClaimStatus.split.value,
            needs_review=False,
            review_reason=None,
            payload={**mem.payload, "split_into": child_ids},
        )
        if hasattr(store, "delete_embedding"):
            store.delete_embedding(claim_id)  # type: ignore[attr-defined]

        after = {
            "created_claim_ids": child_ids,
            "created_evidence_ids": created_evidence,
            "created_relation_ids": created_relations,
            "deleted_embedding_refs": list(before["embeddings"].keys()),
        }
        op_id = _record_op(store, "split_memory", [claim_id], child_ids[0],
                           before, after, actor=actor)

    return LifecycleResult(
        "split", claim_id, child_ids[0],
        created_relations[0] if created_relations else "",
        op_id, extras={"source": claim_id, "children": child_ids},
    )


def archive_claim(store: TwinStore, claim_id: str, *,
                   reason: str = "archived", actor: str = "user") -> LifecycleResult:
    mem = store.get_claim(claim_id)
    if mem is None:
        raise ValueError(f"memory {claim_id} not found")
    with store.transaction():
        before = {
            "claims": {claim_id: _snapshot(mem)},
            "embeddings": {},
        }
        emb = _capture_embedding(store, claim_id)
        if emb:
            before["embeddings"][claim_id] = emb
        store.update_claim(
            claim_id,
            status=ClaimStatus.archived.value,
            needs_review=False,
            review_reason=reason,
        )
        if hasattr(store, "delete_embedding"):
            store.delete_embedding(claim_id)  # type: ignore[attr-defined]
        after = {"deleted_embedding_refs": list(before["embeddings"].keys())}
        op_id = _record_op(store, "archive", [claim_id], None, before, after, actor=actor)
    return LifecycleResult("archive", claim_id, claim_id, "", op_id)


def undo_operation(store: TwinStore, operation_id: str) -> dict[str, Any]:
    """Fully reverse a recorded structural operation inside one transaction."""
    if not hasattr(store, "get_operation"):
        raise ValueError("store does not support operations")
    op = store.get_operation(operation_id)  # type: ignore[attr-defined]
    if op is None:
        raise ValueError(f"operation {operation_id} not found")
    if not op.undoable or op.undone_at:
        raise ValueError(f"operation {operation_id} is not undoable")

    with store.transaction():
        after = op.after or {}
        before = op.before or {}

        # 1. remove created relations
        for rid in after.get("created_relation_ids", []):
            if hasattr(store, "delete_relation"):
                store.delete_relation(rid)  # type: ignore[attr-defined]

        # 2. remove created evidence
        for eid in after.get("created_evidence_ids", []):
            if hasattr(store, "delete_evidence_row"):
                store.delete_evidence_row(eid)  # type: ignore[attr-defined]

        # 3. remove created memories (merge result / split children)
        for mid in after.get("created_claim_ids", []):
            if hasattr(store, "hard_delete_claim"):
                store.hard_delete_claim(mid)  # type: ignore[attr-defined]
            else:
                store.update_claim(
                    mid, status=ClaimStatus.deleted.value,
                    deleted_at=now_iso(), deletion_reason="operation_undone",
                )
                if hasattr(store, "delete_embedding"):
                    store.delete_embedding(mid)  # type: ignore[attr-defined]

        # 4. restore claim snapshots
        mems = before.get("claims") or {}
        if not mems:
            # legacy shapes
            if "old" in before:
                mems[op.inputs[1] if len(op.inputs) > 1 else ""] = before["old"]
            if "a" in before:
                mems[op.inputs[0]] = before["a"]
            if "b" in before and len(op.inputs) > 1:
                mems[op.inputs[1]] = before["b"]
            if op.operation == "archive" and op.inputs:
                # old archive format stored {claim_id: snap} at top level sometimes
                for k, v in before.items():
                    if isinstance(v, dict) and "status" in v:
                        mems[k] = v
        for mid, snap in mems.items():
            if mid and snap:
                _restore_memory_fields(store, mid, snap)

        # 5. restore embeddings
        for emb in (before.get("embeddings") or {}).values():
            _restore_embedding(store, emb)
        for emb in before.get("deleted_embedding_refs") or []:
            if isinstance(emb, dict) and "blob" in emb:
                _restore_embedding(store, emb)

        if hasattr(store, "mark_operation_undone"):
            store.mark_operation_undone(operation_id)  # type: ignore[attr-defined]

    return {"undone": operation_id, "operation": op.operation}


# Deprecated aliases — prefer merge_claims / archive_claim / split_claim.
merge_memories = merge_claims
archive_memory = archive_claim
split_memory = split_claim
