"""Daily / weekly consolidation cycles (v0.8).

Distinct from session-close consolidation (``sessions._consolidate``): these
cycles run on a schedule over the whole store — quality analysis, safe
automation, temporal belief/goal refresh, and (weekly) optional judgment
proposals. They never confirm Memory or Judgment.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..clock import now_iso
from ..config import Config
from ..memory.automation import apply_safe_automations
from ..memory.embeddings import Embedder
from ..memory.store.base import MemoryStore
from .quality import analyze_candidates


@dataclass
class ConsolidationCycleResult:
    kind: str  # daily | weekly
    dry_run: bool = False
    at: str = ""
    stages: list[str] = field(default_factory=list)
    analyzed: int = 0
    contradiction_memory_ids: list[str] = field(default_factory=list)
    automation: dict[str, Any] = field(default_factory=dict)
    temporal_updates: list[dict[str, Any]] = field(default_factory=list)
    goals_observed: list[dict[str, Any]] = field(default_factory=list)
    judgment_proposal_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def refresh_temporal_beliefs_and_goals(
    store: MemoryStore,
    *,
    dry_run: bool = False,
    belief_max_age_days: int = 90,
    as_of: Optional[datetime] = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Flag expired/stale beliefs for review; report project goals needing attention.

    Durable consolidation still requires a human (or an explicit later action).
    """
    now = as_of or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=belief_max_age_days)
    updates: list[dict[str, Any]] = []

    for mem in store.list_memories(type_="belief", status="confirmed", limit=5_000):
        reasons: list[str] = []
        until = _parse_iso(mem.valid_until)
        if until is not None and until < now:
            reasons.append("valid_until_expired")
        anchor = _parse_iso(mem.updated_at) or _parse_iso(mem.created_at)
        if anchor is not None and anchor < cutoff:
            reasons.append("age_without_refresh")
        if not reasons:
            continue
        row = {
            "memory_id": mem.id,
            "type": "belief",
            "action": "flag_review",
            "reasons": reasons,
            "title": mem.title,
        }
        updates.append(row)
        if dry_run:
            continue
        flags = list(mem.quality_flags or [])
        if "stale" not in flags:
            flags.append("stale")
        store.update_memory(
            mem.id,
            needs_review=True,
            review_reason="temporal_belief_refresh",
            quality_flags=flags,
        )

    goals: list[dict[str, Any]] = []
    if hasattr(store, "list_projects"):
        for project in store.list_projects():
            project_goals = list(getattr(project, "goals", None) or [])
            if not project_goals:
                continue
            updated = _parse_iso(getattr(project, "updated_at", None))
            stale_project = updated is not None and updated < cutoff
            for goal in project_goals:
                goals.append({
                    "project_id": project.id,
                    "project_name": getattr(project, "name", ""),
                    "goal": goal,
                    "action": "observe",
                    "stale_project": stale_project,
                    "stage": "goal_observation",
                })
    return updates, goals


def run_consolidation_cycle(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    *,
    kind: str = "daily",
    dry_run: bool = False,
    analyze_limit: int = 200,
    propose_judgment: Optional[bool] = None,
) -> ConsolidationCycleResult:
    """Run one daily or weekly consolidation cycle.

    Stages (typed, ordered):
      analyze → contradictions → safe_automation → temporal_refresh
      → (weekly) judgment_proposals → done

    ``propose_judgment`` defaults to True on weekly, False on daily.
    """
    if kind not in ("daily", "weekly"):
        raise ValueError(f"unknown consolidation cycle kind: {kind!r}")
    if propose_judgment is None:
        propose_judgment = kind == "weekly"

    result = ConsolidationCycleResult(kind=kind, dry_run=dry_run, at=now_iso())
    result.stages.append("analyze")
    if not dry_run:
        reports = analyze_candidates(store, embedder, limit=analyze_limit)
        result.analyzed = len(reports)
    else:
        # dry: count queue only
        queue = store.list_memories(status="candidate", needs_review=True, limit=analyze_limit)
        if not queue:
            queue = store.list_memories(status="candidate", limit=analyze_limit)
        result.analyzed = len(queue)
        result.notes.append("dry_run skipped quality analyzer writes")

    result.stages.append("contradictions")
    conflict_ids: list[str] = []
    for mem in store.list_memories(limit=10_000):
        if "possible_conflict" in (mem.quality_flags or []):
            conflict_ids.append(mem.id)
    result.contradiction_memory_ids = conflict_ids

    result.stages.append("safe_automation")
    result.automation = apply_safe_automations(store, dry_run=dry_run)

    result.stages.append("temporal_refresh")
    updates, goals = refresh_temporal_beliefs_and_goals(store, dry_run=dry_run)
    result.temporal_updates = updates
    result.goals_observed = goals

    if propose_judgment:
        result.stages.append("judgment_proposals")
        from ..judgment.proposals import propose_from_pattern
        if dry_run:
            result.notes.append("dry_run skipped judgment proposals")
        else:
            proposals = propose_from_pattern(store, domain="technical")
            result.judgment_proposal_ids = [p.id for p in proposals]

    result.stages.append("done")
    result.notes.append(
        "cycle never confirms Memory or Judgment; durable changes stay human-gated"
    )
    return result
