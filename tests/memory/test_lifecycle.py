"""Explicit memory lifecycle (twin.store.lifecycle)."""

import pytest

from twin import ids
from twin.store.lifecycle import (
    contradict,
    merge_memories,
    split_memory,
    supersede,
    undo_operation,
)
from twin.store.models import Evidence, StoreClaim, ClaimStatus
from twin.sense.sensory.percept import Percept


def _mem(store, embedder, **kw):
    base = dict(
        id=ids.claim_id(), type="fact", title="t", summary="s",
        domain="technical", confidence=0.9, status="confirmed",
        entities=["Twin"], project_id="proj_twin",
    )
    base.update(kw)
    mem = StoreClaim(**base)
    store.insert_claim(mem)
    store.store_embedding(
        mem.id, "claim", embedder.name,
        embedder.embed(f"{mem.title}\n{mem.summary}"),
    )
    return mem


def test_supersede_closes_old_memory(store, embedder):
    old = _mem(store, embedder, type="belief", title="microservices",
               summary="Prefere microservices.", valid_from="2023-01-01")
    new = _mem(store, embedder, type="belief", title="modular monolith",
               summary="Prefere modular monolith.", valid_from="2026-07-01")
    result = supersede(store, new.id, old.id)
    reloaded = store.get_claim(old.id)
    assert reloaded.status.value == "deprecated"
    assert reloaded.valid_until == "2026-07-01"
    rels = store.relations_for(new.id)
    assert any(r.predicate == "supersedes" and r.object_id == old.id for r in rels)
    assert result.action == "supersede"


def test_meeting_candidate_supersedes_prior_decision_after_confirm(store, embedder):
    """Later meeting evidence can supersede a prior decision — only after confirm.

    Candidates from connectors stay candidates until review confirms; supersede
    is an explicit Memory lifecycle action.
    """
    from twin.clock import now_iso
    from twin.store.models import Evidence, ClaimStatus
    from twin.sense.sensory.percept import Percept

    pr = Percept(
        id=ids.new_id("pct"),
        percept_type="pull_request",
        source_sensor="github",
        occurred_at="2026-07-10T10:00:00Z",
        ingested_at=now_iso(),
        content="Decision: ship Atlas Friday.",
        source_trust=0.85,
        source_scope="work",
        source_confidentiality="internal",
    )
    pr.seal()
    store.insert_percept(pr)
    meeting = Percept(
        id=ids.new_id("pct"),
        percept_type="meeting_transcript_chunk",
        source_sensor="fireflies",
        occurred_at="2026-07-11T15:00:00Z",
        ingested_at=now_iso(),
        content="Postpone the Atlas ship to next sprint.",
        source_trust=0.80,
        source_scope="work",
        source_confidentiality="internal",
    )
    meeting.seal()
    store.insert_percept(meeting)

    old = _mem(
        store, embedder, type="decision", title="Ship Atlas Friday",
        summary="Decision: ship Atlas Friday.", status="candidate",
        confidence=0.75,
    )
    store.insert_evidence(Evidence(
        id=ids.new_id("ev"), claim_id=old.id, quote="ship Atlas Friday",
        percept_id=pr.id, artifact_id="github:pr:atlas#8",
        independence_group="lineage:github:acme/atlas#8",
    ))
    new = _mem(
        store, embedder, type="decision", title="Postpone Atlas ship",
        summary="Postpone the Atlas ship to next sprint.", status="candidate",
        confidence=0.80,
    )
    store.insert_evidence(Evidence(
        id=ids.new_id("ev"), claim_id=new.id, quote="postpone the Atlas ship",
        percept_id=meeting.id, artifact_id="fireflies:meeting:m1",
        independence_group="meeting:m1",
    ))

    assert store.get_claim(old.id).status == ClaimStatus.candidate
    assert store.get_claim(new.id).status == ClaimStatus.candidate
    store.update_claim(new.id, status=ClaimStatus.confirmed.value)
    result = supersede(store, new.id, old.id)
    assert result.action == "supersede"
    assert store.get_claim(old.id).status == ClaimStatus.deprecated
    assert store.get_claim(new.id).status == ClaimStatus.confirmed


def test_contradict_flags_both_for_review(store, embedder):
    a = _mem(store, embedder, title="usa tabs", summary="Prefere tabs.")
    b = _mem(store, embedder, title="usa espaços", summary="Prefere espaços.")
    contradict(store, a.id, b.id)
    assert store.get_claim(b.id).status.value == "contradicted"
    assert store.get_claim(a.id).needs_review
    assert store.get_claim(b.id).needs_review
    rels = store.relations_for(a.id)
    assert any(r.predicate == "contradicts" for r in rels)


