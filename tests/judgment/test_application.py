"""Evolving judgment model — immutable revisions, human-gated constitution."""

import pytest

from twin import ids
from twin.clock import now_iso
from twin.inject.context_pack import build_context_pack
from twin.privacy.identity import ensure_local_identity, resolve_access
from twin.privacy.yaml_io import bootstrap_policy_set
from twin.cognize.stance_engine.application import applicable_pack
from twin.cognize.stance_engine.conflicts import (
    detect_behavior_conflicts,
    detect_judgment_conflicts,
    resolve_conflict,
)
from twin.cognize.stance_engine.models import (
    ExceptionEffect,
    JudgmentException,
    JudgmentItem,
    JudgmentKind,
    JudgmentProposal,
    JudgmentProvenance,
    JudgmentScope,
    JudgmentStability,
    JudgmentStatus,
    ProposalAction,
    ProposalStatus,
)
from twin.cognize.stance_engine.proposals import (
    approve_proposal,
    preview_proposal,
    propose_from_memory,
    propose_from_pattern,
    reject_proposal,
)
from twin.cognize.stance_engine.revisions import commit_new_item
from twin.cognize.stance_engine.simulate import counterfactual, evaluate, simulate
from twin.cognize.stance_engine.versions import active_items, create_version, restore_version
from twin.cognize.stance_engine.yaml_io import apply_yaml_import, preview_yaml_import
from twin.store.models import MemoryItem
from twin.privacy.identity import ensure_local_identity, resolve_access
from twin.privacy.yaml_io import bootstrap_policy_set


def _cli_access(store):
    bootstrap_policy_set(store)
    ensure_local_identity(store)
    return resolve_access(store, surface="cli", persona="individual",
                          purpose="memory_retrieval", audience="self")



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


def test_yaml_import_creates_revisions(store, cfg):
    preview = preview_yaml_import(cfg.judgment_path)
    result = apply_yaml_import(store, cfg.judgment_path, classifications=preview)
    assert result["count"] == len(preview)
    assert result["revision_ids"]
    version = store.get_active_judgment_version()
    assert version is not None
    assert version.revision_ids
    for rid in version.revision_ids:
        assert store.get_judgment_revision(rid) is not None


def test_conflict_detection_does_not_deactivate(store, cfg, embedder):
    apply_yaml_import(store, cfg.judgment_path)
    before = {i.id for i in active_items(store)}
    for i, proj in enumerate(("p1", "p2", "p3")):
        _mem(
            store, embedder,
            title=f"complex {i}",
            summary="Adopt microservices and Neo4j for every scalable system.",
            project_id=proj,
        )
    detect_behavior_conflicts(store, domain="technical", min_exceptions=3)
    after = {i.id for i in active_items(store)}
    assert before == after
    assert store.list_judgment_conflicts(status="open")


def test_judgment_conflict_dedupes(store, cfg):
    now = now_iso()
    a, _ = commit_new_item(store, JudgmentItem(
        id=ids.judgment_id(), kind=JudgmentKind.principle,
        statement="Prefer simplicity in MVP", domain="technical",
        status=JudgmentStatus.active, created_at=now, updated_at=now,
        approved_at=now, approved_by="user",
    ))
    b, _ = commit_new_item(store, JudgmentItem(
        id=ids.judgment_id(), kind=JudgmentKind.principle,
        statement="Prefer microservices for every scalable system", domain="technical",
        status=JudgmentStatus.active, created_at=now, updated_at=now,
        approved_at=now, approved_by="user",
    ))
    create_version(store, reason="pair")
    first = detect_judgment_conflicts(store)
    second = detect_judgment_conflicts(store)
    open_conflicts = store.list_judgment_conflicts(status="open")
    pair = [
        c for c in open_conflicts
        if {c.judgment_id, c.other_judgment_id} == {a.id, b.id}
    ]
    assert len(pair) == 1


def test_preview_edits_change_token(store, cfg, embedder):
    mem = _mem(
        store, embedder, type="preference",
        title="short", summary="Prefere respostas curtas.",
    )
    prop = propose_from_memory(store, mem.id)
    p1 = preview_proposal(store, prop.id)
    p2 = preview_proposal(store, prop.id, edits={"kind": "principle", "strength": 0.9})
    assert p1["preview_token"] != p2["preview_token"]
    with pytest.raises(ValueError, match="preview_token"):
        approve_proposal(store, prop.id, preview_token=p1["preview_token"], edits={"kind": "principle"})
    result = approve_proposal(
        store, prop.id, preview_token=p2["preview_token"],
        edits={"kind": "principle", "strength": 0.9},
    )
    item = store.get_judgment_item(result["judgment_id"])
    assert item.kind == JudgmentKind.principle


