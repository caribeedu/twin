"""Revision outcomes, vault isolation, commit preview, backfill, review."""

from __future__ import annotations

from twin.cognize.commit import (
    CommitError,
    commit_narrative,
    preview_commit_token,
    resynthesize_narrative,
)
from twin.cognize.migrate import backfill_from_memories, claim_to_provisional
from twin.cognize.models import (
    EpistemicStatus,
    Interpretation,
    InterpretationStatus,
    NarrativeRevisionDecision,
    NarrativeRevisionOutcome,
    Reflection,
    ReflectionStatus,
    Situation,
    SurpriseLevel,
)
from twin.cognize.orchestrator import (
    CognizeStage,
    StageResult,
    StageRunStatus,
    clear_cognize_stage_overrides,
    run_cognize,
    set_cognize_stage_override,
)
from twin.interfaces.commands import cognize_cmd
from twin.store.models import StoreClaim, ClaimStatus, ClaimType, Sensitivity
from twin.sense.sensory.percept import Percept
from twin import ids


def _base_overrides(**extra):
    clear_cognize_stage_overrides()

    def salience(store, cfg, ctx, *, dry_run):
        ctx["kept_percepts"] = list(ctx["percepts"])
        return StageResult(CognizeStage.salience, StageRunStatus.ok, {"kept": len(ctx["kept_percepts"])})

    def situate(store, cfg, ctx, *, dry_run):
        sit = Situation(
            vault_id=ctx["vault_id"],
            percept_ids=[p.id for p in ctx["kept_percepts"]],
            summary="sit",
        )
        ctx["situation"] = sit
        if not dry_run:
            store.upsert_situation(sit)
        return StageResult(CognizeStage.situate, StageRunStatus.ok, {"situations": 1})

    def raise_ref(store, cfg, ctx, *, dry_run):
        refs = [
            Reflection(
                vault_id=ctx["vault_id"],
                text="Q1?",
                status=ReflectionStatus.open,
                situation_ids=[ctx["situation"].id],
                evidence_ids=[p.id for p in ctx["kept_percepts"]],
            ),
            Reflection(
                vault_id=ctx["vault_id"],
                text="Q2?",
                status=ReflectionStatus.open,
                situation_ids=[ctx["situation"].id],
                evidence_ids=[p.id for p in ctx["kept_percepts"]],
            ),
        ]
        ctx["reflections"] = refs
        if not dry_run:
            for r in refs:
                store.upsert_reflection(r)
        return StageResult(CognizeStage.raise_reflections, StageRunStatus.ok, {"reflections": 2})

    def form_intp(store, cfg, ctx, *, dry_run):
        intps = [
            Interpretation(
                vault_id=ctx["vault_id"],
                explanation="winner",
                status=InterpretationStatus.competing,
                reflection_ids=[ctx["reflections"][0].id],
                evidence_ids=[p.id for p in ctx["kept_percepts"]],
            ),
            Interpretation(
                vault_id=ctx["vault_id"],
                explanation="dissent",
                status=InterpretationStatus.competing,
                reflection_ids=[ctx["reflections"][0].id],
                evidence_ids=[p.id for p in ctx["kept_percepts"]],
            ),
        ]
        ctx["interpretations"] = intps
        if not dry_run:
            for i in intps:
                store.upsert_interpretation(i)
        return StageResult(
            CognizeStage.form_interpretations, StageRunStatus.ok, {"interpretations": 2}
        )

    def noop(stage):
        def _fn(store, cfg, ctx, *, dry_run):
            return StageResult(stage, StageRunStatus.ok, {"relations": 0})
        return _fn

    def nrev(store, cfg, ctx, *, dry_run):
        outcome = extra.get("outcome", NarrativeRevisionOutcome.integrate)
        d = NarrativeRevisionDecision(
            vault_id=ctx["vault_id"],
            interpretation_ids=[i.id for i in ctx["interpretations"]],
            outcome=outcome,
            surprise=SurpriseLevel.medium,
            explanatory_delta="delta",
            retained_dissent_ids=[ctx["interpretations"][1].id],
            rationale="override",
        )
        ctx["revision"] = d
        if not dry_run:
            store.upsert_narrative_revision(d)
        return StageResult(CognizeStage.narrative_revision, StageRunStatus.ok, {"decisions": 1})

    set_cognize_stage_override(CognizeStage.salience, salience)
    set_cognize_stage_override(CognizeStage.situate, situate)
    set_cognize_stage_override(CognizeStage.raise_reflections, raise_ref)
    set_cognize_stage_override(CognizeStage.form_interpretations, form_intp)
    set_cognize_stage_override(CognizeStage.cross_reflections, noop(CognizeStage.cross_reflections))
    set_cognize_stage_override(
        CognizeStage.cross_interpretations, noop(CognizeStage.cross_interpretations)
    )
    set_cognize_stage_override(CognizeStage.narrative_revision, nrev)
    set_cognize_stage_override(CognizeStage.evidence_audit, noop(CognizeStage.evidence_audit))


