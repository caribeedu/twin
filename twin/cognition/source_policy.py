"""Per-source memory candidate policy (v0.6 §49–50, §70).

Connector-fed percepts don't get to propose every memory type: GitHub may
propose decisions and constraints, but never beliefs or preferences; Slack
and email will be progressively more conservative. The policy gates WHAT can
become a candidate — the connector itself never enforces it (connectors
capture evidence; the cognitive core decides what to do with it).

Resolution order for one extracted memory:

    type in drop            → discarded (searchable as artifact, never memory)
    type in require_review  → candidate, forced needs_review
    allow declared and type not in allow → discarded
    otherwise               → normal pipeline rules apply

Only percepts that carry ``metadata.connector_type`` are affected — local
sensors (documents, git working copy, sessions) keep their existing rules.
Instance-level overrides travel on ``metadata.ingestion_policy``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..sensory.percept import Percept


@dataclass
class SourcePolicy:
    allow: Optional[frozenset[str]] = None       # None = no allowlist
    require_review: frozenset[str] = frozenset()
    drop: frozenset[str] = frozenset()


@dataclass
class PolicyDecision:
    action: str                 # "allow" | "review" | "drop"
    reason: Optional[str] = None


# Initial calibration per connector type (v0.6 §70). Instance configuration
# may only NARROW these defaults — never widen them.
DEFAULT_SOURCE_POLICIES: dict[str, SourcePolicy] = {
    "github": SourcePolicy(
        allow=frozenset({"decision", "constraint", "procedure", "fact",
                         "event", "task"}),
        require_review=frozenset({"task", "procedure"}),
        drop=frozenset({"preference", "belief", "relationship"}),
    ),
    # Slack is more conservative: informal chat may propose decisions /
    # commitments / risks, but never beliefs, preferences or relationships,
    # and candidates that do flow in are born needing review.
    "slack": SourcePolicy(
        allow=frozenset({"decision", "constraint", "task", "event", "fact"}),
        require_review=frozenset({"decision", "constraint", "task",
                                  "event", "fact"}),
        drop=frozenset({"preference", "belief", "relationship", "procedure"}),
    ),
    # Email is stricter still (v0.6 §70): narrow allowlist, every candidate
    # needs review; belief/preference/relationship never auto-flow.
    "gmail": SourcePolicy(
        allow=frozenset({"decision", "constraint", "task", "fact"}),
        require_review=frozenset({"decision", "constraint", "task", "fact"}),
        drop=frozenset({"preference", "belief", "relationship",
                        "procedure", "event"}),
    ),
    "outlook": SourcePolicy(
        allow=frozenset({"decision", "constraint", "task", "fact"}),
        require_review=frozenset({"decision", "constraint", "task", "fact"}),
        drop=frozenset({"preference", "belief", "relationship",
                        "procedure", "event"}),
    ),
    # Calendar: temporal context + commitments; every candidate needs review.
    "calendar": SourcePolicy(
        allow=frozenset({"event", "task", "fact"}),
        require_review=frozenset({"event", "task", "fact"}),
        drop=frozenset({"preference", "belief", "relationship",
                        "procedure", "decision"}),
    ),
    # Fireflies / meeting transcripts: decisions & tasks possible, always review.
    "fireflies": SourcePolicy(
        allow=frozenset({"decision", "constraint", "task", "fact", "event"}),
        require_review=frozenset({"decision", "constraint", "task",
                                  "fact", "event"}),
        drop=frozenset({"preference", "belief", "relationship", "procedure"}),
    ),
    # Shared documents: technical facts/decisions/procedures; always review.
    "folder": SourcePolicy(
        allow=frozenset({"decision", "constraint", "procedure", "fact",
                         "task"}),
        require_review=frozenset({"decision", "constraint", "procedure",
                                  "fact", "task"}),
        drop=frozenset({"preference", "belief", "relationship", "event"}),
    ),
    # exercised by the contract suite; mirrors github's posture
    "fake": SourcePolicy(
        allow=frozenset({"decision", "constraint", "procedure", "fact",
                         "event", "task"}),
        drop=frozenset({"preference", "belief"}),
    ),
}


def _from_config(raw: dict[str, Any]) -> SourcePolicy:
    allow_raw = raw.get("allow_memory_types")
    return SourcePolicy(
        allow=frozenset(allow_raw) if allow_raw else None,
        require_review=frozenset(raw.get("require_review_for") or []),
        drop=frozenset(raw.get("drop") or []),
    )


def merge_policies(default: SourcePolicy, override: SourcePolicy) -> SourcePolicy:
    """Combine defaults with instance overrides restrictively.

    Instances may remove allowlist entries, add drops, and add review
    requirements — never the reverse."""
    if override.allow is not None:
        base = default.allow if default.allow is not None else frozenset()
        effective_allow: Optional[frozenset[str]] = base & override.allow
    else:
        effective_allow = default.allow
    return SourcePolicy(
        allow=effective_allow,
        require_review=default.require_review | override.require_review,
        drop=default.drop | override.drop,
    )


def policy_for_percept(percept: Percept) -> Optional[SourcePolicy]:
    """The policy that governs candidates derived from this percept, or None
    when the percept did not come through a connector."""
    connector_type = (percept.metadata or {}).get("connector_type")
    if not connector_type:
        return None
    default = DEFAULT_SOURCE_POLICIES.get(str(connector_type), SourcePolicy())
    override = (percept.metadata or {}).get("ingestion_policy")
    if isinstance(override, dict) and override:
        return merge_policies(default, _from_config(override))
    return default


def evaluate(policy: Optional[SourcePolicy], memory_type: str) -> PolicyDecision:
    if policy is None:
        return PolicyDecision("allow")
    if memory_type in policy.drop:
        return PolicyDecision(
            "drop", f"memory type '{memory_type}' not accepted from this source")
    if memory_type in policy.require_review:
        return PolicyDecision(
            "review", f"source policy requires review for '{memory_type}'")
    if policy.allow is not None and memory_type not in policy.allow:
        return PolicyDecision(
            "drop", f"memory type '{memory_type}' outside the source allowlist")
    return PolicyDecision("allow")
