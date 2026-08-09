"""Cognize entity contract tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from twin.cognize.models import (
    EpistemicState,
    Narrative,
    NarrativeRevisionDecision,
    NarrativeRevisionOutcome,
    Relation,
    RelationAssertedBy,
    RelationType,
    Situation,
    collapse_independent_origins,
    derive_confidence,
    EpistemicStatus,
)


def test_situation_round_trip():
    s = Situation(vault_id="vault_a", percept_ids=["p1", "p2"], summary="launch blocker")
    data = s.model_dump()
    s2 = Situation.model_validate(data)
    assert s2.id == s.id
    assert s2.vault_id == "vault_a"
    assert s2.id.startswith("sit_")


def test_relation_rejects_unknown_type():
    with pytest.raises(ValidationError):
        Relation(
            vault_id="v",
            from_id="a",
            to_id="b",
            type="similarity",  # type: ignore[arg-type]
        )


def test_same_originating_decision_requires_llm_or_test():
    with pytest.raises(ValidationError, match="same_originating_decision"):
        Relation(
            vault_id="v",
            from_id="e1",
            to_id="e2",
            type=RelationType.same_originating_decision,
            asserted_by=RelationAssertedBy.human,
            rationale="nope",
        )
    ok = Relation(
        vault_id="v",
        from_id="e1",
        to_id="e2",
        type=RelationType.same_originating_decision,
        asserted_by=RelationAssertedBy.llm,
        rationale="one upstream call",
    )
    assert ok.type is RelationType.same_originating_decision


def test_narrative_revision_outcomes():
    d = NarrativeRevisionDecision(
        outcome=NarrativeRevisionOutcome.supersede,
        interpretation_ids=["intp_1"],
        retained_dissent_ids=["intp_2"],
        surprise="high",
        explanatory_delta="prior direction no longer explains merge of B",
    )
    assert d.outcome is NarrativeRevisionOutcome.supersede
    assert "intp_2" in d.retained_dissent_ids


def test_epistemic_state_forbids_confidence_metadata():
    with pytest.raises(ValidationError, match="confidence"):
        EpistemicState(metadata={"confidence": 0.9})


def test_narrative_forbids_confidence_metadata():
    with pytest.raises(ValidationError, match="confidence"):
        Narrative(vault_id="v", account="x", metadata={"confidence": 0.5})


def test_independence_collapse_four_echoes_one_origin():
    evid = ["e1", "e2", "e3", "e4"]
    summary = collapse_independent_origins(evid, [{"e1", "e2", "e3", "e4"}])
    assert summary.observation_count == 4
    assert summary.independent_origin_count == 1
    assert summary.display == "4 observations, 1 independent origin"


def test_derive_confidence_does_not_inflate_echoes():
    evid = ["e1", "e2", "e3", "e4"]
    derived = derive_confidence(
        evidence_ids=evid,
        same_originating_decision_groups=[evid],
        support_count=4,
    )
    assert derived.independence.independent_origin_count == 1
    assert derived.label == "low"


def test_derive_confidence_stale():
    derived = derive_confidence(
        evidence_ids=["e1"],
        epistemic_status=EpistemicStatus.stale,
    )
    assert derived.label == "uncertain"
    assert derived.score is None


def test_json_schema_exportable():
    schema = Narrative.model_json_schema()
    assert "account" in schema["properties"]
    assert "confidence" not in schema["properties"]
