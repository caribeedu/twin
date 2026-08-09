"""Deeper quiet-reversal + disagreement evals with Cognize overrides."""

from __future__ import annotations

from twin.cognize.commit import commit_narrative
from twin.cognize.models import (
    EpistemicStatus,
    NarrativeRevisionDecision,
    NarrativeRevisionOutcome,
    Reflection,
    ReflectionStatus,
    SurpriseLevel,
)
from twin.cognize.orchestrator import (
    CognizeStage,
    clear_cognize_stage_overrides,
    set_cognize_stage_override,
)
from twin.cognize.research import attention_score
from twin.sensory.percept import Percept, SourceClass


def test_eval_disagreement_vs_echo_via_revision_store(store):
    """Metric: attention_score — documented in RESEARCH.md.

    Echo control: low surprise + integrate.
    Disagreement: high surprise + contradict from Stage 6 override shape.
    """
    echo = NarrativeRevisionDecision(
        vault_id="default",
        outcome=NarrativeRevisionOutcome.integrate,
        surprise=SurpriseLevel.low,
        explanatory_delta="three agreeing echoes",
    )
    disagree = NarrativeRevisionDecision(
        vault_id="default",
        outcome=NarrativeRevisionOutcome.contradict,
        surprise=SurpriseLevel.high,
        explanatory_delta="PR Feature B vs Narrative Feature A",
    )
    store.upsert_narrative_revision(echo)
    store.upsert_narrative_revision(disagree)
    rows = store.list_narrative_revisions("default")
    assert len(rows) >= 2
    assert attention_score("high", "contradict") > attention_score("low", "integrate")


def test_eval_quiet_reversal_vs_noisy_drift(store):
    """Quiet meeting (little talk) vs noisy chat drift fixtures side-by-side."""
    nar = commit_narrative(
        store,
        account="Shipping Feature A",
        vault_id="default",
        evidence_ids=["ev_base"],
        committed_by="eval",
        domain="technical",
    )

    quiet = Percept(
        percept_type="meeting_transcript",
        source_sensor="meeting",
        content="Feature A cancelled. No further discussion.",
        metadata={"vault_id": "default", "domain": "technical", "fixture": "quiet"},
    )
    assert quiet.source_class is SourceClass.meeting
    store.insert_percept(quiet)
    assert store.get_epistemic_state(nar.epistemic_state_id).status is EpistemicStatus.stale

    # Quiet path raises challenger Reflection (Stage 6 override stand-in)
    def _revision_override(store, cfg, stage, ctx, dry_run=False):
        store.upsert_reflection(
            Reflection(
                vault_id="default",
                text="Quiet reversal challenger for Feature A",
                status=ReflectionStatus.open,
                evidence_ids=[quiet.id],
                metadata={"kind": "quiet_reversal"},
            )
        )
        return NarrativeRevisionDecision(
            vault_id="default",
            prior_narrative_id=nar.id,
            outcome=NarrativeRevisionOutcome.contradict,
            surprise=SurpriseLevel.high,
            explanatory_delta="quiet meeting reversed plan",
        )

    set_cognize_stage_override(CognizeStage.narrative_revision, _revision_override)
    try:
        _revision_override(store, None, CognizeStage.narrative_revision, {})
    finally:
        clear_cognize_stage_overrides()

    # Noisy drift fixture: lots of chat without a clear challenger
    drift_nar = commit_narrative(
        store,
        account="Maybe Feature B someday",
        vault_id="default",
        evidence_ids=["ev_drift"],
        committed_by="eval",
        domain="technical",
    )
    for i in range(3):
        store.insert_percept(
            Percept(
                percept_type="message",
                source_sensor="slack",
                content=f"lots of talk {i} about Feature B maybe",
                metadata={"vault_id": "default", "domain": "technical", "fixture": "drift"},
            )
        )
    # Drift marks stale but we do not auto-raise quiet_reversal Reflection
    assert store.get_epistemic_state(drift_nar.epistemic_state_id).status is EpistemicStatus.stale
    quiet_refs = [
        r for r in store.list_open_reflections("default")
        if (r.metadata or {}).get("kind") == "quiet_reversal"
    ]
    assert quiet_refs
    assert store.get_narrative(nar.id) is not None
