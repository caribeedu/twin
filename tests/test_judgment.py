"""Evolving judgment model (twin.judgment.*) — versioned, proposal-driven."""

import pytest

from twin import ids
from twin.cognition.context_pack import build_context_pack
from twin.judgment.application import applicable_pack, render_applicable
from twin.judgment.conflicts import detect_judgment_conflicts
from twin.judgment.models import (
    ExceptionEffect,
    JudgmentException,
    JudgmentItem,
    JudgmentKind,
    JudgmentProposal,
    JudgmentScope,
    JudgmentStability,
    JudgmentStatus,
    ProposalAction,
    ProposalStatus,
)
from twin.judgment.proposals import (
    approve_proposal,
    preview_proposal,
    propose_from_memory,
    propose_from_pattern,
    reject_proposal,
)
from twin.judgment.simulate import counterfactual, simulate
from twin.judgment.versions import active_items, create_version, restore_version
from twin.judgment.yaml_io import apply_yaml_import, preview_yaml_import
from twin.memory.models import MemoryItem
from twin.clock import now_iso


def _mem(store, embedder, **kw):
    base = dict(
        id=ids.memory_id(), type="decision", title="t", summary="s",
        domain="technical", confidence=0.9, status="confirmed",
        entities=["Twin"],
    )
    base.update(kw)
    mem = MemoryItem(**base)
    store.insert_memory(mem)
    store.store_embedding(
        mem.id, "memory", embedder.name,
        embedder.embed(f"{mem.title}\n{mem.summary}"),
    )
    return mem


def test_yaml_import_preview_and_apply(store, cfg):
    preview = preview_yaml_import(cfg.judgment_path)
    assert preview
    kinds = {c["kind"] for c in preview}
    assert "principle" in kinds or "constraint" in kinds
    assert any(c["stability"] == "constitutional" for c in preview)
    result = apply_yaml_import(store, cfg.judgment_path, classifications=preview)
    assert result["count"] == len(preview)
    assert store.get_active_judgment_version() is not None
    assert active_items(store)


def test_promote_creates_proposal_not_active_item(store, cfg, embedder):
    from twin.judgment.profile import promote_memory

    mem = _mem(
        store, embedder, type="preference",
        title="ADRs", summary="Prefere ADRs no próprio repositório.",
    )
    section = promote_memory(cfg.judgment_path, mem, store=store)
    assert section.startswith("proposal:")
    proposals = store.list_judgment_proposals(status="pending")
    assert any(mem.id in p.supporting_memory_ids for p in proposals)
    assert not any(
        "ADRs" in i.statement for i in store.list_judgment_items(status="active")
    )


def test_proposal_preview_token_and_approve(store, cfg, embedder):
    apply_yaml_import(store, cfg.judgment_path)
    mem = _mem(
        store, embedder, type="preference",
        title="short answers", summary="Prefere respostas curtas em perguntas simples.",
    )
    prop = propose_from_memory(store, mem.id)
    preview = preview_proposal(store, prop.id)
    token = preview["preview_token"]
    with pytest.raises(ValueError, match="preview_token"):
        approve_proposal(store, prop.id, preview_token="bad")
    result = approve_proposal(store, prop.id, preview_token=token)
    item = store.get_judgment_item(result["judgment_id"])
    assert item is not None
    assert item.status == JudgmentStatus.active
    assert item.approved_by == "user"


def test_constitutional_requires_extra_confirm(store, cfg):
    prop = JudgmentProposal(
        id=ids.judgment_proposal_id(),
        action=ProposalAction.create,
        proposed_item={
            "kind": "constraint",
            "statement": "Never mix intimate context with work.",
            "stability": "constitutional",
            "strength": 1.0,
            "confidence": 0.95,
            "domain": "technical",
        },
        reason="explicit",
        confidence=0.95,
        status=ProposalStatus.pending,
        created_at=now_iso(),
    )
    store.insert_judgment_proposal(prop)
    token = preview_proposal(store, prop.id)["preview_token"]
    with pytest.raises(ValueError, match="constitutional"):
        approve_proposal(store, prop.id, preview_token=token)
    approve_proposal(
        store, prop.id,
        preview_token=preview_proposal(store, prop.id)["preview_token"],
        confirm_constitutional=True,
    )
    assert any(i.stability == JudgmentStability.constitutional for i in active_items(store))


def test_applicable_respects_scope_and_precedence(store, cfg):
    apply_yaml_import(store, cfg.judgment_path)
    now = now_iso()
    store.insert_judgment_item(JudgmentItem(
        id=ids.judgment_id(), kind=JudgmentKind.preference,
        statement="Use a warm diplomatic tone",
        domain="assistant_preferences",
        scope=JudgmentScope(domains=["assistant_preferences"], audiences=["external"]),
        strength=0.9, confidence=0.9, stability=JudgmentStability.evolving,
        status=JudgmentStatus.active, created_at=now, updated_at=now,
        approved_at=now, approved_by="user",
    ))
    create_version(store, reason="add tone pref")
    pack = applicable_pack(store, domain="technical", task_profile="architecture")
    stmts = [i["statement"] for i in pack["applicable_judgments"]]
    assert not any("diplomatic" in s.lower() for s in stmts)
    assert pack["snapshot_id"]
    text = render_applicable(pack)
    assert "Hard constraints" in text or "Principles" in text


