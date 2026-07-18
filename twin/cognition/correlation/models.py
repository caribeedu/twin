"""Cross-source cognition models (v0.6 Phase 7).

Connectors capture evidence; this package proposes identities, project maps,
WorkEpisodes, independence groups and conflict findings — never confirmed
Memory or Judgment.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from ... import ids
from ...clock import now_iso


class IdentityStatus(str, Enum):
    candidate = "candidate"
    confirmed = "confirmed"
    rejected = "rejected"


class ExternalIdentity(BaseModel):
    """One provider-scoped person/handle observation."""
    id: str = Field(default_factory=lambda: ids.new_id("extid"))
    provider: str
    external_id: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    source_account_id: str = ""
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
    external_type: str                  # github_repository | slack_channel | ...
    external_id: str
    confidence: float = 0.5
    confirmed: bool = False
    created_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    soft = "soft"                       # temporal + participants (never auto-merge)


class WorkEpisode(BaseModel):
    """Cross-source work unit — candidate until confidence is high enough."""
    id: str = Field(default_factory=lambda: ids.new_id("episode"))
    project_id: Optional[str] = None
    title: str = ""
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    status: EpisodeStatus = EpisodeStatus.candidate
    participant_actor_ids: list[str] = Field(default_factory=list)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    independence_group: Optional[str] = None
    confidence: float = 0.5
    vault_id: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EpisodeLink(BaseModel):
    """Edge between a WorkEpisode and a source object (or between episodes)."""
    id: str = Field(default_factory=lambda: ids.new_id("eplink"))
    episode_id: str
    connector_record_id: Optional[str] = None
    external_type: str = ""
    external_id: str = ""
    thread_key: Optional[str] = None
    lineage_root: Optional[str] = None
    kind: EpisodeLinkKind = EpisodeLinkKind.soft
    confidence: float = 0.5
    created_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)
