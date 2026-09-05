"""First-class judgment model — versioned, scoped, user-governed.

Judgment is not memory. Twin may observe and propose; only the user
constitutes durable judgment. Revisions are immutable; versions point at
revision IDs, never at mutable heads alone.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class JudgmentKind(str, Enum):
    preference = "preference"
    belief = "belief"
    principle = "principle"
    value = "value"
    heuristic = "heuristic"
    constraint = "constraint"


class JudgmentStability(str, Enum):
    temporary = "temporary"
    evolving = "evolving"
    stable = "stable"
    constitutional = "constitutional"


class JudgmentStatus(str, Enum):
    """Lifecycle of the logical judgment identity (human-driven only)."""
    candidate = "candidate"
    active = "active"
    rejected = "rejected"
    superseded = "superseded"
    deprecated = "deprecated"


class ProposalAction(str, Enum):
    create = "create"
    update = "update"
    weaken = "weaken"
    strengthen = "strengthen"
    supersede = "supersede"
    add_exception = "add_exception"
    deprecate = "deprecate"


class ProposalStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    deferred = "deferred"
    expired = "expired"


class ConflictType(str, Enum):
    exception = "exception"
    drift = "drift"
    explicit_contradiction = "explicit_contradiction"
    scope_mismatch = "scope_mismatch"
    judgment_vs_judgment = "judgment_vs_judgment"


class ConflictStatus(str, Enum):
    open = "open"
    resolved = "resolved"
    dismissed = "dismissed"


class ExceptionEffect(str, Enum):
    disable = "disable"
    reduce_strength = "reduce_strength"
    replace_with = "replace_with"
    require_confirmation = "require_confirmation"


class JudgmentScope(BaseModel):
    projects: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    personas: list[str] = Field(default_factory=list)
    task_profiles: list[str] = Field(default_factory=list)
    audiences: list[str] = Field(default_factory=list)
    clients: list[str] = Field(default_factory=list)
    project_stages: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)


class JudgmentContext(BaseModel):
    """All dimensions considered when selecting applicable judgment."""
    domain: str = "technical"
    persona: str = "individual"
    project_id: Optional[str] = None
    task_profile: str = "general"
    audience: Optional[str] = None
    client: Optional[str] = None
    project_stage: Optional[str] = None
    conditions: list[str] = Field(default_factory=list)
    query: str = ""


class JudgmentProvenance(BaseModel):
    claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    session_ids: list[str] = Field(default_factory=list)
    narrative_ids: list[str] = Field(default_factory=list)
    source: str = "manual"
    twin_influenced: bool = False
    independence_weight: float = Field(default=1.0, ge=0.0, le=1.0)


class JudgmentException(BaseModel):
    id: str
    condition: str = ""
    # Structured match when available (preferred over loose text tokens).
    match: dict[str, Any] = Field(default_factory=dict)
    effect: ExceptionEffect = ExceptionEffect.reduce_strength
    value: float = Field(default=0.5, ge=0.0, le=1.0)
    replace_with_revision_id: Optional[str] = None
    reason: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)


class JudgmentItem(BaseModel):
    """Logical judgment identity + current head revision content.

    Content fields mirror the current revision for convenience. Historical
    fidelity comes from ``JudgmentRevision`` rows referenced by versions.
    """
    id: str
    kind: JudgmentKind
    statement: str = Field(min_length=1)
    description: str = ""
    domain: str = "technical"
    persona: str = "individual"
    scope: JudgmentScope = Field(default_factory=JudgmentScope)
    strength: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    stability: JudgmentStability = JudgmentStability.evolving
    status: JudgmentStatus = JudgmentStatus.candidate
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    approved_at: Optional[str] = None
    approved_by: Optional[str] = None
    provenance: JudgmentProvenance = Field(default_factory=JudgmentProvenance)
    exceptions: list[JudgmentException] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)
    supersedes: Optional[str] = None
    tradeoff: Optional[str] = None
    lean: Optional[float] = Field(default=None, ge=-1.0, le=1.0)
    current_revision_id: Optional[str] = None
    revision: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)


class JudgmentRevision(BaseModel):
    """Immutable content snapshot of a judgment at a point in time."""
    id: str
    judgment_id: str
    revision: int
    payload: dict[str, Any]
    created_at: str
    actor: str = "user"
    reason: str = ""


class AppliedRevisionRef(BaseModel):
    judgment_id: str
    revision_id: str
    effective_strength: float = Field(ge=0.0, le=1.0)
    disabled: bool = False
    requires_confirmation: bool = False
    exception_ids: list[str] = Field(default_factory=list)
    replacement_revision_id: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)


class JudgmentProposal(BaseModel):
    id: str
    action: ProposalAction
    target_judgment_id: Optional[str] = None
    expected_revision_id: Optional[str] = None
    proposed_item: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    supporting_claim_ids: list[str] = Field(default_factory=list)
    contradicting_claim_ids: list[str] = Field(default_factory=list)
    support_count: int = 0
    contradiction_count: int = 0
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    scope: dict[str, Any] = Field(default_factory=dict)
    status: ProposalStatus = ProposalStatus.pending
    created_at: str = ""
    expires_at: Optional[str] = None
    preview_token: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class JudgmentVersion(BaseModel):
    id: str
    version: int
    created_at: str
    reason: str = ""
    parent_version_id: Optional[str] = None
    active: bool = True
    # Immutable composition — revision IDs, not mutable heads.
    revision_ids: list[str] = Field(default_factory=list)
    item_ids: list[str] = Field(default_factory=list)  # logical ids for convenience
    actor: str = "user"
    metadata: dict[str, Any] = Field(default_factory=dict)


class JudgmentSnapshot(BaseModel):
    id: str
    judgment_version_id: str
    item_ids: list[str] = Field(default_factory=list)
    applied_revisions: list[AppliedRevisionRef] = Field(default_factory=list)
    target_domain: str = "technical"
    persona: str = "individual"
    task_profile: str = "general"
    project_id: Optional[str] = None
    audience: Optional[str] = None
    client: Optional[str] = None
    project_stage: Optional[str] = None
    application_engine: str = "judgment-app-v2"
    created_at: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class JudgmentConflict(BaseModel):
    id: str
    judgment_id: str
    claim_ids: list[str] = Field(default_factory=list)
    other_judgment_id: Optional[str] = None
    type: ConflictType
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    status: ConflictStatus = ConflictStatus.open
    suggested_resolution: str = ""
    reason: str = ""
    created_at: str = ""
    resolved_at: Optional[str] = None
    resolution_operation_id: Optional[str] = None
    proposal_id: Optional[str] = None
    analyzer_version: str = "conflict-v1"
    evidence_fingerprint: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class AppliedJudgmentEffect(BaseModel):
    judgment_id: str
    revision_id: Optional[str] = None
    effect: str
    option: Optional[str] = None
    weight: float = 0.0
    reason: str = ""


class JudgmentTrace(BaseModel):
    id: str
    query: str
    snapshot_id: str
    applied_items: list[AppliedJudgmentEffect] = Field(default_factory=list)
    blocked_options: list[str] = Field(default_factory=list)
    exceptions_used: list[str] = Field(default_factory=list)
    result: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


KIND_PRECEDENCE = {
    JudgmentKind.constraint: 0,
    JudgmentKind.principle: 1,
    JudgmentKind.value: 2,
    JudgmentKind.heuristic: 3,
    JudgmentKind.belief: 4,
    JudgmentKind.preference: 5,
}

DURABLE_KINDS = frozenset({
    JudgmentKind.principle,
    JudgmentKind.value,
    JudgmentKind.constraint,
})

ACTIONS_REQUIRING_TARGET = frozenset({
    ProposalAction.update,
    ProposalAction.weaken,
    ProposalAction.strengthen,
    ProposalAction.supersede,
    ProposalAction.add_exception,
    ProposalAction.deprecate,
})