def test_supporting_memory_change_invalidates_token(store, cfg, embedder):
    mem = _mem(
        store, embedder, type="preference",
        title="x", summary="Prefere ferramentas locais.",
    )
    prop = propose_from_memory(store, mem.id)
    token = preview_proposal(store, prop.id)["preview_token"]
    store.update_memory(mem.id, summary="Prefere ferramentas locais — edited after preview.")
    with pytest.raises(ValueError, match="preview_token"):
        approve_proposal(store, prop.id, preview_token=token)


def test_proposal_actions_update_weaken_deprecate(store, cfg):
    apply_yaml_import(store, cfg.judgment_path)
    target = next(
        i for i in active_items(store)
        if i.stability != JudgmentStability.constitutional
    )
    # update
    prop = JudgmentProposal(
        id=ids.judgment_proposal_id(), action=ProposalAction.update,
        target_judgment_id=target.id, expected_revision_id=target.current_revision_id,
        proposed_item={
            "kind": target.kind.value, "statement": "Updated statement",
            "domain": target.domain, "strength": target.strength,
            "confidence": 0.8, "stability": target.stability.value,
        },
        reason="edit", confidence=0.8, status=ProposalStatus.pending, created_at=now_iso(),
    )
    store.insert_judgment_proposal(prop)
    token = preview_proposal(store, prop.id)["preview_token"]
    approve_proposal(store, prop.id, preview_token=token)
    assert store.get_judgment_item(target.id).statement == "Updated statement"
    old_rev = target.current_revision_id
    hist = store.get_judgment_revision(old_rev)
    assert hist is not None
    assert hist.payload["statement"] != "Updated statement"

    # weaken
    head = store.get_judgment_item(target.id)
    prop2 = JudgmentProposal(
        id=ids.judgment_proposal_id(), action=ProposalAction.weaken,
        target_judgment_id=head.id, expected_revision_id=head.current_revision_id,
        proposed_item={"strength": 0.2}, reason="weaken", confidence=0.7,
        status=ProposalStatus.pending, created_at=now_iso(),
    )
    store.insert_judgment_proposal(prop2)
    approve_proposal(store, prop2.id, preview_token=preview_proposal(store, prop2.id)["preview_token"])
    assert store.get_judgment_item(target.id).strength <= 0.2

    # deprecate
    head = store.get_judgment_item(target.id)
    prop3 = JudgmentProposal(
        id=ids.judgment_proposal_id(), action=ProposalAction.deprecate,
        target_judgment_id=head.id, expected_revision_id=head.current_revision_id,
        proposed_item={}, reason="retire", confidence=0.9,
        status=ProposalStatus.pending, created_at=now_iso(),
    )
    store.insert_judgment_proposal(prop3)
    approve_proposal(store, prop3.id, preview_token=preview_proposal(store, prop3.id)["preview_token"])
    assert store.get_judgment_item(target.id).status == JudgmentStatus.deprecated


def _make_rich_item(**kw) -> JudgmentItem:
    now = now_iso()
    base = dict(
        id=ids.judgment_id(), kind=JudgmentKind.principle,
        statement="Prefer reversible infrastructure choices",
        description="rich item",
        domain="technical", persona="developer",
        scope=JudgmentScope(
            domains=["technical"], projects=["proj_twin"],
            project_stages=["mvp"], audiences=["internal"],
        ),
        strength=0.9, confidence=0.85,
        stability=JudgmentStability.stable,
        status=JudgmentStatus.active,
        created_at=now, updated_at=now, approved_at=now, approved_by="user",
        provenance=JudgmentProvenance(
            source="explicit_user_statement", memory_ids=["mem_1"],
        ),
        exceptions=[JudgmentException(
            id=ids.judgment_exception_id(),
            condition="client imposed legacy requirement",
            effect=ExceptionEffect.reduce_strength, value=0.4,
        )],
        tradeoff="simplicity vs capability", lean=0.3,
        metadata={"origin": "test"},
    )
    base.update(kw)
    return JudgmentItem(**base)


