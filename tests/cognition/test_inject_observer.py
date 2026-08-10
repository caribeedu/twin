"""Inject Observer stub + stance draft from Narrative."""

from __future__ import annotations

from twin.inject.inject_observer import (
    NoOpInjectObserver,
    get_inject_observer,
    inject_observer_enabled,
)
from twin.cognize.commit import commit_narrative
from twin.cognize.stance_engine.proposals import propose_from_narrative
from twin.cognize.stance_engine.models import ProposalStatus


def test_inject_observer_default_noop(monkeypatch, store):
    monkeypatch.delenv("TWIN_INJECT_OBSERVER", raising=False)
    assert inject_observer_enabled() is False
    obs = get_inject_observer()
    assert isinstance(obs, NoOpInjectObserver)
    before = len(store.list_narratives("default")) if hasattr(store, "list_narratives") else 0
    decision = obs.observe_turn(store, text="hello", session_id="s1")
    assert decision.inject is False
    after = len(store.list_narratives("default")) if hasattr(store, "list_narratives") else 0
    assert after == before


def test_propose_from_narrative_pending(store):
    nar = commit_narrative(
        store,
        account="Prefer reversible infrastructure choices",
        vault_id="default",
        evidence_ids=["ev_1"],
        committed_by="tester",
        domain="technical",
    )
    # commit already drafts; ensure pending
    proposals = [
        p for p in store.list_judgment_proposals()
        if (p.metadata or {}).get("narrative_id") == nar.id
    ]
    assert proposals
    assert all(p.status is ProposalStatus.pending for p in proposals)

    # explicit call is idempotent-ish (creates another pending draft)
    p2 = propose_from_narrative(store, nar.id)
    assert p2 is not None
    assert p2.status is ProposalStatus.pending
    assert p2.proposed_item["provenance"]["source"] == "narrative_stance"
