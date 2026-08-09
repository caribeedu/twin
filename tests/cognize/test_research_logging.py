"""Research logging: surprise / explanatory_delta persist and export."""

from __future__ import annotations

from twin.cognize.models import (
    NarrativeRevisionDecision,
    NarrativeRevisionOutcome,
    SurpriseLevel,
)
from twin.cognize.research import list_revision_research_rows


def test_narrative_revision_research_fields_persist(store):
    rev = NarrativeRevisionDecision(
        vault_id="default",
        outcome=NarrativeRevisionOutcome.contradict,
        surprise=SurpriseLevel.high,
        explanatory_delta="new PR flips the prior account",
        rationale="disagreement",
        prior_narrative_id="nar_x",
    )
    store.upsert_narrative_revision(rev)
    loaded = store.get_narrative_revision(rev.id)
    assert loaded is not None
    assert loaded.surprise is SurpriseLevel.high
    assert loaded.explanatory_delta.startswith("new PR")

    rows = list_revision_research_rows(store, "default")
    assert any(r["id"] == rev.id and r["surprise"] == "high" for r in rows)