def test_update_partial_preserves_unmentioned_fields(store, cfg):
    item, _ = commit_new_item(store, _make_rich_item())
    create_version(store, reason="rich")
    before = store.get_judgment_item(item.id)
    prop = JudgmentProposal(
        id=ids.judgment_proposal_id(), action=ProposalAction.update,
        target_judgment_id=before.id, expected_revision_id=before.current_revision_id,
        proposed_item={"statement": "Prefer reversible choices — clarified"},
        reason="wording", confidence=0.9, status=ProposalStatus.pending, created_at=now_iso(),
    )
    store.insert_judgment_proposal(prop)
    approve_proposal(
        store, prop.id,
        preview_token=preview_proposal(store, prop.id)["preview_token"],
    )
    after = store.get_judgment_item(item.id)
    assert after.statement == "Prefer reversible choices — clarified"
    assert after.strength == before.strength
    assert after.confidence == before.confidence
    assert after.stability == before.stability
    assert after.persona == before.persona
    assert after.scope.model_dump() == before.scope.model_dump()
    assert after.provenance.model_dump() == before.provenance.model_dump()
    assert [e.model_dump() for e in after.exceptions] == [
        e.model_dump() for e in before.exceptions
    ]
    assert after.tradeoff == before.tradeoff
    assert after.lean == before.lean
    assert after.metadata == before.metadata
    assert after.kind == before.kind
    assert after.domain == before.domain
    hist = store.get_judgment_revision(before.current_revision_id)
    assert hist.payload["statement"] == before.statement


def test_update_explicit_clear_exceptions(store, cfg):
    item, _ = commit_new_item(store, _make_rich_item())
    create_version(store, reason="rich2")
    head = store.get_judgment_item(item.id)
    assert head.exceptions
    prop = JudgmentProposal(
        id=ids.judgment_proposal_id(), action=ProposalAction.update,
        target_judgment_id=head.id, expected_revision_id=head.current_revision_id,
        proposed_item={"exceptions": []},
        reason="clear exceptions", confidence=0.9,
        status=ProposalStatus.pending, created_at=now_iso(),
    )
    store.insert_judgment_proposal(prop)
    approve_proposal(
        store, prop.id,
        preview_token=preview_proposal(store, prop.id)["preview_token"],
    )
    after = store.get_judgment_item(item.id)
    assert after.exceptions == []
    assert after.statement == head.statement
    assert after.scope.model_dump() == head.scope.model_dump()


def test_constitutional_target_mutations_require_confirm(store, cfg):
    item, _ = commit_new_item(store, _make_rich_item(
        statement="Never mix intimate context with work",
        kind=JudgmentKind.constraint,
        stability=JudgmentStability.constitutional,
        strength=1.0, confidence=0.95,
    ))
    create_version(store, reason="constitutional")
    head = store.get_judgment_item(item.id)

    cases = [
        (ProposalAction.weaken, {"strength": 0.2}),
        (ProposalAction.strengthen, {"strength": 1.0}),
        (ProposalAction.update, {"statement": "Never mix intimate context with work."}),
        (ProposalAction.add_exception, {
            "exception": {
                "id": ids.judgment_exception_id(),
                "condition": "explicit user override for one case",
                "effect": "disable",
            },
        }),
        (ProposalAction.deprecate, {}),
    ]
    for action, proposed in cases:
        head = store.get_judgment_item(item.id)
        prop = JudgmentProposal(
            id=ids.judgment_proposal_id(), action=action,
            target_judgment_id=head.id, expected_revision_id=head.current_revision_id,
            proposed_item=proposed, reason=f"try {action.value}",
            confidence=0.9, status=ProposalStatus.pending, created_at=now_iso(),
        )
        store.insert_judgment_proposal(prop)
        token = preview_proposal(store, prop.id)["preview_token"]
        with pytest.raises(ValueError, match="constitutional"):
            approve_proposal(store, prop.id, preview_token=token)
        # same token works with confirmation
        approve_proposal(
            store, prop.id, preview_token=token, confirm_constitutional=True,
        )
        # refresh for next mutation on possibly changed head
        if action == ProposalAction.deprecate:
            assert store.get_judgment_item(item.id).status == JudgmentStatus.deprecated
            break


def test_stability_change_changes_preview_token(store, cfg):
    item, _ = commit_new_item(store, _make_rich_item())
    create_version(store, reason="stable item")
    head = store.get_judgment_item(item.id)
    prop = JudgmentProposal(
        id=ids.judgment_proposal_id(), action=ProposalAction.update,
        target_judgment_id=head.id, expected_revision_id=head.current_revision_id,
        proposed_item={"statement": head.statement},
        reason="stability edit", confidence=0.9,
        status=ProposalStatus.pending, created_at=now_iso(),
    )
    store.insert_judgment_proposal(prop)
    t1 = preview_proposal(store, prop.id)["preview_token"]
    t2 = preview_proposal(
        store, prop.id, edits={"stability": "evolving"},
    )["preview_token"]
    assert t1 != t2
    preview = preview_proposal(store, prop.id, edits={"stability": "evolving"})
    assert preview["signed_payload"]["target_stability"] == "stable"
    assert preview["signed_payload"]["new_stability"] == "evolving"
    assert preview["signed_payload"]["stability_change"] is True