def test_all_revision_outcomes_persist(store, cfg):
    p = Percept(
        percept_type="message",
        source_sensor="slack",
        content="x",
        metadata={"vault_id": "default"},
    )
    store.insert_percept(p)
    for outcome in NarrativeRevisionOutcome:
        _base_overrides(outcome=outcome)
        report = run_cognize(store, cfg, percept_ids=[p.id], vault_id="default")
        assert report.ok
        assert report.revision_ids
        rev = store.get_narrative_revision(report.revision_ids[0])
        assert rev.outcome is outcome
        assert rev.retained_dissent_ids
    clear_cognize_stage_overrides()


def test_cross_vault_refuse(store, cfg):
    clear_cognize_stage_overrides()
    _base_overrides()
    foreign = Percept(
        percept_type="message",
        source_sensor="slack",
        content="other vault",
        metadata={"vault_id": "vault_b"},
    )
    store.insert_percept(foreign)
    report = run_cognize(
        store, cfg, percept_ids=[foreign.id], vault_id="vault_a"
    )
    assert report.halted
    assert report.halt_reason == "cross_vault_refuse"
    clear_cognize_stage_overrides()


def test_preview_token_and_resynthesize(store):
    token = preview_commit_token(
        account="A", evidence_ids=["e1"], vault_id="default", domain="technical"
    )
    try:
        commit_narrative(
            store,
            account="A",
            vault_id="default",
            evidence_ids=["e1"],
            committed_by="u",
            domain="technical",
            preview_token="bad",
            require_preview_token=True,
        )
        assert False, "expected token mismatch"
    except CommitError:
        pass
    nar = commit_narrative(
        store,
        account="A",
        vault_id="default",
        evidence_ids=["e1"],
        committed_by="u",
        domain="technical",
        preview_token=token,
        require_preview_token=True,
    )
    store.mark_epistemic_stale(nar.epistemic_state_id, reason="t", unseen_percept_id="p2")
    assert store.get_epistemic_state(nar.epistemic_state_id).status is EpistemicStatus.stale
    updated = resynthesize_narrative(
        store,
        nar.id,
        account="A revised",
        evidence_ids=["e1", "e2"],
        committed_by="u",
    )
    assert updated.account == "A revised"
    assert store.get_epistemic_state(nar.epistemic_state_id).status is EpistemicStatus.fresh


def test_needs_review_never_narrative():
    mem = StoreClaim(
        id=ids.claim_id(),
        type=ClaimType.decision,
        title="maybe",
        summary="needs eyes",
        domain="technical",
        persona="developer",
        sensitivity=Sensitivity.internal,
        confidence=0.5,
        status=ClaimStatus.confirmed,
        needs_review=True,
    )
    kind, obj = claim_to_provisional(mem)
    assert kind == "interpretation"


def test_backfill_idempotent_and_skips_needs_review(store):
    mem = StoreClaim(
        id=ids.claim_id(),
        type=ClaimType.decision,
        title="review me",
        summary="candidate path",
        domain="technical",
        persona="developer",
        sensitivity=Sensitivity.internal,
        confidence=0.4,
        status=ClaimStatus.candidate,
        needs_review=True,
    )
    store.insert_claim(mem)
    s1 = backfill_from_memories(store, vault_id="default", dry_run=False)
    assert s1["interpretations"] >= 1
    assert s1["narratives"] == 0
    s2 = backfill_from_memories(store, vault_id="default", dry_run=False)
    assert s2["skipped"] >= 1
    assert s2["interpretations"] == 0


def test_cognize_review_surface(store, cfg):
    from types import SimpleNamespace

    ref = Reflection(vault_id="vault_general", text="Still open?", status=ReflectionStatus.open)
    store.upsert_reflection(ref)
    intp = Interpretation(
        vault_id="vault_general",
        explanation="maybe",
        status=InterpretationStatus.competing,
        evidence_ids=["e1"],
    )
    store.upsert_interpretation(intp)
    ws = SimpleNamespace(store=store, cfg=cfg)
    args = SimpleNamespace(vault="vault_general")
    data = cognize_cmd.cognize_review(ws, args)
    assert data["counts"]["open_reflections"] >= 1
    assert data["counts"]["competing_interpretations"] >= 1
