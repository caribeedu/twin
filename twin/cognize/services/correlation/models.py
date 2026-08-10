"""Cross-source cognition models.

Connectors capture evidence; this package proposes identities, project maps,
WorkEpisodes, independence groups and conflict findings — never confirmed
Memory or Judgment.

All correlation is partitioned by ``vault_id`` — no automatic cross-vault
joins.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

from twin import ids
from twin.clock import now_iso


class IdentityStatus(str, Enum):
    candidate = "candidate"
    confirmed = "confirmed"
    rejected = "rejected"


class ProjectLinkStatus(str, Enum):
    """Lifecycle for ProjectLink.

    ``historical`` keeps provenance after a project closes without implying
    current ownership; ``rejected`` is an explicit negative decision.
    """
    candidate = "candidate"
    confirmed = "confirmed"
    historical = "historical"
    rejected = "rejected"


class ExternalIdentity(BaseModel):
    """One provider-scoped person/handle observation within a vault."""
    id: str = Field(default_factory=lambda: ids.new_id("extid"))
    provider: str
    external_id: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    source_account_id: str = ""
    vault_id: str = ""
    source_owner: str = ""
    actor_id: str = ""                  # e.g. github:caribeedu, mail:a@b.com
    linked_entity_id: Optional[str] = None
    confidence: float = 0.5
    confirmed: bool = False
    mapping_signals: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IdentityLink(BaseModel):
    """Proposed or confirmed link between two external identities / entity."""
    id: str = Field(default_factory=lambda: ids.new_id("idlink"))
    left_identity_id: str
    right_identity_id: Optional[str] = None
    entity_id: Optional[str] = None
    vault_id: str = ""                  # empty only for explicit cross-domain
    cross_domain: bool = False
    confidence: float = 0.5
    status: IdentityStatus = IdentityStatus.candidate
    signals: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectLink(BaseModel):
    """Map an external container (repo, channel, folder…) onto a Project."""
    id: str = Field(default_factory=lambda: ids.new_id("projlink"))
    project_id: str
    source_account_id: str = ""
    vault_id: str = ""
    external_type: str                  # github_repository | slack_channel | ...
    external_id: str
    confidence: float = 0.5
    status: ProjectLinkStatus = ProjectLinkStatus.candidate
    # Deprecated mirror of ``status == confirmed`` — kept so callers
    # and persisted payloads keep working.
    confirmed: bool = False
    created_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _migrate_confirmed_to_status(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        status = data.get("status")
        confirmed = data.get("confirmed")
        if status is None and confirmed:
            data["status"] = ProjectLinkStatus.confirmed.value
        elif status is not None:
            sval = getattr(status, "value", status)
            data["confirmed"] = sval == ProjectLinkStatus.confirmed.value
        return data


class EpisodeStatus(str, Enum):
    candidate = "candidate"
    active = "active"
    closed = "closed"
    rejected = "rejected"


class EpisodeLinkKind(str, Enum):
    explicit = "explicit"               # shared lineage_root / calendar id
    reference = "reference"             # PR #N / issue URL in content
    fingerprint = "fingerprint"         # calendar↔meeting weak key
    thread = "thread"
    derived = "derived"                 # notification_of / derived_from
    soft = "soft"                       # never auto-merge


class EpisodeLinkStatus(str, Enum):
    active = "active"
    removed = "removed"
    superseded = "superseded"


class WorkEpisode(BaseModel):
    """Cross-source work unit — candidate until confidence is high enough.

    ``correlation_key`` is the idempotent identity within a vault.
    Independence of evidence lives on EpisodeLinks, not as a single episode
    key (``independence_group`` is only the primary merge lineage, if any).
    """
    id: str = Field(default_factory=lambda: ids.new_id("episode"))
    vault_id: str = ""
    correlation_key: str = ""           # vault-qualified canonical key
    project_id: Optional[str] = None
    title: str = ""
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    status: EpisodeStatus = EpisodeStatus.candidate
    participant_actor_ids: list[str] = Field(default_factory=list)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    independence_group: Optional[str] = None   # primary lineage (optional)
    independence_group_count: int = 0
    confidence: float = 0.5
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EpisodeLink(BaseModel):
    """Edge between a WorkEpisode and a source object."""
    id: str = Field(default_factory=lambda: ids.new_id("eplink"))
    episode_id: str
    vault_id: str = ""
    connector_record_id: Optional[str] = None
    external_type: str = ""
    external_id: str = ""
    thread_key: Optional[str] = None
    lineage_root: Optional[str] = None
    kind: EpisodeLinkKind = EpisodeLinkKind.soft
    status: EpisodeLinkStatus = EpisodeLinkStatus.active
    independence_group: Optional[str] = None
    directness: float = 1.0
    confidence: float = 0.5
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EpisodePhaseKind(str, Enum):
    """Structured arc of a WorkEpisode — goal → decision → execution → outcome.

    ``other`` is the conservative default when a member does not map cleanly;
    phases are revisable structure, never Memory or Judgment.
    """
    goal = "goal"
    decision = "decision"
    execution = "execution"
    outcome = "outcome"
    other = "other"


class EpisodePhaseStatus(str, Enum):
    proposed = "proposed"
    active = "active"
    superseded = "superseded"


class EpisodePhase(BaseModel):
    """One contiguous same-kind stretch of an episode's timeline.

    ``phase_key`` is deterministic within an episode so edges can reference a
    phase stably across rebuilds. ``id`` is derived from ``phase_key`` too.
    """
    id: str = Field(default_factory=lambda: ids.new_id("epphase"))
    episode_id: str
    vault_id: str = ""
    kind: EpisodePhaseKind = EpisodePhaseKind.other
    phase_key: str = ""                 # stable within episode (kind|anchor ref)
    order: int = 0
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    status: EpisodePhaseStatus = EpisodePhaseStatus.proposed
    member_external_refs: list[str] = Field(default_factory=list)
    member_link_ids: list[str] = Field(default_factory=list)
    summary: str = ""
    confidence: float = 0.5
    # provenance: {"method": "heuristic"|"llm", "twin_influenced": bool}
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EpisodeEdgeRelation(str, Enum):
    motivated = "motivated"             # A led to / prompted B
    superseded = "superseded"           # B overturns / replaces A
    resolved = "resolved"               # B closed / answered A
    continues = "continues"             # B carries on A
    contradicts = "contradicts"         # A and B disagree (cross-source)


class EpisodeEdgeStatus(str, Enum):
    proposed = "proposed"
    confirmed = "confirmed"
    rejected = "rejected"


class EpisodeEdge(BaseModel):
    """Revisable causal / narrative edge between two phases (or links).

    ``from_ref`` / ``to_ref`` are ``{"kind": "phase"|"link", "id": <key>}``.
    Phase refs use ``EpisodePhase.phase_key`` so they survive rebuilds. Never
    auto-writes Memory or Judgment; default status is ``proposed``.
    """
    id: str = Field(default_factory=lambda: ids.new_id("epedge"))
    episode_id: str
    vault_id: str = ""
    from_ref: dict[str, Any] = Field(default_factory=dict)
    to_ref: dict[str, Any] = Field(default_factory=dict)
    relation: EpisodeEdgeRelation = EpisodeEdgeRelation.continues
    status: EpisodeEdgeStatus = EpisodeEdgeStatus.proposed
    confidence: float = 0.5
    evidence_quote: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)