def test_approve_rollback_on_fault(store, cfg, embedder):
    mem = _mem(store, embedder, type="preference", title="t", summary="Prefere X.")
    prop = propose_from_memory(store, mem.id)
    token = preview_proposal(store, prop.id)["preview_token"]
    real = store.insert_judgment_version
    calls = {"n": 0}

    def boom(version):
        calls["n"] += 1
        raise RuntimeError("injected version failure")

    store.insert_judgment_version = boom  # type: ignore[method-assign]
    try:
        with pytest.raises(RuntimeError, match="injected"):
            approve_proposal(store, prop.id, preview_token=token)
    finally:
        store.insert_judgment_version = real  # type: ignore[method-assign]
    assert store.get_judgment_proposal(prop.id).status == ProposalStatus.pending
    # no orphan active preference from this proposal
    assert not any("Prefere X" in i.statement for i in active_items(store))


def test_project_scoped_requires_project_id(store, cfg):
    now = now_iso()
    item, _ = commit_new_item(store, JudgmentItem(
        id=ids.judgment_id(), kind=JudgmentKind.preference,
        statement="Twin-only stack preference",
        domain="technical",
        scope=JudgmentScope(domains=["technical"], projects=["proj_twin"]),
        status=JudgmentStatus.active, created_at=now, updated_at=now,
        approved_at=now, approved_by="user", strength=0.8, confidence=0.9,
    ))
    create_version(store, reason="scoped")
    pack_no = applicable_pack(store, domain="technical", persist_snapshot=False)
    assert item.id not in [i["id"] for i in pack_no["applicable_judgments"]]
    pack_yes = applicable_pack(
        store, domain="technical", project_id="proj_twin", persist_snapshot=False,
    )
    assert item.id in [i["id"] for i in pack_yes["applicable_judgments"]]


def test_audience_scope(store, cfg):
    now = now_iso()
    item, _ = commit_new_item(store, JudgmentItem(
        id=ids.judgment_id(), kind=JudgmentKind.preference,
        statement="Use warm diplomatic tone",
        domain="assistant_preferences",
        scope=JudgmentScope(domains=["assistant_preferences"], audiences=["external"]),
        status=JudgmentStatus.active, created_at=now, updated_at=now,
        approved_at=now, approved_by="user",
    ))
    create_version(store, reason="audience")
    pack = applicable_pack(
        store, domain="assistant_preferences", audience="internal", persist_snapshot=False,
    )
    assert item.id not in [i["id"] for i in pack["applicable_judgments"]]
    pack2 = applicable_pack(
        store, domain="assistant_preferences", audience="external", persist_snapshot=False,
    )
    assert item.id in [i["id"] for i in pack2["applicable_judgments"]]


def test_exception_disable_removes_constraint(store, cfg):
    now = now_iso()
    item, _ = commit_new_item(store, JudgmentItem(
        id=ids.judgment_id(), kind=JudgmentKind.constraint,
        statement="Never send PII to cloud",
        domain="technical",
        status=JudgmentStatus.active, created_at=now, updated_at=now,
        approved_at=now, approved_by="user", strength=1.0, confidence=1.0,
        stability=JudgmentStability.constitutional,
        exceptions=[JudgmentException(
            id=ids.judgment_exception_id(),
            condition="client imposed cloud requirement",
            effect=ExceptionEffect.disable,
            reason="external mandate",
        )],
    ))
    create_version(store, reason="constraint+exc")
    pack = applicable_pack(
        store, domain="technical",
        query="client imposed cloud requirement for storage",
        persist_snapshot=False,
    )
    assert item.id not in [i["id"] for i in pack["hard_constraints"]]
    assert any(r["disabled"] for r in pack["applied_revisions"] if r["judgment_id"] == item.id)


def test_require_confirmation_blocks_recommendation(store, cfg):
    now = now_iso()
    commit_new_item(store, JudgmentItem(
        id=ids.judgment_id(), kind=JudgmentKind.heuristic,
        statement="Be direct always",
        domain="assistant_preferences",
        scope=JudgmentScope(domains=["assistant_preferences"]),
        status=JudgmentStatus.active, created_at=now, updated_at=now,
        approved_at=now, approved_by="user",
        exceptions=[JudgmentException(
            id=ids.judgment_exception_id(),
            condition="external candidate rejection email",
            effect=ExceptionEffect.require_confirmation,
        )],
    ))
    create_version(store, reason="confirm exc")
    result = evaluate(
        store, "Write external candidate rejection email",
        domain="assistant_preferences",
        options=["direct", "diplomatic"],
        persist=False,
    )
    assert result["outcome"] == "requires_confirmation"
    assert result["recommendation"] is None


