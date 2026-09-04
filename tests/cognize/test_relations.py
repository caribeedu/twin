"""Relation validation and composition types."""

from __future__ import annotations

import pytest

from twin.cognize.models import Relation, RelationAssertedBy, RelationType
from twin.cognize.relations import (
    RelationValidationError,
    coerce_relation_type,
    refuse_similarity_causal_assert,
    upsert_validated_relation,
    validate_relation,
)


def test_unknown_relation_type_rejected():
    with pytest.raises(ValueError):
        RelationType("not-a-real-type")


def test_coerce_supported_by_alias():
    assert coerce_relation_type("supported_by") is RelationType.supports
    assert coerce_relation_type("reinforces") is RelationType.supports
    assert coerce_relation_type("supports") is RelationType.supports
    assert coerce_relation_type("depends_on") is RelationType.depends_on
    assert coerce_relation_type("same-as") is RelationType.same_as
    # Unknown LLM invention must not abort the run.
    assert coerce_relation_type("not-a-real-type") is RelationType.related


def test_same_originating_decision_requires_llm():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Relation(
            vault_id="v",
            from_id="a",
            to_id="b",
            type=RelationType.same_originating_decision,
            asserted_by=RelationAssertedBy.human,
            rationale="nope",
        )


def test_same_originating_decision_allows_test_flag(store):
    rel = Relation(
        vault_id="vault_a",
        from_id="e1",
        to_id="e2",
        type=RelationType.same_originating_decision,
        asserted_by=RelationAssertedBy.test,
        rationale="fixture",
    )
    upsert_validated_relation(store, rel, allow_test_asserted=True)
    rows = store.list_relations(
        "vault_a", rel_type=RelationType.same_originating_decision.value
    )
    assert len(rows) == 1


def test_similarity_cannot_assert_same_originating_decision():
    with pytest.raises(RelationValidationError):
        refuse_similarity_causal_assert(
            similarity_score=0.97,
            proposed_type=RelationType.same_originating_decision,
        )


def test_narrative_composition_relation_types(store):
    for rtype in (
        RelationType.part_of,
        RelationType.continues,
        RelationType.supersedes,
    ):
        rel = Relation(
            vault_id="vault_a",
            from_id="nar_1",
            to_id="nar_2",
            type=rtype,
            asserted_by=RelationAssertedBy.llm,
            rationale="composition",
        )
        store.upsert_relation(rel)
    assert len(store.list_relations("vault_a")) >= 3
