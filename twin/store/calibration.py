"""Source calibration — trust by source × memory type.

Git commit messages are strong for facts, weaker for preferences.
Meeting transcripts are strong for decisions and tasks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

DEFAULT_CALIBRATION: dict[str, Any] = {
    "sources": {
        "git": {
            "base_trust": 0.90,
            "type_modifiers": {
                "fact": 1.0,
                "decision": 0.75,
                "preference": 0.35,
                "belief": 0.30,
                "task": 0.40,
                "constraint": 0.70,
                "event": 0.85,
            },
        },
        "git_commit": {
            "base_trust": 0.90,
            "type_modifiers": {
                "fact": 1.0,
                "decision": 0.75,
                "preference": 0.35,
                "belief": 0.30,
                "task": 0.40,
            },
        },
        "document": {
            "base_trust": 0.85,
            "type_modifiers": {
                "fact": 0.95,
                "decision": 0.90,
                "preference": 0.70,
                "constraint": 0.90,
            },
        },
        "meeting": {
            "base_trust": 0.82,
            "type_modifiers": {
                "decision": 1.0,
                "task": 0.95,
                "preference": 0.70,
                "belief": 0.65,
                "fact": 0.70,
            },
        },
        "meeting_transcript": {
            "base_trust": 0.82,
            "type_modifiers": {
                "decision": 1.0,
                "task": 0.95,
            },
        },
        "slack": {
            "base_trust": 0.70,
            "type_modifiers": {
                "task": 0.85,
                "decision": 0.75,
                "preference": 0.60,
                "fact": 0.65,
            },
        },
        "session": {
            "base_trust": 0.88,
            "type_modifiers": {
                "fact": 1.0,
                "decision": 1.0,
                "preference": 1.0,
                "task": 1.0,
                "belief": 0.85,
            },
        },
        "heuristic": {
            "base_trust": 0.55,
            "type_modifiers": {
                "fact": 0.8,
                "decision": 0.6,
                "preference": 0.5,
            },
        },
        "ollama": {
            "base_trust": 0.70,
            "type_modifiers": {
                "fact": 0.75,
                "decision": 0.70,
                "preference": 0.55,
                "belief": 0.50,
            },
        },
    },
    "quality_automation": {
        "exact_duplicate": {
            "action": "reject",
            "max_sensitivity": "internal",
        },
        "corroborating_evidence": {
            "action": "attach",
        },
        "possible_conflict": {
            "action": "review",
        },
        "expired_task": {
            "action": "archive",
            "min_age_days": 30,
            "require_valid_until": True,
            "allowed_terminal_states": ["completed", "cancelled"],
        },
    },
}


def load_calibration(path: Optional[Path] = None) -> dict[str, Any]:
    if path and path.exists():
        data = yaml.safe_load(path.read_text()) or {}
        merged = {**DEFAULT_CALIBRATION, **data}
        if "sources" in data:
            merged["sources"] = {**DEFAULT_CALIBRATION["sources"], **data["sources"]}
        if "quality_automation" in data:
            merged["quality_automation"] = {
                **DEFAULT_CALIBRATION["quality_automation"],
                **data["quality_automation"],
            }
        return merged
    return dict(DEFAULT_CALIBRATION)


def calibrated_confidence(
    source: str,
    claim_type: str,
    raw_confidence: float,
    *,
    source_trust: Optional[float] = None,
    evidence_directness: float = 1.0,
    extractor_reliability: float = 1.0,
    calibration: Optional[dict[str, Any]] = None,
) -> float:
    """Combine source trust with type compatibility and evidence directness.

    Preserves the v0.2 ``raw × source_trust`` core, then softly applies the
    source×type matrix so preferences from git commits are downweighted
    without crushing ordinary facts below the firewall floor.
    """
    cal = calibration or DEFAULT_CALIBRATION
    src = cal.get("sources", {}).get(source) or cal.get("sources", {}).get("document", {})
    trust = float(source_trust if source_trust is not None else src.get("base_trust", 0.7))
    mod = float(src.get("type_modifiers", {}).get(claim_type, 1.0))
    # Soft type curve: modifier 1.0 → full trust; 0.35 → ~0.71× trust
    adjusted_trust = trust * (0.55 + 0.45 * mod)
    score = raw_confidence * adjusted_trust * evidence_directness
    if extractor_reliability < 1.0:
        score *= 0.9 + 0.1 * extractor_reliability
    return round(min(0.99, max(0.05, score)), 3)


def source_report(calibration: Optional[dict[str, Any]] = None,
                  source: Optional[str] = None) -> dict[str, Any]:
    cal = calibration or DEFAULT_CALIBRATION
    sources = cal.get("sources", {})
    if source:
        return {source: sources.get(source, {})}
    return sources