def test_lifecycle_rejects_self_reference(store, embedder):
    mem = _mem(store, embedder)
    with pytest.raises(ValueError):
        supersede(store, mem.id, mem.id)
    with pytest.raises(ValueError):
        contradict(store, mem.id, mem.id)


def test_lifecycle_requires_existing_memories(store, embedder):
    mem = _mem(store, embedder)
    with pytest.raises(ValueError):
        supersede(store, mem.id, "mem_inexistente")
    with pytest.raises(ValueError):
        contradict(store, "mem_inexistente", mem.id)


def test_merge_preserves_evidence_and_undo(store, embedder):
    p = Percept(id=ids.new_id("pct"), percept_type="document", source_sensor="document",
                content="Twin uses FastAPI for the API.")
    store.insert_percept(p)
    a = _mem(store, embedder, title="FastAPI", summary="Twin uses FastAPI.",
             status="confirmed")
    b = _mem(store, embedder, title="API FastAPI", summary="The Twin API is built with FastAPI.",
             status="confirmed")
    store.insert_evidence(Evidence(id=ids.evidence_id(), claim_id=a.id, percept_id=p.id,
                                   quote="Twin uses FastAPI"))
    store.insert_evidence(Evidence(id=ids.evidence_id(), claim_id=b.id, percept_id=p.id,
                                   quote="API is built with FastAPI"))
    result = merge_memories(store, [a.id, b.id], title="Twin HTTP API uses FastAPI",
                            embedder=embedder)
    merged_id = result.extras["merged_id"]
    merged = store.get_claim(merged_id)
    assert merged is not None
    assert store.get_claim(a.id).status == ClaimStatus.merged
    assert store.get_claim(b.id).status == ClaimStatus.merged
    assert len(store.get_evidence(merged_id)) >= 1
    assert result.operation_id
    undo_operation(store, result.operation_id)
    assert store.get_claim(a.id).status != ClaimStatus.merged


def test_undo_restores_embeddings_and_graph(store, embedder):
    a = _mem(store, embedder, title="FastAPI", summary="Twin uses FastAPI.")
    b = _mem(store, embedder, title="API FastAPI", summary="The Twin API uses FastAPI.")
    result = merge_memories(
        store, [a.id, b.id],
        title="Twin HTTP API uses FastAPI",
        summary="Twin HTTP API uses FastAPI.",
        human_confirmed_synthesis=True, embedder=embedder,
    )
    merged_id = result.extras["merged_id"]
    assert store.get_claim(a.id).status == ClaimStatus.merged
    assert store.get_embedding_blob(a.id) is None

    undo_operation(store, result.operation_id)
    assert store.get_claim(a.id).status == ClaimStatus.confirmed
    assert store.get_claim(b.id).status == ClaimStatus.confirmed
    assert store.get_embedding_blob(a.id) is not None
    assert store.get_claim(merged_id) is None
    rels = store.relations_for(a.id)
    assert not any(r.predicate == "merged_into" and r.object_id == merged_id for r in rels)


def test_split_creates_children(store, embedder):
    mem = _mem(
        store, embedder,
        title="stack",
        summary="Twin uses PostgreSQL in production, SQLite in development, and FastAPI for its API.",
        status="candidate", needs_review=True,
    )
    result = split_memory(store, mem.id, [
        {"title": "Postgres prod", "summary": "Twin production storage uses PostgreSQL."},
        {"title": "SQLite dev", "summary": "Twin development storage can use SQLite."},
        {"title": "FastAPI", "summary": "Twin HTTP API uses FastAPI."},
    ], embedder=embedder)
    assert store.get_claim(mem.id).status == ClaimStatus.split
    children = result.extras["children"]
    assert len(children) == 3
    for cid in children:
        assert store.get_claim(cid).status == ClaimStatus.candidate