def test_abstention_without_signal(store, cfg):
    now = now_iso()
    commit_new_item(store, JudgmentItem(
        id=ids.judgment_id(), kind=JudgmentKind.preference,
        statement="Prefer green UI accents",
        domain="assistant_preferences",
        scope=JudgmentScope(domains=["assistant_preferences"]),
        status=JudgmentStatus.active, created_at=now, updated_at=now,
        approved_at=now, approved_by="user",
    ))
    create_version(store, reason="unrelated pref")
    result = evaluate(
        store, "PostgreSQL vs Neo4j?",
        domain="technical",
        options=["PostgreSQL", "Neo4j"],
        persist=False,
    )
    assert result["outcome"] == "insufficient_judgment_signal"
    assert result["recommendation"] is None


def test_counterfactual_has_no_side_effects(store, cfg):
    apply_yaml_import(store, cfg.judgment_path)
    before_snaps = store._j_fetchall("SELECT id FROM judgment_snapshots", ())
    before_traces = store._j_fetchall("SELECT id FROM judgment_traces", ())
    items = active_items(store)
    counterfactual(
        store, "PostgreSQL vs Neo4j?", items[0].id,
        domain="technical", options=["PostgreSQL", "Neo4j"],
    )
    after_snaps = store._j_fetchall("SELECT id FROM judgment_snapshots", ())
    after_traces = store._j_fetchall("SELECT id FROM judgment_traces", ())
    assert len(after_snaps) == len(before_snaps)
    assert len(after_traces) == len(before_traces)


def test_restore_preserves_historical_revisions(store, cfg):
    r1 = apply_yaml_import(store, cfg.judgment_path)
    v1 = store.get_judgment_version(r1["version_id"])
    hist = [store.get_judgment_revision(rid) for rid in v1.revision_ids]
    assert all(h is not None for h in hist)
    payloads = [h.payload["statement"] for h in hist]

    now = now_iso()
    extra, _ = commit_new_item(store, JudgmentItem(
        id=ids.judgment_id(), kind=JudgmentKind.preference,
        statement="Prefer dark themes", domain="assistant_preferences",
        status=JudgmentStatus.active, created_at=now, updated_at=now,
        approved_at=now, approved_by="user",
    ))
    create_version(store, reason="theme")
    restore_version(store, v1.id)
    # original revision payloads unchanged
    for rid, stmt in zip(v1.revision_ids, payloads):
        assert store.get_judgment_revision(rid).payload["statement"] == stmt
    assert store.get_judgment_item(extra.id).status == JudgmentStatus.deprecated


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
        reason="explicit", confidence=0.95,
        status=ProposalStatus.pending, created_at=now_iso(),
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


def test_promote_creates_proposal(store, cfg, embedder):
    from twin.cognize.stance_engine.profile import promote_memory
    mem = _mem(store, embedder, type="preference", title="ADRs",
               summary="Prefere ADRs no repo.")
    section = promote_memory(cfg.judgment_path, mem, store=store)
    assert section.startswith("proposal:")


def test_simulate_persists_trace(store, cfg):
    apply_yaml_import(store, cfg.judgment_path)
    result = simulate(
        store, "Should Twin migrate from PostgreSQL to Neo4j?",
        domain="technical",
        options=["PostgreSQL", "Neo4j", "custom graph engine"],
    )
    assert result["snapshot_id"]
    assert result.get("trace_id") or result["outcome"] == "insufficient_judgment_signal"


def test_context_pack_structured(store, cfg, embedder):
    apply_yaml_import(store, cfg.judgment_path)
    pack = build_context_pack(
        store, cfg, embedder, "architecture choice",
        target_domain="technical", task_profile="architecture",
        access=_cli_access(store),
    )
    assert "Judgment" in pack.context_pack


def test_resolve_conflict_requires_operation_or_dismiss(store, cfg):
    apply_yaml_import(store, cfg.judgment_path)
    detect_judgment_conflicts(store)
    open_ = store.list_judgment_conflicts(status="open")
    if not open_:
        pytest.skip("no opposing pair in default yaml")
    with pytest.raises(ValueError, match="resolution_operation_id|dismiss"):
        resolve_conflict(store, open_[0].id, resolution="narrow scope")
    resolve_conflict(store, open_[0].id, resolution="dismiss", dismiss=True)
    assert store.get_judgment_conflict(open_[0].id).status.value in ("dismissed", "resolved")
