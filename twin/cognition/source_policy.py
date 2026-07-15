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
    allow: frozenset[str] = frozenset()          # empty = no allowlist
    require_review: frozenset[str] = frozenset()
    drop: frozenset[str] = frozenset()


@dataclass
class PolicyDecision:
    action: str                 # "allow" | "review" | "drop"
    reason: Optional[str] = None


# Initial calibration per connector type (v0.6 §70). Not universal truth —
# instance configuration can override every field.
DEFAULT_SOURCE_POLICIES: dict[str, SourcePolicy] = {
    "github": SourcePolicy(
        allow=frozenset({"decision", "constraint", "procedure", "fact",
                         "event", "task"}),
        require_review=frozenset({"task", "procedure"}),
        drop=frozenset({"preference", "belief", "relationship"}),
    ),
    # exercised by the contract suite; mirrors github's posture
    "fake": SourcePolicy(
        allow=frozenset({"decision", "constraint", "procedure", "fact",
                         "event", "task"}),
        drop=frozenset({"preference", "belief"}),
    ),
}


def _from_config(raw: dict[str, Any]) -> SourcePolicy:
    return SourcePolicy(
        allow=frozenset(raw.get("allow_memory_types") or []),
        require_review=frozenset(raw.get("require_review_for") or []),
        drop=frozenset(raw.get("drop") or []),
    )


def policy_for_percept(percept: Percept) -> Optional[SourcePolicy]:
    """The policy that governs candidates derived from this percept, or None
    when the percept did not come through a connector."""
    connector_type = (percept.metadata or {}).get("connector_type")
    if not connector_type:
        return None
    override = (percept.metadata or {}).get("ingestion_policy")
    if isinstance(override, dict) and override:
        return _from_config(override)
    return DEFAULT_SOURCE_POLICIES.get(str(connector_type), SourcePolicy())


def evaluate(policy: Optional[SourcePolicy], memory_type: str) -> PolicyDecision:
    if policy is None:
        return PolicyDecision("allow")
    if memory_type in policy.drop:
        return PolicyDecision(
            "drop", f"memory type '{memory_type}' not accepted from this source")
    if memory_type in policy.require_review:
        return PolicyDecision(
            "review", f"source policy requires review for '{memory_type}'")
    if policy.allow and memory_type not in policy.allow:
        return PolicyDecision(
            "drop", f"memory type '{memory_type}' outside the source allowlist")
    return PolicyDecision("allow")