def test_exception_reduces_strength(store, cfg):
    apply_yaml_import(store, cfg.judgment_path)
    now = now_iso()
    item = JudgmentItem(
        id=ids.judgment_id(), kind=JudgmentKind.heuristic,
        statement="Be direct in all communication",
        domain="assistant_preferences",
        scope=JudgmentScope(domains=["assistant_preferences"]),
        strength=0.9, confidence=0.9,
        status=JudgmentStatus.active, created_at=now, updated_at=now,
        approved_at=now, approved_by="user",
        exceptions=[JudgmentException(
            id=ids.judgment_exception_id(),
            condition="external candidate rejection",
            effect=ExceptionEffect.reduce_strength,
            value=0.3,
            reason="avoid unnecessary harshness",
        )],
    )
    store.insert_judgment_item(item)
    create_version(store, reason="exception demo")
    pack = applicable_pack(
        store, domain="assistant_preferences",
        query="Write a rejection to an external candidate",
    )
    matched = [i for i in pack["applicable_judgments"] if i["id"] == item.id]
    assert matched
    assert matched[0]["strength"] <= 0.3
    assert pack["exceptions_used"]


def test_simulate_blocks_and_traces(store, cfg):
    apply_yaml_import(store, cfg.judgment_path)
    result = simulate(
        store,
        "Should Twin migrate from PostgreSQL to Neo4j?",
        domain="technical",
        options=["PostgreSQL", "Neo4j", "custom graph engine"],
    )
    assert result["snapshot_id"]
    assert result["trace_id"]
    assert result["recommendation"] != "custom graph engine" or (
        "custom graph engine" in result["blocked_options"]
    )


def test_counterfactual_without_item(store, cfg):
    apply_yaml_import(store, cfg.judgment_path)
    items = active_items(store)
    assert items
    target = items[0]
    cf = counterfactual(
        store, "PostgreSQL vs Neo4j for Twin?",
        target.id, domain="technical",
        options=["PostgreSQL", "Neo4j"],
    )
    assert "baseline_recommendation" in cf
    assert cf["without_judgment_id"] == target.id


def test_pattern_proposal_needs_independent_projects(store, embedder):
    for i, proj in enumerate(("p1", "p2", "p3")):
        _mem(
            store, embedder,
            title=f"MVP stack {i}",
            summary="Choose SQLite for simplicity and reversibility in the MVP.",
            project_id=proj,
        )
    props = propose_from_pattern(store, domain="technical", min_evidence=3, min_projects=2)
    assert props
    assert props[0].support_count >= 3


def test_twin_influenced_evidence_downweighted(store, embedder):
    for i, proj in enumerate(("p1", "p2", "p3")):
        m = _mem(
            store, embedder,
            title=f"assisted {i}",
            summary="Choose SQLite for simplicity and reversibility in the MVP.",
            project_id=proj,
        )
        store.update_memory(m.id, payload={"judgment_influenced": True})
    props = propose_from_pattern(store, domain="technical", min_evidence=3, min_projects=2)
    assert props == [] or props[0].confidence < 0.7


def test_version_restore(store, cfg):
    r1 = apply_yaml_import(store, cfg.judgment_path)
    v1 = store.get_judgment_version(r1["version_id"])
    assert v1 is not None
    now = now_iso()
    extra = JudgmentItem(
        id=ids.judgment_id(), kind=JudgmentKind.preference,
        statement="Prefer dark themes", domain="assistant_preferences",
        status=JudgmentStatus.active, created_at=now, updated_at=now,
        approved_at=now, approved_by="user",
    )
    store.insert_judgment_item(extra)
    v2 = create_version(store, reason="theme pref")
    assert v2.version > v1.version
    restored = restore_version(store, v1.id)
    assert restored.version > v2.version
    reloaded = store.get_judgment_item(extra.id)
    assert reloaded is not None
    assert reloaded.status != JudgmentStatus.active or extra.id not in restored.item_ids


def test_context_pack_uses_structured_judgment(store, cfg, embedder):
    apply_yaml_import(store, cfg.judgment_path)
    pack = build_context_pack(
        store, cfg, embedder, "architecture choice",
        target_domain="technical", task_profile="architecture",
    )
    assert "Judgment" in pack.context_pack


def test_reject_proposal(store, cfg, embedder):
    mem = _mem(
        store, embedder, type="belief", title="b",
        summary="Microservices are always better.",
    )
    prop = propose_from_memory(store, mem.id)
    reject_proposal(store, prop.id, reason="overgeneralization")
    assert store.get_judgment_proposal(prop.id).status.value == "rejected"


def test_judgment_conflict_detection(store, cfg):
    now = now_iso()
    a = JudgmentItem(
        id=ids.judgment_id(), kind=JudgmentKind.principle,
        statement="Prefer simplicity in MVP", domain="technical",
        status=JudgmentStatus.active, created_at=now, updated_at=now,
        approved_at=now, approved_by="user",
    )
    b = JudgmentItem(
        id=ids.judgment_id(), kind=JudgmentKind.principle,
        statement="Prefer microservices for every scalable system", domain="technical",
        status=JudgmentStatus.active, created_at=now, updated_at=now,
        approved_at=now, approved_by="user",
    )
    store.insert_judgment_item(a)
    store.insert_judgment_item(b)
    create_version(store, reason="conflict pair")
    found = detect_judgment_conflicts(store)
    assert found
