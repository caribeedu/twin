"""Memory-layer data model: Memory Items, Entities, Relations, Evidence.

(The Percept model — the input contract — lives in ``twin.sensory.percept``.)
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    event = "event"
    fact = "fact"
    decision = "decision"
    preference = "preference"
    belief = "belief"
    task = "task"
    procedure = "procedure"
    relationship = "relationship"
    communication_act = "communication_act"
    constraint = "constraint"


class Sensitivity(str, Enum):
    public = "public"
    internal = "internal"
    private = "private"
    restricted = "restricted"


class MemoryStatus(str, Enum):
    candidate = "candidate"
    confirmed = "confirmed"
    rejected = "rejected"
    deprecated = "deprecated"
    contradicted = "contradicted"


class Evidence(BaseModel):
    id: str
    memory_id: str
    percept_id: str
    quote: str


class Entity(BaseModel):
    id: str
    name: str
    entity_type: str = "generic"  # person | project | system | tool | team | generic
    created_at: str = ""


class Relation(BaseModel):
    id: str
    subject_id: str  # entity id or memory id
    predicate: str  # works_on | prefers | affects | produced | supersedes | contradicts | ...
    object_id: str  # entity id or memory id
    memory_id: Optional[str] = None  # memory that asserted this relation
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    created_at: str = ""


class MemoryItem(BaseModel):
    id: str
    type: MemoryType
    title: str
    summary: str
    domain: str = "technical"
    persona: str = "individual"
    sensitivity: Sensitivity = Sensitivity.internal
    confidence: float = 0.5
    status: MemoryStatus = MemoryStatus.candidate
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)  # type-specific fields
    needs_review: bool = False
    review_reason: Optional[str] = None
    project_id: Optional[str] = None
    percept_ids: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)  # entity names (resolved to ids in store)


class TaskProfile(str, Enum):
    general = "general"
    coding = "coding"
    architecture = "architecture"
    debugging = "debugging"
    writing = "writing"
    planning = "planning"
    review = "review"
    meeting_prep = "meeting_prep"


class FeedbackVerdict(str, Enum):
    useful = "useful"
    partially_useful = "partially_useful"
    irrelevant = "irrelevant"
    incorrect = "incorrect"
    missing_context = "missing_context"
    privacy_overblock = "privacy_overblock"
    privacy_underblock = "privacy_underblock"


class Project(BaseModel):
    """A first-class cognitive unit: everything the system knows converges
    on projects — decisions, constraints, sessions, percepts and people."""

    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    repos: list[str] = Field(default_factory=list)  # repo names/paths/urls
    goals: list[str] = Field(default_factory=list)
    milestones: list[dict[str, Any]] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    status: str = "active"  # active | paused | done
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionStatus(str, Enum):
    active = "active"
    completed = "completed"
    abandoned = "abandoned"


class ConsolidationStatus(str, Enum):
    """Whether the session's work has been turned into percepts/memories.

    Cognitive completion ("the work is done") is not the same event as
    consolidation ("twin learned from it") — a completed session can carry a
    failed consolidation that is retried without duplicating anything.
    """

    none = "none"            # not attempted yet (session still active)
    pending = "pending"      # completion committed, extraction in flight
    completed = "completed"  # summary percept stored and extracted
    failed = "failed"        # extraction failed — retryable, error recorded
    skipped = "skipped"      # nothing to consolidate (abandoned / no summary)


FEEDBACK_SCOPES = ("session", "pack", "memory")


class CognitiveSession(BaseModel):
    """One unit of real work done with an external LLM/IDE on top of twin.

    Closes the loop: context supplied → work performed → new percepts →
    candidate memories → feedback.

    ``artifacts`` and ``feedback`` live in their own store tables
    (append-only, safe under concurrent writers); they are materialized
    onto this model on read.
    """

    id: str
    client: str = "unknown"          # claude-code | cursor | claude-desktop | cli | ...
    project_id: Optional[str] = None
    domain: str = "technical"
    task_profile: str = "general"
    initial_query: str = ""
    status: SessionStatus = SessionStatus.active
    started_at: str = ""
    ended_at: Optional[str] = None
    last_activity_at: str = ""       # bumped by observe/feedback — stale detection
    supplied_memory_ids: list[str] = Field(default_factory=list)
    pack_chars: int = 0              # size of the supplied context pack
    artifacts: list[dict[str, Any]] = Field(default_factory=list)  # observed refs/notes
    created_memory_ids: list[str] = Field(default_factory=list)
    feedback: list[dict[str, Any]] = Field(default_factory=list)   # {scope, verdict, memory_id?, note, at}
    consolidation_status: ConsolidationStatus = ConsolidationStatus.none
    consolidation_error: Optional[str] = None   # error type/summary, never content
    summary_percept_id: Optional[str] = None    # deterministic idempotency anchor
