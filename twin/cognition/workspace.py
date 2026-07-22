"""Parallel workspace tick (v0.8) — Global-Workspace-shaped observation.

Separates stages clearly:

```text
interpretation reading (fast/deep observer)
→ spontaneous recall suggestions (confidence-gated)
→ silent blocked (firewall)
→ optional parallel interpretation → memory candidates
→ never durable confirmation
```

A tick never writes confirmed Memory or Judgment. Parallel interpretation
reuses the v0.7 pipeline and only produces reviewable candidates.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from .. import ids
from ..clock import now_iso
from ..config import Config
from ..judgment.firewall import Firewall
from ..memory.embeddings import Embedder
from ..memory.store.base import MemoryStore
from ..sensory.percept import Percept
from .observer import observe, read_context
from .pipeline import extract_percept
from .recall import RecallPolicy, RecallResult, apply_recall_policy
from .salience import score_memories


@dataclass
class WorkspaceTickResult:
    """Typed stages of one parallel-memory tick."""

    session_id: str = ""
    inferred_domain: str = ""
    reading: dict[str, Any] = field(default_factory=dict)
    suggestions: list[dict[str, Any]] = field(default_factory=list)
    blocked: list[dict[str, Any]] = field(default_factory=list)
    silent: bool = False
    silence_reason: str = ""
    contradiction_memory_ids: list[str] = field(default_factory=list)
    parallel_interpretation: dict[str, Any] = field(default_factory=dict)
    candidate_memory_ids: list[str] = field(default_factory=list)
    stages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def workspace_tick(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    current_text: str,
    *,
    session_id: str = "",
    target_domain: Optional[str] = None,
    cwd: Optional[str] = None,
    policy: Optional[RecallPolicy] = None,
    interpret: bool = False,
    firewall: Optional[Firewall] = None,
) -> WorkspaceTickResult:
    """Run one parallel-memory tick over the current conversational text.

    ``interpret=True`` feeds the text through the cognitive interpreter as a
    session-delta percept (candidates only). Default is observation+recall
    only — cheap enough for every host intervene_check.
    """
    text = (current_text or "").strip()
    result = WorkspaceTickResult(session_id=session_id or "")
    result.stages.append("reading")

    reading = read_context(store, cfg, text, cwd=cwd)
    result.reading = {
        "domain": reading.domain,
        "task_profile": reading.task_profile,
        "project_id": reading.project_id,
        "confidences": dict(reading.confidences or {}),
        "uncertain": reading.uncertain,
        "mode": reading.mode,
        "needs_domain_confirmation": reading.needs_domain_confirmation,
    }
    domain = target_domain or reading.domain
    result.inferred_domain = domain

    result.stages.append("observe")
    obs = observe(
        store, cfg, embedder, text,
        target_domain=domain if domain != "unclassified" else None,
        firewall=firewall,
    )
    # Attach retrieval scores when present; observe uses confidence as proxy.
    suggested_rows = []
    for row in obs.suggested_context:
        suggested_rows.append({
            **row,
            "score": float(row.get("confidence") or 0.0),
        })

    result.stages.append("salience")
    mids = [r["memory_id"] for r in suggested_rows if r.get("memory_id")]
    scores = score_memories(store, mids, query_text=text)
    result.contradiction_memory_ids = list(scores.contradiction_ids)

    result.stages.append("recall")
    recall: RecallResult = apply_recall_policy(
        suggested_rows, obs.blocked_context,
        policy=policy,
        salience_by_id=scores.by_memory,
        novelty_by_id=scores.novelty,
    )
    result.suggestions = [
        {
            "memory_id": s.memory_id,
            "summary": s.summary,
            "why_relevant": s.why_relevant,
            "confidence": s.confidence,
            "score": s.score,
            "salience": s.salience,
            "novelty": s.novelty,
            "stage": s.stage,
        }
        for s in recall.suggestions
    ]
    result.blocked = list(recall.blocked)
    result.silent = recall.silent
    result.silence_reason = recall.silence_reason

    if interpret and text:
        result.stages.append("parallel_interpretation")
        percept = Percept(
            id=ids.new_id("pct"),
            percept_type="session_delta",
            source_sensor="workspace",
            occurred_at=now_iso(),
            ingested_at=now_iso(),
            content=text,
            source_trust=0.70,
            source_scope=domain if domain != "unclassified" else "technical",
            source_confidentiality="internal",
            project_id=reading.project_id,
            metadata={
                "workspace_tick": True,
                "session_id": session_id or "",
                "stage": "parallel_interpretation",
            },
        )
        percept.seal()
        store.insert_percept(percept)
        report = extract_percept(store, cfg, embedder, percept)
        result.parallel_interpretation = {
            "percept_id": percept.id,
            "deferred": report.deferred,
            "interpretation_status": report.interpretation_status,
            "inserted": list(report.inserted),
            "ungrounded": report.ungrounded,
            "invalid": report.invalid,
            "policy_dropped": report.policy_dropped,
            "stage_counts": report.stage_counts(),
        }
        result.candidate_memory_ids = list(report.inserted)
        # Never mark inserted candidates as confirmed here — pipeline already
        # creates review-bound candidates only.

    result.stages.append("done")
    return result
