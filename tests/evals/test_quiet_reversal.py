"""Eval: quiet reversal path (§9.3 #2)."""

from __future__ import annotations

from twin.cognize.commit import commit_narrative
from twin.cognize.models import EpistemicStatus, Reflection, ReflectionStatus
from twin.sensory.percept import Percept, SourceClass


def test_eval_quiet_reversal_marks_stale_and_raises_gap(store):
    """Quiet meeting percept (little follow-up) must stale Narrative;
    Cognize leaves an open Reflection challenger rather than relying on TTL.
    """
    nar = commit_narrative(
        store,
        account="We are shipping Feature A next week",
        vault_id="default",
        evidence_ids=["ev_old"],
        committed_by="eval",
        domain="technical",
    )
    assert store.get_epistemic_state(nar.epistemic_state_id).status is EpistemicStatus.fresh

    quiet = Percept(
        percept_type="meeting_transcript",
        source_sensor="meeting",
        content="Quick sync: Feature A cancelled; no further discussion.",
        metadata={"vault_id": "default", "domain": "technical", "quiet_reversal": True},
    )
    assert quiet.source_class is SourceClass.meeting
    store.insert_percept(quiet)

    eps = store.get_epistemic_state(nar.epistemic_state_id)
    assert eps.status is EpistemicStatus.stale
    assert quiet.id in eps.unseen_since

    # Challenger gap (deterministic fixture — Stage 6 override stand-in)
    store.upsert_reflection(
        Reflection(
            vault_id="default",
            text="Quiet meeting reversed Feature A plan — needs revision",
            status=ReflectionStatus.open,
            evidence_ids=[quiet.id],
            metadata={"domain": "technical", "kind": "quiet_reversal"},
        )
    )
    open_refs = store.list_open_reflections("default")
    assert any("reversed" in r.text.lower() for r in open_refs)
    # Prior Narrative retained
    assert store.get_narrative(nar.id) is not None
