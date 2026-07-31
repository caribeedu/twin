"""Cross-source cognition.

Identity resolution, project mapping, WorkEpisode correlation, independence
groups, and conflict findings. Connectors capture evidence; this package
proposes structure for the cognitive core — never confirmed Memory/Judgment.
"""

from .independence import (
    evidence_directness_for,
    independence_group_for,
    is_derived_evidence,
)
from .explain import (
    explain_episode,
    explain_identity_link,
    explain_project_link,
)
from .models import (
    EpisodeEdge,
    EpisodeEdgeRelation,
    EpisodeEdgeStatus,
    EpisodeLink,
    EpisodeLinkKind,
    EpisodeLinkStatus,
    EpisodePhase,
    EpisodePhaseKind,
    EpisodePhaseStatus,
    EpisodeStatus,
    ExternalIdentity,
    IdentityLink,
    IdentityStatus,
    ProjectLink,
    ProjectLinkStatus,
    WorkEpisode,
)
from .edges import (
    build_edges_from_llm,
    clear_proposed_edges,
    confirm_edge,
    persist_edges,
    reject_edge,
)
from .partition import partition_records, vault_for_record
from .phases import (
    build_phases_from_roles,
    clear_phases,
    member_briefs,
    persist_phases,
)
from .service import CorrelationReport, run_correlation_pass

__all__ = [
    "CorrelationReport",
    "EpisodeEdge",
    "EpisodeEdgeRelation",
    "EpisodeEdgeStatus",
    "EpisodeLink",
    "EpisodeLinkKind",
    "EpisodeLinkStatus",
    "EpisodePhase",
    "EpisodePhaseKind",
    "EpisodePhaseStatus",
    "EpisodeStatus",
    "ExternalIdentity",
    "IdentityLink",
    "IdentityStatus",
    "ProjectLink",
    "ProjectLinkStatus",
    "WorkEpisode",
    "build_edges_from_llm",
    "build_phases_from_roles",
    "clear_phases",
    "clear_proposed_edges",
    "confirm_edge",
    "evidence_directness_for",
    "explain_episode",
    "explain_identity_link",
    "explain_project_link",
    "independence_group_for",
    "is_derived_evidence",
    "member_briefs",
    "partition_records",
    "persist_edges",
    "persist_phases",
    "reject_edge",
    "run_correlation_pass",
    "vault_for_record",
]
