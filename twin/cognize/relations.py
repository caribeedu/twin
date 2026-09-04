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

# LLM / legacy aliases → canonical RelationType values.
_RELATION_TYPE_ALIASES: dict[str, RelationType] = {
    "supported_by": RelationType.supports,
    "supportedby": RelationType.supports,
    "support": RelationType.supports,
    "supporting": RelationType.supports,
    "supported": RelationType.supports,
    "reinforces": RelationType.supports,
    "reinforce": RelationType.supports,
    "reinforcing": RelationType.supports,
    "backed_by": RelationType.supports,
    "evidences": RelationType.supports,
    "depends_on": RelationType.depends_on,
    "dependson": RelationType.depends_on,
    "depends": RelationType.depends_on,
    "same_as": RelationType.same_as,
    "sameas": RelationType.same_as,
    "part_of": RelationType.part_of,
    "partof": RelationType.part_of,
    "related_to": RelationType.related,
    "relatedto": RelationType.related,
    "contradict": RelationType.contradicts,
    "contradiction": RelationType.contradicts,
    "supersede": RelationType.supersedes,
    "continue": RelationType.continues,
    "continues_from": RelationType.continues,
}


def coerce_relation_type(
    raw: RelationType | str | None,
    *,
    default: RelationType = RelationType.related,
) -> RelationType:
    """Map LLM / legacy labels onto ``RelationType`` (e.g. supported_by → supports).

    Unknown labels fall back to ``default`` so a single invented enum never
    aborts an entire Cognize run after partial entities were already written.
    """
    if isinstance(raw, RelationType):
        return raw
    s = str(raw or "").strip()
    if not s:
        return default
    try:
        return RelationType(s)
    except ValueError:
        pass
    key = s.lower().replace(" ", "_").replace("-", "_")
    if key in _RELATION_TYPE_ALIASES:
        return _RELATION_TYPE_ALIASES[key]
    for rt in RelationType:
        if rt.name == key or rt.value.replace("-", "_") == key:
            return rt
    return default


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
    rtype = coerce_relation_type(proposed_type)
    if rtype is RelationType.same_originating_decision and similarity_score is not None:
        raise RelationValidationError(
            "refusing same_originating_decision from similarity score alone"
        )
