"""Confidence-aware spontaneous recall.

Recall is a *policy* over observer hits:

```text
eligibility = confidence gate AND retrieval relevance gate
ranking = relevance + salience + controlled novelty boost
```

Novelty may reorder eligible suggestions; it must not help an irrelevant hit
clear the relevance bar. Forbidden memories stay in ``blocked`` (ids/reasons
only) — never promoted into suggestions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class RecallPolicy:
    """Gates for spontaneous recall. Prefer silence over weak recall."""

    min_confidence: float = 0.55
    min_score: float = 0.25
    min_salience: float = 0.0  # optional attention floor; 0 = off
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
    """Filter observer output into confidence + relevance-aware spontaneous recall.

    ``score`` is retrieval relevance from the observer — never substituted from
    memory confidence. Empty surviving suggestions → ``silent=True``.
    """
    policy = policy or RecallPolicy()
    salience_by_id = salience_by_id or {}
    novelty_by_id = novelty_by_id or {}
    out = RecallResult(blocked=list(blocked))

    eligible: list[RecallItem] = []
    for row in suggested:
        mid = row.get("memory_id") or ""
        conf = float(row.get("confidence") or 0.0)
        # Retrieval relevance only — do not fall back to confidence.
        if "score" not in row or row.get("score") is None:
            continue
        score = float(row["score"])
        sal = float(salience_by_id.get(mid, 0.0))
        nov = float(novelty_by_id.get(mid, 0.0))
        if conf < policy.min_confidence:
            continue
        if score < policy.min_score:
            continue
        if policy.min_salience > 0 and sal < policy.min_salience:
            continue
        eligible.append(RecallItem(
            memory_id=mid,
            summary=str(row.get("summary") or ""),
            why_relevant=str(row.get("why_relevant") or ""),
            confidence=conf,
            score=score,
            salience=sal,
            novelty=nov,
            stage="suggestion",
        ))

    # Rank eligible: relevance first, then salience, then novelty (inspection boost).
    eligible.sort(key=lambda s: (s.score, s.salience, s.novelty), reverse=True)
    out.suggestions = eligible[: policy.max_suggestions]
    if not out.suggestions:
        out.silent = True
        out.silence_reason = (
            "no suggestion cleared confidence/relevance bar"
            if suggested else "no observer hits"
        )
    return out
