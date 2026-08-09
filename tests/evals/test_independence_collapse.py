"""Independence collapse eval (§9.3 #3)."""

from __future__ import annotations

from twin.cognize.commit import commit_narrative
from twin.cognize.models import (
    Relation,
    RelationAssertedBy,
    RelationType,
    derive_confidence,
)
from twin.cognition.context_pack import build_context_pack
from twin.memory.embeddings import HashEmbedder


def test_eval_independence_collapse_correlated_echoes(store, cfg):
    evidence = ["ev_meet", "ev_roadmap", "ev_cal", "ev_commit"]
    nar = commit_narrative(
        store,
        account="Ship Feature A this quarter",
        vault_id="default",
        evidence_ids=evidence,
        committed_by="eval",
        domain="technical",
    )
    # Four echoes of one decision
    for a, b in zip(evidence, evidence[1:]):
        store.upsert_relation(
            Relation(
                vault_id="default",
                from_id=a,
                to_id=b,
                type=RelationType.same_originating_decision,
                asserted_by=RelationAssertedBy.test,
                rationale="same product decision",
            )
        )

    pack = build_context_pack(
        store, cfg, HashEmbedder(),
        query="What did we decide about Feature A?",
        target_domain="technical",
    )
    derived = pack.derived_confidence[nar.id]
    assert derived["independence"]["independent_origin_count"] == 1
    assert derived["independence"]["observation_count"] == 4
    assert "1 independent origin" in derived["independence"]["display"]
    assert derived["label"] == "low"
    assert derived.get("derived") is True


def test_eval_independence_counterexample_independent_contradiction(store, cfg):
    evidence = ["ev_a", "ev_b"]
    nar = commit_narrative(
        store,
        account="Plan is Feature A",
        vault_id="default",
        evidence_ids=evidence,
        committed_by="eval",
        domain="technical",
    )
    store.upsert_relation(
        Relation(
            vault_id="default",
            from_id="ev_b",
            to_id="ev_a",
            type=RelationType.contradicts,
            asserted_by=RelationAssertedBy.test,
            rationale="independent contradicting source",
        )
    )
    pack = build_context_pack(
        store, cfg, HashEmbedder(),
        query="Feature plan",
        target_domain="technical",
    )
    derived = pack.derived_confidence[nar.id]
    assert derived["independence"]["independent_origin_count"] == 2
    assert derived["label"] == "contested"
    assert derived["contradicts"] >= 1


def test_derive_confidence_table():
    d = derive_confidence(
        evidence_ids=["a", "b", "c", "d"],
        same_originating_decision_groups=[{"a", "b", "c", "d"}],
    )
    assert d.independence.independent_origin_count == 1
    assert d.label == "low"
