"""Cognize store CRUD + vault isolation tests."""

from __future__ import annotations

from twin.cognize.models import (
    EpistemicState,
    EpistemicStatus,
    Narrative,
    Relation,
    RelationAssertedBy,
    RelationType,
    Situation,
)


def test_situation_narrative_round_trip(store):
    sit = Situation(vault_id="vault_a", percept_ids=["p1"], summary="blocker")
    store.upsert_situation(sit)
    got = store.get_situation(sit.id)
    assert got is not None
    assert got.summary == "blocker"

    eps = EpistemicState(status=EpistemicStatus.fresh, evidence_ids=["e1"])
    store.upsert_epistemic_state(eps)
    nar = Narrative(
        vault_id="vault_a",
        account="Feature A unblocked launch",
        epistemic_state_id=eps.id,
        evidence_ids=["e1"],
        domain="technical",
        committed_by="user",
    )
    store.upsert_narrative(nar)
    loaded = store.get_narrative(nar.id)
    assert loaded is not None
    assert loaded.account.startswith("Feature A")
    assert store.get_epistemic_state(eps.id).status is EpistemicStatus.fresh


def test_vault_isolation_narratives(store):
    a = Narrative(vault_id="vault_a", account="A only", committed_by="u")
    b = Narrative(vault_id="vault_b", account="B only", committed_by="u")
    store.upsert_narrative(a)
    store.upsert_narrative(b)
    assert [n.id for n in store.list_narratives("vault_a")] == [a.id]
    assert [n.id for n in store.list_narratives("vault_b")] == [b.id]


def test_mark_epistemic_stale_without_llm(store):
    eps = EpistemicState(status=EpistemicStatus.fresh)
    store.upsert_epistemic_state(eps)
    updated = store.mark_epistemic_stale(
        eps.id, reason="new percept in domain", unseen_percept_id="perc_1"
    )
    assert updated is not None
    assert updated.status is EpistemicStatus.stale
    assert "perc_1" in updated.unseen_since
    assert store.get_epistemic_state(eps.id).status is EpistemicStatus.stale


def test_relation_same_originating_decision_persists(store):
    rel = Relation(
        vault_id="vault_a",
        from_id="e1",
        to_id="e2",
        type=RelationType.same_originating_decision,
        asserted_by=RelationAssertedBy.test,
        rationale="fixture",
    )
    store.upsert_relation(rel)
    rows = store.list_relations(
        "vault_a", rel_type=RelationType.same_originating_decision.value
    )
    assert len(rows) == 1
    assert rows[0].from_id == "e1"