def test_split_evidence_mapping(store, embedder):
    mem = _mem(
        store, embedder, title="stack",
        summary="Twin uses PostgreSQL in production and SQLite locally.",
        status="candidate", needs_review=True,
    )
    p = Percept(id=ids.new_id("pct"), percept_type="document", source_sensor="document",
                content="PostgreSQL is the primary production backend.")
    store.insert_percept(p)
    ev = Evidence(id=ids.evidence_id(), claim_id=mem.id, percept_id=p.id,
                  quote="PostgreSQL is the primary production backend.")
    store.insert_evidence(ev)

    result = split_memory(store, mem.id, [
        {"title": "Postgres prod", "summary": "Twin production storage uses PostgreSQL.",
         "evidence_ids": [ev.id]},
        {"title": "SQLite local", "summary": "Twin development storage can use SQLite.",
         "evidence_ids": []},
    ], embedder=embedder)
    children = result.extras["children"]
    child_a = store.get_claim(children[0])
    child_b = store.get_claim(children[1])
    ev_a = store.get_evidence(child_a.id)
    ev_b = store.get_evidence(child_b.id)
    assert any(e.supports for e in ev_a)
    assert not any(e.supports for e in ev_b) or "evidence_mapping_required" in child_b.quality_flags


def test_merge_blocks_cross_domain(store, embedder):
    a = _mem(store, embedder, domain="technical", type="decision",
             title="tech", summary="technical decision")
    b = _mem(store, embedder, domain="relationship", type="decision",
             title="rel", summary="relationship decision", entities=["Partner"])
    with pytest.raises(ValueError, match="life domains|mixed domains"):
        merge_memories(store, [a.id, b.id], confirm_cross_scope_merge=True, embedder=embedder)


def test_merge_cross_type_requires_output_semantics(store, embedder):
    a = _mem(store, embedder, type="decision", title="ship it",
             summary="We decided to ship the release.")
    b = _mem(store, embedder, type="belief", title="ship belief",
             summary="I believe shipping the release is right.")
    with pytest.raises(ValueError, match="mixed types"):
        merge_memories(store, [a.id, b.id], embedder=embedder)
    with pytest.raises(ValueError, match="output_type"):
        merge_memories(
            store, [a.id, b.id], confirm_cross_scope_merge=True, embedder=embedder,
        )
    result = merge_memories(
        store, [a.id, b.id],
        confirm_cross_scope_merge=True,
        output_type="decision",
        title="Ship release",
        summary="Decision: ship the release.",
        embedder=embedder,
    )
    merged = store.get_claim(result.extras["merged_id"])
    assert merged is not None
    assert merged.type.value == "decision"


def test_merge_rolls_back_on_mid_failure(store, embedder):
    a = _mem(store, embedder, title="A", summary="Twin uses FastAPI.")
    b = _mem(store, embedder, title="B", summary="API built with FastAPI.")
    p = Percept(id=ids.new_id("pct"), percept_type="document", source_sensor="document",
                content="FastAPI")
    store.insert_percept(p)
    store.insert_evidence(Evidence(id=ids.evidence_id(), claim_id=a.id, percept_id=p.id,
                                   quote="FastAPI"))
    store.insert_evidence(Evidence(id=ids.evidence_id(), claim_id=b.id, percept_id=p.id,
                                   quote="FastAPI"))

    real_insert = store.insert_relation
    calls = {"n": 0}

    def boom(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("injected relation failure")
        return real_insert(*args, **kwargs)

    store.insert_relation = boom  # type: ignore[method-assign]
    before_ids = {m.id for m in store.list_claims(limit=100)}
    with pytest.raises(RuntimeError):
        merge_memories(store, [a.id, b.id], embedder=embedder)
    store.insert_relation = real_insert  # type: ignore[method-assign]

    after = store.list_claims(limit=100)
    assert {m.id for m in after} == before_ids
    assert store.get_claim(a.id).status == ClaimStatus.confirmed
    assert store.get_claim(b.id).status == ClaimStatus.confirmed


def test_merge_transaction_rollback_on_fault(store, embedder):
    a = _mem(store, embedder, title="A", summary="alpha fact about Twin")
    b = _mem(store, embedder, title="B", summary="beta fact about Twin")
    a_id, b_id = a.id, b.id
    before_ids = {m.id for m in store.list_claims(limit=1000)}

    real_update = store.update_claim
    calls = {"n": 0}

    def boom(mid, **kwargs):
        calls["n"] += 1
        if kwargs.get("status") == ClaimStatus.merged.value and calls["n"] >= 2:
            raise RuntimeError("injected failure")
        return real_update(mid, **kwargs)

    store.update_claim = boom  # type: ignore[method-assign]
    try:
        with pytest.raises(RuntimeError, match="injected"):
            merge_memories(store, [a_id, b_id], embedder=embedder)
    finally:
        store.update_claim = real_update  # type: ignore[method-assign]

    assert store.get_claim(a_id).status != ClaimStatus.merged
    assert store.get_claim(b_id).status != ClaimStatus.merged
    after_ids = {m.id for m in store.list_claims(limit=1000)}
    assert after_ids == before_ids
