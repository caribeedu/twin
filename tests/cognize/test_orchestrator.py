"""Orchestrator tests using stage overrides (no network)."""

from __future__ import annotations

from twin.cognize.models import (
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
from twin.sensory.percept import Percept


def _install_overrides():
    clear_cognize_stage_overrides()

    def salience(store, cfg, ctx, *, dry_run):
        ctx["kept_percepts"] = list(ctx["percepts"])
        return StageResult(CognizeStage.salience, StageRunStatus.ok, {"kept": len(ctx["kept_percepts"])})

    def situate(store, cfg, ctx, *, dry_run):
        sit = Situation(
            vault_id=ctx["vault_id"],
            percept_ids=[p.id for p in ctx["kept_percepts"]],
            summary="test situation",
        )
        ctx["situation"] = sit
        if not dry_run:
            store.upsert_situation(sit)
        return StageResult(CognizeStage.situate, StageRunStatus.ok, {"situations": 1})

    def raise_ref(store, cfg, ctx, *, dry_run):
        ref = Reflection(
            vault_id=ctx["vault_id"],
            text="Is Feature A still a launch blocker?",
            status=ReflectionStatus.open,
            situation_ids=[ctx["situation"].id],
            evidence_ids=[p.id for p in ctx["kept_percepts"]],
        )
        ctx["reflections"] = [ref]
        if not dry_run:
            store.upsert_reflection(ref)
        return StageResult(CognizeStage.raise_reflections, StageRunStatus.ok, {"reflections": 1})

    def form_intp(store, cfg, ctx, *, dry_run):
        intp = Interpretation(
            vault_id=ctx["vault_id"],
            explanation="Feature A was the blocker; PR merged it.",
            status=InterpretationStatus.competing,
            reflection_ids=[ctx["reflections"][0].id],
            evidence_ids=[p.id for p in ctx["kept_percepts"]],
        )
        ctx["interpretations"] = [intp]
        if not dry_run:
            store.upsert_interpretation(intp)
        return StageResult(CognizeStage.form_interpretations, StageRunStatus.ok, {"interpretations": 1})

    def cross_r(store, cfg, ctx, *, dry_run):
        return StageResult(CognizeStage.cross_reflections, StageRunStatus.ok, {"relations": 0})

    def cross_i(store, cfg, ctx, *, dry_run):
        return StageResult(CognizeStage.cross_interpretations, StageRunStatus.ok, {"relations": 0})

    def nrev(store, cfg, ctx, *, dry_run):
        d = NarrativeRevisionDecision(
            vault_id=ctx["vault_id"],
            interpretation_ids=[ctx["interpretations"][0].id],
            outcome=NarrativeRevisionOutcome.integrate,
            surprise=SurpriseLevel.low,
            explanatory_delta="first account",
            rationale="override",
        )
        ctx["revision"] = d
        if not dry_run:
            store.upsert_narrative_revision(d)
        return StageResult(CognizeStage.narrative_revision, StageRunStatus.ok, {"decisions": 1})

    def audit(store, cfg, ctx, *, dry_run):
        return StageResult(CognizeStage.evidence_audit, StageRunStatus.ok, {"relations": 0})

    set_cognize_stage_override(CognizeStage.salience, salience)
    set_cognize_stage_override(CognizeStage.situate, situate)
    set_cognize_stage_override(CognizeStage.raise_reflections, raise_ref)
    set_cognize_stage_override(CognizeStage.form_interpretations, form_intp)
    set_cognize_stage_override(CognizeStage.cross_reflections, cross_r)
    set_cognize_stage_override(CognizeStage.cross_interpretations, cross_i)
    set_cognize_stage_override(CognizeStage.narrative_revision, nrev)
    set_cognize_stage_override(CognizeStage.evidence_audit, audit)


def test_run_cognize_with_overrides(store, cfg):
    _install_overrides()
    try:
        p = Percept(
            percept_type="message",
            source_sensor="test",
            content="Feature A blocks launch",
            metadata={"vault_id": "default", "domain": "technical"},
        )
        store.insert_percept(p)
        report = run_cognize(store, cfg, percept_ids=[p.id])
        assert report.ok
        assert not report.halted
        assert report.reflection_ids
        assert report.interpretation_ids
        assert store.get_reflection(report.reflection_ids[0]) is not None
    finally:
        clear_cognize_stage_overrides()


def test_cognize_halts_without_llm_or_override(store, cfg, monkeypatch):
    clear_cognize_stage_overrides()
    monkeypatch.setattr(cfg, "extractor", "heuristic")
    p = Percept(
        percept_type="message",
        source_sensor="test",
        content="x",
        metadata={"vault_id": "default"},
    )
    store.insert_percept(p)
    report = run_cognize(store, cfg, percept_ids=[p.id], chat_reachable=False)
    assert report.halted
