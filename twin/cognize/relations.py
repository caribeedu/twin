"""Relation validation for causal types."""

from __future__ import annotations

from typing import Any, Optional

from twin.cognize.models import Relation, RelationAssertedBy, RelationType


class RelationValidationError(ValueError):
    pass


CAUSAL_TYPES = frozenset(
    {
        RelationType.same_originating_decision,
        RelationType.depends_on,
        RelationType.supersedes,
        RelationType.continues,
        RelationType.part_of,
    }
)


def validate_relation(
    rel: Relation,
    *,
    allow_test_asserted: bool = False,
) -> Relation:
    if rel.type is RelationType.same_originating_decision:
        if rel.asserted_by is RelationAssertedBy.llm:
            return rel
        if allow_test_asserted or rel.asserted_by is RelationAssertedBy.test:
            return rel
        raise RelationValidationError(
            "same_originating_decision requires asserted_by=llm "
            "(embeddings/similarity cannot assert causal independence)"
        )
    return rel


def upsert_validated_relation(
    store: Any,
    rel: Relation,
    *,
    allow_test_asserted: bool = False,
) -> str:
    validate_relation(rel, allow_test_asserted=allow_test_asserted)
    return store.upsert_relation(rel)


def refuse_similarity_causal_assert(
    *,
    similarity_score: Optional[float] = None,
    proposed_type: RelationType | str,
) -> None:
    rtype = (
        proposed_type
        if isinstance(proposed_type, RelationType)
        else RelationType(str(proposed_type))
    )
    if rtype is RelationType.same_originating_decision and similarity_score is not None:
        raise RelationValidationError(
            "refusing same_originating_decision from similarity score alone"
        )
