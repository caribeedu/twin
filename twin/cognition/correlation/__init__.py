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
from .models import (
    EpisodeLink,
    EpisodeLinkKind,
    EpisodeStatus,
    ExternalIdentity,
    IdentityLink,
    IdentityStatus,
    ProjectLink,
    WorkEpisode,
)
from .service import CorrelationReport, run_correlation_pass

__all__ = [
    "CorrelationReport",
    "EpisodeLink",
    "EpisodeLinkKind",
    "EpisodeStatus",
    "ExternalIdentity",
    "IdentityLink",
    "IdentityStatus",
    "ProjectLink",
    "WorkEpisode",
    "evidence_directness_for",
    "independence_group_for",
    "is_derived_evidence",
    "run_correlation_pass",
]
