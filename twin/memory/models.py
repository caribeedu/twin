"""Memory-layer data model: Memory Items, Entities, Relations, Evidence.

(The Percept model — the input contract — lives in ``twin.sensory.percept``.)
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from twin import ids


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
    # v0.3 consolidation statuses
    merged = "merged"
    split = "split"
    archived = "archived"
    unsupported = "unsupported"
    stale = "stale"
    deleted = "deleted"


# Statuses that must not appear in default retrieval / packs.
INACTIVE_STATUSES = frozenset({
    MemoryStatus.rejected.value,
    MemoryStatus.deprecated.value,
    MemoryStatus.contradicted.value,
    MemoryStatus.merged.value,
    MemoryStatus.split.value,
    MemoryStatus.archived.value,
    MemoryStatus.unsupported.value,
    MemoryStatus.stale.value,
    MemoryStatus.deleted.value,
})


class EvidenceType(str, Enum):
    verbatim = "verbatim"
    derived = "derived"
    metadata = "metadata"
    inferred = "inferred"
    contradictory = "contradictory"


class Evidence(BaseModel):
    id: str
    memory_id: str
    percept_id: str
    quote: str
    evidence_type: EvidenceType = EvidenceType.verbatim
    directness: float = 1.0
    source_trust: float = 0.8
    independence_group: Optional[str] = None
    supports: bool = True
    span_start: Optional[int] = None
    span_end: Optional[int] = None
    artifact_id: Optional[str] = None


class Entity(BaseModel):
    id: str
    name: str
    entity_type: str = "generic"  # person | project | system | tool | team | generic
    created_at: str = ""
    aliases: list[str] = Field(default_factory=list)
    canonical_id: Optional[str] = None  # points to canonical entity when this is an alias


class Relation(BaseModel):
    id: str
    subject_id: str  # entity id or memory id
    predicate: str  # works_on | prefers | affects | produced | supersedes | contradicts | merged_into | split_into | ...
    object_id: str  # entity id or memory id
    memory_id: Optional[str] = None  # memory that asserted this relation
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    created_at: str = ""


class CanonicalClaim(BaseModel):
    """Propositional core of a memory — separate from human/LLM wording."""

    subject: str = ""
    predicate: str = ""
    object: str = ""
    qualifiers: dict[str, Any] = Field(default_factory=dict)


class ExtractorVersion(BaseModel):
    extractor: str = ""
    model: str = ""
    prompt_version: str = ""
    schema_version: str = "2"
    created_at: str = ""


class DetectionSignal(BaseModel):
    """v0.7 conservative lexical detection — explicitly NOT a memory.

    The heuristic detector may say "this span looks like it could contain a
    decision/task" to prioritize a Percept, seed a review queue or drive
    operational metrics. It may NOT establish a memory type, domain, entity,
    title, summary or cognitive confidence — only a cognitive interpreter can.
    A DetectionSignal therefore carries a *candidate category*, the source
    span that triggered it and a detection confidence, and never becomes a
    MemoryItem on its own."""

    id: str
    percept_id: str
    kind: str                 # candidate category (decision|task|…) — a hint, not a type
    span: str                 # the source span that triggered detection
    reason: str = ""
    confidence: float = 0.0   # detection confidence, NOT cognitive confidence
    created_at: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class PerceptInterpretation(BaseModel):
    """v0.7 execution record of interpreting one Percept.

    Lightweight, metadata-only: it tracks *whether and how* a Percept was
    understood (status + model/prompt/schema versions + attempt count), not
    the interpreted semantics themselves — those still flow into memories and
    evidence. It exists so the pipeline can tell three states apart that the
    old "no evidence yet" heuristic conflated: never interpreted, interpreted
    and legitimately empty, and deferred because no model was available.

    ``content_hash`` pins the record to the exact Percept content, so an
    edited Percept is re-interpreted instead of being considered done."""

    percept_id: str
    # interpretation execution status:
    #   interpreted | empty | deferred | error
    # pipeline/governance terminals that did NOT interpret:
    #   quarantined | heuristic_detection | not_attempted
    status: str = "deferred"
    # distinguishes a service outage from a Percept-specific failure so a
    # prolonged outage never consumes a Percept's retry budget:
    #   unavailable | transient | input | schema | permanent | ""
    failure_class: str = ""
    # whether the cognitive interpreter was actually invoked (False for
    # quarantine and heuristic detection — those never interpret)
    interpretation_attempted: bool = False
    # a terminal record is never retried (poison input exhausted its budget)
    terminal: bool = False
    # earliest time this Percept should be retried (backoff); "" = immediately
    next_attempt_at: str = ""
    interpreter: str = ""
    model: str = ""
    prompt_version: str = ""
    schema_version: str = ""
    attempts: int = 0
    items_catalogued: int = 0
    unresolved_count: int = 0
    detail: str = ""
    content_hash: str = ""
    # per-stage counters for observability (§v0.7 metrics): emitted, grounded,
    # ungrounded, policy_dropped, deduplicated, inserted, review_bound, invalid
    stage_counts: dict[str, int] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


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
    # v0.3 quality / review fields (recomputable analysis lives partly here)
    review_priority: float = 0.0
    quality_score: float = 0.0
    quality_flags: list[str] = Field(default_factory=list)
    impact: str = "medium"  # low | medium | high
    reviewed_at: Optional[str] = None
    review_batch_id: Optional[str] = None
    canonical_claim: Optional[CanonicalClaim] = None
    extractor_version: Optional[ExtractorVersion] = None
    last_reconciled_at: Optional[str] = None
    retrieval_count: int = 0
    last_retrieved_at: Optional[str] = None
    deleted_at: Optional[str] = None
    deletion_reason: Optional[str] = None


class FindingType(str, Enum):
    possible_duplicate = "possible_duplicate"
    near_duplicate = "near_duplicate"
    exact_duplicate = "exact_duplicate"
    possible_conflict = "possible_conflict"
    possible_supersedence = "possible_supersedence"
    possible_merge = "possible_merge"
    possible_split = "possible_split"
    possibly_related = "possibly_related"
    low_specificity = "low_specificity"
    weak_evidence = "weak_evidence"
    high_future_reuse = "high_future_reuse"
    source_risk = "source_risk"
    temporal_succession = "temporal_succession"
    scope_difference = "scope_difference"
    unsupported = "unsupported"
    stale = "stale"
    evidence_mapping_required = "evidence_mapping_required"
    cross_source_temporal_conflict = "cross_source_temporal_conflict"


class DuplicateGroup(BaseModel):
    id: str
    memory_ids: list[str] = Field(default_factory=list)
    canonical_memory_id: str = ""
    reason: str = ""
    created_at: str = ""


class SuggestedAction(str, Enum):
    confirm = "confirm"
    reject = "reject"
    edit = "edit"
    merge = "merge"
    split = "split"
    supersede = "supersede"
    contradict = "contradict"
    defer = "defer"
    archive = "archive"
    request_more_evidence = "request_more_evidence"
    attach_evidence = "attach_evidence"
    none = "none"


class FindingStatus(str, Enum):
    open = "open"
    resolved = "resolved"
    dismissed = "dismissed"
    obsolete = "obsolete"


class ReviewFinding(BaseModel):
    id: str
    memory_id: str
    type: FindingType
    related_memory_id: Optional[str] = None
    confidence: float = 0.5
    reason: str = ""
    suggested_action: SuggestedAction = SuggestedAction.none
    requires_human_review: bool = True
    status: FindingStatus = FindingStatus.open
    resolved: bool = False  # legacy mirror of status != open
    created_at: str = ""
    resolved_at: Optional[str] = None
    resolution_operation_id: Optional[str] = None
    analyzer_version: str = "quality-v1"
    metadata: dict[str, Any] = Field(default_factory=dict)


class QualityReport(BaseModel):
    memory_id: str
    quality_score: float
    review_priority: float
    impact: str = "medium"
    issues: list[ReviewFinding] = Field(default_factory=list)
    suggested_action: SuggestedAction = SuggestedAction.none
    requires_human_review: bool = False
    quality_flags: list[str] = Field(default_factory=list)
    neighbors: list[str] = Field(default_factory=list)


class Artifact(BaseModel):
    """Persisted source object — file, commit, PR, transcript, message, …"""

    id: str
    kind: str  # git_commit | document | meeting | slack_message | email | ...
    external_id: Optional[str] = None
    source_system: str = "local"
    uri: Optional[str] = None
    content_hash: Optional[str] = None
    occurred_at: Optional[str] = None
    created_at: str = ""
    deleted_at: Optional[str] = None
    deletion_reason: Optional[str] = None
    content_destroyed: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewBatch(BaseModel):
    id: str
    name: str
    query: dict[str, Any] = Field(default_factory=dict)
    memory_ids: list[str] = Field(default_factory=list)
    created_at: str = ""
    completed_at: Optional[str] = None
    progress_total: int = 0
    progress_reviewed: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryOperation(BaseModel):
    """Auditable, optionally reversible curation mutation."""

    id: str
    operation: str
    actor: str = "user"
    at: str = ""
    inputs: list[str] = Field(default_factory=list)
    output: Optional[str] = None
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    undoable: bool = True
    undone_at: Optional[str] = None


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
    paused = "paused"
    completed = "completed"   # closed
    abandoned = "abandoned"
    archived = "archived"


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
    judgment_snapshot_id: Optional[str] = None  # pack snapshot that influenced this session
    # v0.5 authorization context captured at session start
    principal_id: Optional[str] = None
    persona: str = "individual"
    purpose: str = "task_execution"
    audience: str = "self"
    tool_id: Optional[str] = None
    privacy_decision_ids: list[str] = Field(default_factory=list)
    grant_ids: list[str] = Field(default_factory=list)
    policy_snapshot_id: Optional[str] = None


class HostSessionBinding(BaseModel):
    """Link an external host conversation occurrence to a CognitiveSession.

    ``occurrence`` allows the same ``external_session_id`` to start again
    after Stop without mixing conversations. Security fields are frozen at
    bind time and must not widen silently on refresh.
    """

    id: str = Field(default_factory=ids.host_session_binding_id)
    host_type: str                          # claude-code | codex | ...
    external_session_id: str
    occurrence: int = 1
    cognitive_session_id: str
    project_id: Optional[str] = None
    principal_id: Optional[str] = None
    vault_id: Optional[str] = None
    domain: Optional[str] = None
    persona: str = "individual"
    purpose: str = "task_execution"
    audience: str = "self"
    task_profile: Optional[str] = None
    connector_id: Optional[str] = None
    started_at: str = ""
    ended_at: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class InterventionRecommendation(BaseModel):
    """Display-only heuristic cue — does not act on the host.

    Reasons are *possible decision reversal cues*, not proven semantic
    contradictions. May false-positive; never modifies host state.
    """

    type: str = "warning"                   # warning | info
    reason: str = ""
    urgency: str = "medium"                 # low | medium | high
    session_id: Optional[str] = None
    supported_actions: list[str] = Field(default_factory=lambda: ["display"])
    requires_confirmation: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
