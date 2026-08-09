"""Twin v2 Cognize entity contracts.

These types are the schema root for Situations, Reflections, Interpretations,
Relations, Narratives, EpistemicState, Evidence anchors, Traces, and Narrative
Revision decisions. Understanding is *emergent* — there is no Understanding
table or model.

See ``docs/v2.md`` §2.2 / §10 and ``docs/GLOSSARY.md``.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from twin import ids
from twin.clock import now_iso


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SituationStatus(str, Enum):
    working = "working"
    concluded = "concluded"


class ReflectionStatus(str, Enum):
    open = "open"
    answered = "answered"
    superseded = "superseded"
    faded = "faded"


class InterpretationStatus(str, Enum):
    competing = "competing"
    rejected = "rejected"
    merged = "merged"
    superseded = "superseded"
    committed = "committed"


class RelationType(str, Enum):
    same_as = "same-as"
    related = "related"
    supports = "supports"
    contradicts = "contradicts"
    depends_on = "depends-on"
    supersedes = "supersedes"
    part_of = "part-of"
    continues = "continues"
    same_originating_decision = "same_originating_decision"


class RelationAssertedBy(str, Enum):
    llm = "llm"
    human = "human"
    test = "test"  # CI / stage overrides only


class NarrativeGrain(str, Enum):
    episode = "episode"
    arc = "arc"
    domain = "domain"


class NarrativeStatus(str, Enum):
    committed = "committed"
    remarkable = "remarkable"
    ordinary = "ordinary"
    fading = "fading"
    archived = "archived"


class EpistemicStatus(str, Enum):
    fresh = "fresh"
    stale = "stale"
    superseded = "superseded"
    tombstoned = "tombstoned"


class StanceStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    active = "active"
    deprecated = "deprecated"


class NarrativeRevisionOutcome(str, Enum):
    integrate = "integrate"
    branch = "branch"
    contradict = "contradict"
    supersede = "supersede"
    keep_separate = "keep_separate"
    defer = "defer"


class SurpriseLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


class Situation(BaseModel):
    """Working cluster of percepts for one happening (not the durable product)."""

    id: str = Field(default_factory=ids.situation_id)
    vault_id: str
    percept_ids: list[str] = Field(default_factory=list)
    status: SituationStatus = SituationStatus.working
    domain: str = ""
    project_id: Optional[str] = None
    summary: str = ""
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Reflection(BaseModel):
    """Open epistemic gap Cognize is holding."""

    id: str = Field(default_factory=ids.reflection_id)
    vault_id: str
    text: str
    status: ReflectionStatus = ReflectionStatus.open
    situation_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    superseded_by: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Interpretation(BaseModel):
    """Competing candidate explanation — not a user-query answer."""

    id: str = Field(default_factory=ids.interpretation_id)
    vault_id: str
    explanation: str
    status: InterpretationStatus = InterpretationStatus.competing
    reflection_ids: list[str] = Field(default_factory=list)
    situation_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Relation(BaseModel):
    """Typed Cognize edge. Causal types require LLM (or explicit test) assertion."""

    id: str = Field(default_factory=ids.cognize_relation_id)
    vault_id: str
    from_id: str
    to_id: str
    type: RelationType
    rationale: str = ""
    asserted_by: RelationAssertedBy = RelationAssertedBy.llm
    model_id: str = ""
    prompt_version: str = ""
    schema_version: str = "cognize-relation-v1"
    created_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _causal_requires_llm_or_test(self) -> Relation:
        if self.type is RelationType.same_originating_decision:
            if self.asserted_by not in (RelationAssertedBy.llm, RelationAssertedBy.test):
                raise ValueError(
                    "same_originating_decision must be asserted_by=llm "
                    "(or test for CI overrides); embeddings alone are forbidden"
                )
        return self


class EpistemicState(BaseModel):
    """Freshness + evidence-set metadata. No stored confidence scalar."""

    id: str = Field(default_factory=ids.epistemic_state_id)
    synthesized_at: str = Field(default_factory=now_iso)
    freshness_boundary: Optional[str] = None
    unseen_since: list[str] = Field(default_factory=list)
    status: EpistemicStatus = EpistemicStatus.fresh
    stale_reason: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    independence_sketch: str = ""
    updated_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def _forbid_confidence_in_metadata(cls, v: dict[str, Any]) -> dict[str, Any]:
        if "confidence" in v:
            raise ValueError(
                "EpistemicState must not store confidence; derive at read time"
            )
        return v


class Narrative(BaseModel):
    """Human-accepted, evidence-backed, revisable account."""

    id: str = Field(default_factory=ids.narrative_id)
    vault_id: str
    account: str
    grain: Optional[NarrativeGrain] = None
    status: NarrativeStatus = NarrativeStatus.committed
    epistemic_state_id: Optional[str] = None
    evidence_ids: list[str] = Field(default_factory=list)
    domain: str = ""
    persona: str = ""
    sensitivity: str = "internal"
    project_id: Optional[str] = None
    migrated_from_memory: bool = False
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    committed_by: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def _forbid_confidence(cls, v: dict[str, Any]) -> dict[str, Any]:
        if "confidence" in v:
            raise ValueError(
                "Narrative must not store confidence; use EpistemicState + read-time derive"
            )
        return v


class Stance(BaseModel):
    """Evaluative posture (public name for Judgment). Alias layer may wrap JudgmentItem."""

    id: str = Field(default_factory=ids.judgment_id)
    vault_id: str = ""
    kind: str = "heuristic"
    statement: str
    status: StanceStatus = StanceStatus.pending
    strength: float = 0.5
    domain: str = ""
    persona: str = ""
    constitutional: bool = False
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceAnchor(BaseModel):
    """Anchored percept span warranting an Interpretation or Narrative."""

    id: str = Field(default_factory=ids.evidence_anchor_id)
    vault_id: str
    percept_id: str
    quote: str
    source_id: str = ""
    observed_at: Optional[str] = None
    acl_tags: list[str] = Field(default_factory=list)
    target_kind: str = ""  # interpretation | narrative
    target_id: str = ""
    weight: float = 1.0
    dissent: bool = False
    created_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Trace(BaseModel):
    """Append-only retrieval / use event for accessibility policy."""

    id: str = Field(default_factory=ids.trace_id)
    vault_id: str = ""
    event_kind: str  # pack_serve | search_hit | review_open | ...
    resource_kind: str = ""  # narrative | reflection | ...
    resource_id: str = ""
    session_id: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NarrativeRevisionDecision(BaseModel):
    """Stage 6 output — see docs/v2.md §10."""

    id: str = Field(default_factory=ids.narrative_revision_id)
    vault_id: str = ""
    prior_narrative_id: Optional[str] = None
    interpretation_ids: list[str] = Field(default_factory=list)
    outcome: NarrativeRevisionOutcome
    surprise: SurpriseLevel = SurpriseLevel.medium
    explanatory_delta: str = ""
    retained_dissent_ids: list[str] = Field(default_factory=list)
    same_originating_decision_hints: list[str] = Field(default_factory=list)
    rationale: str = ""
    created_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Read-time helpers (no persistence of confidence)
# ---------------------------------------------------------------------------


class IndependenceSummary(BaseModel):
    observation_count: int
    independent_origin_count: int
    display: str


class DerivedConfidence(BaseModel):
    """Display-only confidence — never write back onto Narrative/EpistemicState."""

    label: str  # e.g. low | medium | high | uncertain
    score: Optional[float] = None  # optional 0..1 for UI bars; not authoritative storage
    rationale: str = ""
    independence: IndependenceSummary


def collapse_independent_origins(
    evidence_ids: list[str],
    same_originating_decision_groups: list[set[str]] | list[list[str]],
) -> IndependenceSummary:
    """Collapse evidence ids that share a same_originating_decision Relation."""
    if not evidence_ids:
        return IndependenceSummary(
            observation_count=0,
            independent_origin_count=0,
            display="0 observations, 0 independent origins",
        )
    parent: dict[str, str] = {e: e for e in evidence_ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for group in same_originating_decision_groups:
        members = [e for e in group if e in parent]
        for i in range(1, len(members)):
            union(members[0], members[i])

    roots = {find(e) for e in evidence_ids}
    k = len(roots)
    n = len(evidence_ids)
    return IndependenceSummary(
        observation_count=n,
        independent_origin_count=k,
        display=f"{n} observations, {k} independent origin{'s' if k != 1 else ''}",
    )


def derive_confidence(
    *,
    evidence_ids: list[str],
    same_originating_decision_groups: list[set[str]] | list[list[str]] | None = None,
    support_count: int = 0,
    contradict_count: int = 0,
    epistemic_status: EpistemicStatus = EpistemicStatus.fresh,
) -> DerivedConfidence:
    """Read-time confidence display. Agreement among echoes must not inflate origins."""
    indep = collapse_independent_origins(
        evidence_ids, same_originating_decision_groups or []
    )
    if epistemic_status is EpistemicStatus.stale:
        return DerivedConfidence(
            label="uncertain",
            score=None,
            rationale="narrative is stale; re-synthesize before trusting",
            independence=indep,
        )
    if epistemic_status is EpistemicStatus.tombstoned:
        return DerivedConfidence(
            label="unavailable",
            score=0.0,
            rationale="tombstoned",
            independence=indep,
        )
    if contradict_count > 0:
        label = "contested"
        score = max(0.2, 0.5 - 0.1 * contradict_count)
        rationale = "contradicting evidence present; retain dissent"
    elif indep.independent_origin_count <= 1 and indep.observation_count > 1:
        label = "low"
        score = 0.35
        rationale = "multiple observations collapse to one independent origin"
    elif indep.independent_origin_count >= 2 and contradict_count == 0:
        label = "medium" if support_count < 3 else "high"
        score = 0.55 if label == "medium" else 0.75
        rationale = "multiple independent origins without open contradiction"
    else:
        label = "low"
        score = 0.4
        rationale = "sparse or single-origin evidence"
    return DerivedConfidence(
        label=label,
        score=score,
        rationale=rationale,
        independence=indep,
    )
