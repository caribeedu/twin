"""First-class judgment model — versioned, scoped, user-governed.

Judgment is not memory: memory records what happened; judgment records how
that should influence future decisions. Only the user constitutes durable
judgment; Twin may observe and propose.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


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
    candidate = "candidate"
    active = "active"
    rejected = "rejected"
    superseded = "superseded"
    deprecated = "deprecated"
    conflicted = "conflicted"


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


class JudgmentProvenance(BaseModel):
    memory_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    session_ids: list[str] = Field(default_factory=list)
    source: str = "manual"  # explicit_user_statement | repeated_behavior | promoted_memory | manual | yaml_import
    twin_influenced: bool = False
    independence_weight: float = 1.0


class JudgmentException(BaseModel):
    id: str
    condition: str
    effect: ExceptionEffect = ExceptionEffect.reduce_strength
    value: float = 0.5
    reason: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)


class JudgmentItem(BaseModel):
    id: str
    kind: JudgmentKind
    statement: str
    description: str = ""
    domain: str = "technical"
    persona: str = "individual"
    scope: JudgmentScope = Field(default_factory=JudgmentScope)
    strength: float = 0.5
    confidence: float = 0.5
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
    lean: Optional[float] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class JudgmentProposal(BaseModel):
    id: str
    action: ProposalAction
    target_judgment_id: Optional[str] = None
    proposed_item: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    supporting_memory_ids: list[str] = Field(default_factory=list)
    contradicting_memory_ids: list[str] = Field(default_factory=list)
    support_count: int = 0
    contradiction_count: int = 0
    confidence: float = 0.5
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
    item_ids: list[str] = Field(default_factory=list)
    actor: str = "user"
    metadata: dict[str, Any] = Field(default_factory=dict)


class JudgmentSnapshot(BaseModel):
    id: str
    judgment_version_id: str
    item_ids: list[str] = Field(default_factory=list)
    target_domain: str = "technical"
    persona: str = "individual"
    task_profile: str = "general"
    project_id: Optional[str] = None
    created_at: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class JudgmentConflict(BaseModel):
    id: str
    judgment_id: str
    memory_ids: list[str] = Field(default_factory=list)
    other_judgment_id: Optional[str] = None
    type: ConflictType
    confidence: float = 0.5
    status: ConflictStatus = ConflictStatus.open
    suggested_resolution: str = ""
    reason: str = ""
    created_at: str = ""
    resolved_at: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AppliedJudgmentEffect(BaseModel):
    judgment_id: str
    effect: str  # favored_option | blocked_option | reduced_strength | explained
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


# Precedence for application (higher index = lower priority).
KIND_PRECEDENCE = {
    JudgmentKind.constraint: 0,
    JudgmentKind.principle: 1,
    JudgmentKind.value: 2,  # explains, does not command
    JudgmentKind.heuristic: 3,
    JudgmentKind.belief: 4,
    JudgmentKind.preference: 5,
}

DURABLE_KINDS = frozenset({
    JudgmentKind.principle,
    JudgmentKind.value,
    JudgmentKind.constraint,
})
