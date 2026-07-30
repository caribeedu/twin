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
from .edges import confirm_edge, propose_edges, rebuild_edges, reject_edge
from .partition import partition_records, vault_for_record
from .phases import compute_phases, rebuild_phases
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
    "compute_phases",
    "confirm_edge",
    "evidence_directness_for",
    "explain_episode",
    "explain_identity_link",
    "explain_project_link",
    "independence_group_for",
    "is_derived_evidence",
    "partition_records",
    "propose_edges",
    "rebuild_edges",
    "rebuild_phases",
    "reject_edge",
    "run_correlation_pass",
    "vault_for_record",
]
