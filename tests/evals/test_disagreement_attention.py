"""Eval: disagreement vs agreement attention (§9.3 #4)."""

from __future__ import annotations

from twin.cognize.models import (
    NarrativeRevisionDecision,
    NarrativeRevisionOutcome,
    SurpriseLevel,
)
from twin.cognize.research import attention_score


def test_eval_disagreement_attention_beats_echo_agreement():
    """Metric: attention_score(surprise, outcome) — documented in RESEARCH.md.

    Control: three agreeing echoes → low surprise / integrate.
    Treatment: single contradicting artifact → high surprise / contradict.
    """
    echo = NarrativeRevisionDecision(
        vault_id="default",
        outcome=NarrativeRevisionOutcome.integrate,
        surprise=SurpriseLevel.low,
        explanatory_delta="echoes of same decision",
        rationale="three agreeing channels collapse",
    )
    disagree = NarrativeRevisionDecision(
        vault_id="default",
        outcome=NarrativeRevisionOutcome.contradict,
        surprise=SurpriseLevel.high,
        explanatory_delta="PR for Feature B vs Narrative Feature A",
        rationale="single contradicting artifact",
    )
    assert attention_score(
        disagree.surprise.value, disagree.outcome.value
    ) > attention_score(echo.surprise.value, echo.outcome.value)
