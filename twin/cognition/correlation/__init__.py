"""Cross-source cognition (v0.6 Phase 7).

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
    EpisodeLink,
    EpisodeLinkKind,
    EpisodeLinkStatus,
    EpisodeStatus,
    ExternalIdentity,
    IdentityLink,
    IdentityStatus,
    ProjectLink,
    ProjectLinkStatus,
    WorkEpisode,
)
from .partition import partition_records, vault_for_record
from .service import CorrelationReport, run_correlation_pass

__all__ = [
    "CorrelationReport",
    "EpisodeLink",
    "EpisodeLinkKind",
    "EpisodeLinkStatus",
    "EpisodeStatus",
    "ExternalIdentity",
    "IdentityLink",
    "IdentityStatus",
    "ProjectLink",
    "ProjectLinkStatus",
    "WorkEpisode",
    "evidence_directness_for",
    "explain_episode",
    "explain_identity_link",
    "explain_project_link",
    "independence_group_for",
    "is_derived_evidence",
    "partition_records",
    "run_correlation_pass",
    "vault_for_record",
]
