"""PO review #6 — blocking consistency and reversibility scenarios."""

import pytest

from twin import ids
from twin.cognition.quality import (
    _looks_conflict,
    analyze_memory,
    build_duplicate_groups,
    review_priority,
    select_canonical_survivor,
)
from twin.evals import default_eval_root, run_extraction_eval, run_retrieval_eval
from twin.memory.automation import apply_safe_automations
from twin.memory.lifecycle import merge_memories, split_memory, undo_operation
from twin.memory.models import Evidence, MemoryItem, MemoryStatus
from twin.memory.provenance import ensure_artifact_from_percept
from twin.memory.retention import delete_artifact
from twin.sensory.percept import Percept


def _mem(store, embedder, **kw):
    base = dict(
        id=ids.memory_id(), type="fact", title="t", summary="s",
        domain="technical", confidence=0.9, status="confirmed",
        entities=["Twin"], project_id="proj_twin",
    )
    base.update(kw)
    mem = MemoryItem(**base)
    store.insert_memory(mem)
    store.store_embedding(
        mem.id, "memory", embedder.name,
        embedder.embed(f"{mem.title}\n{mem.summary}"),
    )
    return mem


def test_merge_rolls_back_on_mid_failure(store, embedder):
    a = _mem(store, embedder, title="A", summary="Twin uses FastAPI.")
    b = _mem(store, embedder, title="B", summary="API built with FastAPI.")
    p = Percept(id=ids.new_id("pct"), percept_type="document", source_sensor="document",
                content="FastAPI")
    store.insert_percept(p)
    store.insert_evidence(Evidence(id=ids.evidence_id(), memory_id=a.id, percept_id=p.id,
                                   quote="FastAPI"))
    store.insert_evidence(Evidence(id=ids.evidence_id(), memory_id=b.id, percept_id=p.id,
                                   quote="FastAPI"))

    real_insert = store.insert_relation
    calls = {"n": 0}

    def boom(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("injected relation failure")
        return real_insert(*args, **kwargs)

    store.insert_relation = boom  # type: ignore[method-assign]
    before_ids = {m.id for m in store.list_memories(limit=100)}
    with pytest.raises(RuntimeError):
        merge_memories(store, [a.id, b.id], embedder=embedder)
    store.insert_relation = real_insert  # type: ignore[method-assign]

    after = store.list_memories(limit=100)
    assert {m.id for m in after} == before_ids
    assert store.get_memory(a.id).status == MemoryStatus.confirmed
    assert store.get_memory(b.id).status == MemoryStatus.confirmed


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
    assert store.get_memory(a.id).status == MemoryStatus.merged
    assert store.get_embedding_blob(a.id) is None

    undo_operation(store, result.operation_id)
    assert store.get_memory(a.id).status == MemoryStatus.confirmed
    assert store.get_memory(b.id).status == MemoryStatus.confirmed
    assert store.get_embedding_blob(a.id) is not None
    assert store.get_memory(merged_id) is None
    rels = store.relations_for(a.id)
    assert not any(r.predicate == "merged_into" and r.object_id == merged_id for r in rels)


def test_exact_duplicate_keeps_one_survivor(store, embedder):
    a = _mem(store, embedder, title="Same", summary="Same claim text.",
             status="candidate", needs_review=True, confidence=0.7,
             quality_flags=["exact_duplicate"])
    b = _mem(store, embedder, title="Same", summary="Same claim text.",
             status="candidate", needs_review=True, confidence=0.9,
             quality_flags=["exact_duplicate"])
    c = _mem(store, embedder, title="Same", summary="Same claim text.",
             status="confirmed", confidence=0.8,
             quality_flags=["exact_duplicate"])
    analyze_memory(store, embedder, a.id)
    analyze_memory(store, embedder, b.id)
    analyze_memory(store, embedder, c.id)
    for m in (a, b, c):
        store.update_memory(m.id, quality_flags=["exact_duplicate"])

    groups = build_duplicate_groups(store, [
        store.get_memory(a.id), store.get_memory(b.id), store.get_memory(c.id),
    ])
    assert groups
    survivor = select_canonical_survivor(
        [store.get_memory(x) for x in groups[0].memory_ids], store,
    )
    assert survivor.id == c.id

    apply_safe_automations(store, dry_run=False)
    rejected = sum(
        1 for mid in (a.id, b.id, c.id)
        if store.get_memory(mid).status == MemoryStatus.rejected
    )
    assert rejected == 2
    assert store.get_memory(c.id).status != MemoryStatus.rejected


def test_delete_artifact_does_not_cascade_by_hash(store, embedder):
    from twin.memory.models import Artifact
    from twin.clock import now_iso

    p1 = Percept(id=ids.new_id("pct"), percept_type="document", source_sensor="git",
                 content="readme from git commit abc", metadata={"sha": "aaa"})
    p2 = Percept(id=ids.new_id("pct"), percept_type="document", source_sensor="document",
                 content="readme local copy distinct bytes", metadata={"path": "local-copy"})
    assert store.insert_percept(p1)
    assert store.insert_percept(p2)
    # Artifact A intentionally carries the same content_hash as percept B.
    # Explicit lineage still points only at percept A — hash must not cascade.
    art1 = Artifact(id=ids.artifact_id(), kind="git_commit", source_system="git",
                    content_hash=p2.content_hash, created_at=now_iso(),
                    metadata={"percept_id": p1.id})
    art2 = Artifact(id=ids.artifact_id(), kind="document", source_system="document",
                    content_hash=p2.content_hash, created_at=now_iso(),
                    metadata={"percept_id": p2.id})
    store.insert_artifact(art1)
    store.insert_artifact(art2)
    store.link_artifact_percept(art1.id, p1.id)
    store.link_artifact_percept(art2.id, p2.id)

    m1 = _mem(store, embedder, title="from git", summary="README decision from git.")
    m2 = _mem(store, embedder, title="from local", summary="README decision from local copy.")
    store.insert_evidence(Evidence(
        id=ids.evidence_id(), memory_id=m1.id, percept_id=p1.id,
        quote="README", artifact_id=art1.id,
    ))
    store.insert_evidence(Evidence(
        id=ids.evidence_id(), memory_id=m2.id, percept_id=p2.id,
        quote="README", artifact_id=art2.id,
    ))

    plan = delete_artifact(store, art1.id, dry_run=False)
    assert p2.id not in plan["percepts"]
    assert "[content destroyed]" not in store.get_percept(p2.id).content
    assert store.get_memory(m2.id).status == MemoryStatus.confirmed


def test_different_decisions_not_conflict():
    a = MemoryItem(
        id="a", type="decision", title="Postgres",
        summary="Twin uses PostgreSQL as primary storage.",
        domain="technical", entities=["Twin", "PostgreSQL"], project_id="p",
    )
    b = MemoryItem(
        id="b", type="decision", title="FastAPI",
        summary="Twin uses FastAPI for its HTTP API.",
        domain="technical", entities=["Twin", "FastAPI"], project_id="p",
    )
    kind = _looks_conflict(a, b, sim=0.7, claim_match=0.82)
    assert kind in (None, "possibly_related", "scope_difference")
    assert kind != "possible_conflict"


def test_priority_floors_for_high_confidence_conflict():
    mem = MemoryItem(
        id="x", type="decision", title="db", summary="uses postgres",
        domain="technical", confidence=0.95, impact="high", sensitivity="public",
    )
    low = review_priority(mem, contradiction_risk=0.0)
    high = review_priority(mem, contradiction_risk=0.95)
    assert high >= 0.9
    assert high > low


def test_merge_blocks_cross_domain(store, embedder):
    a = _mem(store, embedder, domain="technical", type="decision",
             title="tech", summary="technical decision")
    b = _mem(store, embedder, domain="relationship", type="decision",
             title="rel", summary="relationship decision", entities=["Partner"])
    with pytest.raises(ValueError, match="life domains|mixed domains"):
        merge_memories(store, [a.id, b.id], confirm_cross_scope_merge=True, embedder=embedder)


def test_split_evidence_mapping(store, embedder):
    mem = _mem(
        store, embedder, title="stack",
        summary="Twin uses PostgreSQL in production and SQLite locally.",
        status="candidate", needs_review=True,
    )
    p = Percept(id=ids.new_id("pct"), percept_type="document", source_sensor="document",
                content="PostgreSQL is the primary production backend.")
    store.insert_percept(p)
    ev = Evidence(id=ids.evidence_id(), memory_id=mem.id, percept_id=p.id,
                  quote="PostgreSQL is the primary production backend.")
    store.insert_evidence(ev)

    result = split_memory(store, mem.id, [
        {"title": "Postgres prod", "summary": "Twin production storage uses PostgreSQL.",
         "evidence_ids": [ev.id]},
        {"title": "SQLite local", "summary": "Twin development storage can use SQLite.",
         "evidence_ids": []},
    ], embedder=embedder)
    children = result.extras["children"]
    child_a = store.get_memory(children[0])
    child_b = store.get_memory(children[1])
    ev_a = store.get_evidence(child_a.id)
    ev_b = store.get_evidence(child_b.id)
    assert any(e.supports for e in ev_a)
    assert not any(e.supports for e in ev_b) or "evidence_mapping_required" in child_b.quality_flags


def test_evals_isolated_and_reject_empty_retrieval(store, cfg, embedder, tmp_path):
    before = len(store.list_memories(limit=1000))
    run = run_extraction_eval(store, cfg, embedder, default_eval_root() / "extraction")
    assert len(store.list_memories(limit=1000)) == before
    assert run.summary.get("status") == "implemented"

    bad = tmp_path / "retrieval"
    bad.mkdir()
    (bad / "empty.json").write_text(
        '{"id":"empty","query":"x","expected_memory_ids":[]}', encoding="utf-8",
    )
    run2 = run_retrieval_eval(store, embedder, bad)
    assert run2.cases
    assert run2.cases[0].passed is False

    run3 = run_retrieval_eval(store, embedder, default_eval_root() / "retrieval", cfg=cfg)
    assert len(store.list_memories(limit=1000)) == before
    assert run3.summary.get("status") == "implemented"
