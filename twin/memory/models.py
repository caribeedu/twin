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
    percept_ids: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)  # entity names (resolved to ids in store)
