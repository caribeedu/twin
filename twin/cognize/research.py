"""Research instrumentation helpers for Stage 6 surprise / explanatory_delta."""

from __future__ import annotations

from typing import Any


def list_revision_research_rows(
    store: Any,
    vault_id: str = "",
    *,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Export NarrativeRevisionDecision research fields (queryable, not Inject floor)."""
    if not hasattr(store, "list_narrative_revisions"):
        return []
    rows: list[dict[str, Any]] = []
    for rev in store.list_narrative_revisions(vault_id, limit=limit):
        rows.append({
            "id": rev.id,
            "vault_id": rev.vault_id,
            "outcome": rev.outcome.value if hasattr(rev.outcome, "value") else rev.outcome,
            "surprise": rev.surprise.value if hasattr(rev.surprise, "value") else rev.surprise,
            "explanatory_delta": rev.explanatory_delta,
            "prior_narrative_id": rev.prior_narrative_id,
            "rationale": rev.rationale,
            "created_at": rev.created_at,
        })
    return rows


def attention_score(surprise: str, outcome: str = "") -> float:
    """Metric for disagreement-vs-agreement evals (higher = more attention)."""
    base = {"low": 0.2, "medium": 0.5, "high": 1.0}.get(str(surprise), 0.5)
    boost = 0.3 if str(outcome) in ("contradict", "supersede", "branch") else 0.0
    return base + boost
