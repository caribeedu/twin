"""Confidence-aware spontaneous recall (v0.8).

Recall is a *policy* over observer hits: speak only when confidence and
salience clear the bar; otherwise stay silent. Forbidden memories stay in
``blocked`` with ids/reasons only — never leaked into suggestions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class RecallPolicy:
    """Gates for spontaneous recall. Prefer silence over weak recall."""

    min_confidence: float = 0.55
    min_score: float = 0.25
    min_salience: float = 0.35
    max_suggestions: int = 5


@dataclass
class RecallItem:
    memory_id: str
    summary: str
    why_relevant: str
    confidence: float
    score: float
    salience: float = 0.0
    novelty: float = 0.0
    stage: str = "suggestion"  # suggestion | blocked


@dataclass
class RecallResult:
    suggestions: list[RecallItem] = field(default_factory=list)
    blocked: list[dict[str, Any]] = field(default_factory=list)
    silent: bool = False
    silence_reason: str = ""


def apply_recall_policy(
    suggested: list[dict[str, Any]],
    blocked: list[dict[str, Any]],
    *,
    policy: Optional[RecallPolicy] = None,
    salience_by_id: Optional[dict[str, float]] = None,
    novelty_by_id: Optional[dict[str, float]] = None,
) -> RecallResult:
    """Filter observer output into confidence-aware spontaneous recall.

    Never promotes blocked firewall hits into suggestions. Empty surviving
    suggestions → ``silent=True`` (non-intrusive default).
    """
    policy = policy or RecallPolicy()
    salience_by_id = salience_by_id or {}
    novelty_by_id = novelty_by_id or {}
    out = RecallResult(blocked=list(blocked))

    kept: list[RecallItem] = []
    for row in suggested:
        mid = row.get("memory_id") or ""
        conf = float(row.get("confidence") or 0.0)
        score = float(row.get("score") or row.get("confidence") or 0.0)
        sal = float(salience_by_id.get(mid, conf))
        nov = float(novelty_by_id.get(mid, 0.0))
        if conf < policy.min_confidence:
            continue
        if score < policy.min_score:
            continue
        if sal < policy.min_salience:
            continue
        kept.append(RecallItem(
            memory_id=mid,
            summary=str(row.get("summary") or ""),
            why_relevant=str(row.get("why_relevant") or ""),
            confidence=conf,
            score=score,
            salience=sal,
            novelty=nov,
            stage="suggestion",
        ))
        if len(kept) >= policy.max_suggestions:
            break

    out.suggestions = kept
    if not kept:
        out.silent = True
        out.silence_reason = (
            "no suggestion cleared confidence/salience bar"
            if suggested else "no observer hits"
        )
    return out
