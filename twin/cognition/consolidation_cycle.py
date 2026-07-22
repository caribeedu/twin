"""Daily / weekly consolidation cycles (v0.8).

Distinct from session-close consolidation (``sessions._consolidate``): these
cycles run on a logical window over the store — quality analysis, safe
automation, temporal belief/goal refresh, and (weekly) optional judgment
proposals. They never confirm Memory or Judgment.

Apply runs are idempotent per ``(kind, window_start, window_end)``. This is a
synchronous maintenance spine, not a continuous background worker.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..clock import now_iso
from ..config import Config
from ..connectors.errors import sanitize_error
from ..memory.automation import apply_safe_automations
from ..memory.embeddings import Embedder
from ..memory.store.base import MemoryStore
from ..memory.store.workspace_ops_mixin import ConsolidationRunRecord
from .quality import analyze_candidates


class ConsolidationInvariantError(RuntimeError):
    """Cycle mutated the confirmed Memory/Judgment set — must not complete."""


@dataclass
class ConsolidationCycleResult:
    kind: str  # daily | weekly
    dry_run: bool = False
    run_id: str = ""
    window_start: str = ""
    window_end: str = ""
    duplicated: bool = False
    status: str = ""
    at: str = ""
    stages: list[str] = field(default_factory=list)
    analyzed: int = 0
    contradiction_memory_ids: list[str] = field(default_factory=list)
    automation: dict[str, Any] = field(default_factory=dict)
    temporal_updates: list[dict[str, Any]] = field(default_factory=list)
    goals_observed: list[dict[str, Any]] = field(default_factory=list)
    judgment_proposal_ids: list[str] = field(default_factory=list)
    truncated: bool = False
    notes: list[str] = field(default_factory=list)
    error: str = ""
    error_stage: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConsolidationCycleResult":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


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


def logical_window(
    kind: str,
    *,
    as_of: Optional[datetime] = None,
) -> tuple[str, str]:
    """Return inclusive ISO date bounds for a daily or weekly cycle window."""
    now = as_of or datetime.now(timezone.utc)
    if kind == "daily":
        day = now.date().isoformat()
        return day, day
    if kind == "weekly":
        # ISO week: Monday..Sunday
        monday = (now - timedelta(days=now.weekday())).date()
        sunday = monday + timedelta(days=6)
        return monday.isoformat(), sunday.isoformat()
    raise ValueError(f"unknown consolidation cycle kind: {kind!r}")


def refresh_temporal_beliefs_and_goals(
    store: MemoryStore,
    *,
    dry_run: bool = False,
    belief_max_age_days: int = 90,
    as_of: Optional[datetime] = None,
    page_size: int = 500,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    """Flag expired/stale beliefs for review; report project goals needing attention.

    Returns ``(updates, goals, truncated)``. Durable consolidation still requires
    a human (or an explicit later action).
    """
    now = as_of or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=belief_max_age_days)
    updates: list[dict[str, Any]] = []
    truncated = False

    # Page by over-fetching; list_memories has no offset — detect truncation.
    beliefs = store.list_memories(type_="belief", status="confirmed", limit=page_size)
    if len(beliefs) >= page_size:
        truncated = True

    for mem in beliefs:
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
    return updates, goals, truncated


def _existing_window_proposals(
    store: MemoryStore, *, window_key: str, detector: str,
) -> list[str]:
    if not hasattr(store, "list_judgment_proposals"):
        return []
    ids_out: list[str] = []
    for p in store.list_judgment_proposals(status="pending", limit=500):
        meta = getattr(p, "metadata", None) or {}
        if meta.get("detector") == detector and meta.get("consolidation_window") == window_key:
            ids_out.append(p.id)
    return ids_out


def _confirmed_snapshot(store: MemoryStore) -> tuple[set[str], set[str]]:
    mems = {
        m.id for m in store.list_memories(status="confirmed", limit=10_000)
    }
    judgments: set[str] = set()
    if hasattr(store, "list_judgment_items"):
        for item in store.list_judgment_items(limit=10_000):  # type: ignore[attr-defined]
            status = getattr(item.status, "value", item.status)
            if status in ("active", "confirmed", "accepted"):
                judgments.add(item.id)
    return mems, judgments


def run_consolidation_cycle(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    *,
    kind: str = "daily",
    dry_run: bool = False,
    analyze_limit: int = 200,
    propose_judgment: Optional[bool] = None,
    as_of: Optional[datetime] = None,
    conflict_scan_limit: int = 2_000,
    retry: bool = False,
) -> ConsolidationCycleResult:
    """Run one daily or weekly consolidation cycle for the logical window.

    Stages:
      analyze → contradictions → safe_automation → temporal_refresh
      → (weekly) judgment_proposals → done

    Apply runs persist a ``ConsolidationRun`` keyed by window; repeats return
    the prior completed result (``duplicated=True``). Concurrent ``running``
    is blocked. Prior ``error`` requires ``retry=True`` to reclaim.
    """
    if kind not in ("daily", "weekly"):
        raise ValueError(f"unknown consolidation cycle kind: {kind!r}")
    if propose_judgment is None:
        propose_judgment = kind == "weekly"

    window_start, window_end = logical_window(kind, as_of=as_of)
    window_key = f"{kind}:{window_start}:{window_end}"

    prior = None
    if not dry_run and hasattr(store, "get_consolidation_run_for_window"):
        prior = store.get_consolidation_run_for_window(
            kind=kind, window_start=window_start, window_end=window_end, dry_run=False,
        )
        if prior is not None:
            if prior.status == "completed" and prior.payload:
                result = ConsolidationCycleResult.from_dict(prior.payload)
                result.duplicated = True
                result.run_id = prior.id
                result.status = "completed"
                return result
            if prior.status == "running":
                return ConsolidationCycleResult(
                    kind=kind,
                    dry_run=False,
                    run_id=prior.id,
                    window_start=window_start,
                    window_end=window_end,
                    duplicated=True,
                    status="running",
                    at=now_iso(),
                    stages=["blocked_concurrent"],
                    notes=["another consolidation run owns this window"],
                )
            if prior.status == "error" and not retry:
                result = ConsolidationCycleResult.from_dict(prior.payload) if prior.payload else ConsolidationCycleResult(
                    kind=kind, dry_run=False, run_id=prior.id,
                    window_start=window_start, window_end=window_end,
                )
                result.duplicated = True
                result.run_id = prior.id
                result.status = "error"
                result.error = prior.error
                result.error_stage = prior.error_stage
                result.notes = list(result.notes) + [
                    "prior cycle failed; pass retry=True to reclaim",
                ]
                return result

    run = ConsolidationRunRecord(
        kind=kind,
        window_start=window_start,
        window_end=window_end,
        dry_run=dry_run,
        status="running",
        started_at=now_iso(),
        error="",
        error_stage="",
    )
    created = True
    if not dry_run and prior is not None and prior.status == "error" and retry:
        claimed = False
        if hasattr(store, "try_claim_consolidation_retry"):
            claimed = store.try_claim_consolidation_retry(
                prior.id, started_at=now_iso(),
            )
        if not claimed:
            current = store.get_consolidation_run(prior.id) if hasattr(store, "get_consolidation_run") else prior
            if current is None:
                current = prior
            if current.status == "running":
                return ConsolidationCycleResult(
                    kind=kind, dry_run=False, run_id=current.id,
                    window_start=window_start, window_end=window_end,
                    duplicated=True, status="running", at=now_iso(),
                    stages=["blocked_concurrent"],
                    notes=["another consolidation run owns this window"],
                )
            if current.status == "completed" and current.payload:
                result = ConsolidationCycleResult.from_dict(current.payload)
                result.duplicated = True
                result.run_id = current.id
                result.status = "completed"
                return result
            result = ConsolidationCycleResult.from_dict(current.payload) if current.payload else ConsolidationCycleResult(
                kind=kind, dry_run=False, run_id=current.id,
                window_start=window_start, window_end=window_end,
            )
            result.duplicated = True
            result.run_id = current.id
            result.status = current.status
            result.notes = list(result.notes) + ["retry claim lost to another executor"]
            return result
        run = store.get_consolidation_run(prior.id)  # type: ignore[assignment]
        assert run is not None
        created = True
    elif not dry_run and hasattr(store, "try_begin_consolidation_run"):
        run, created = store.try_begin_consolidation_run(run)
        if not created and run.status == "completed" and run.payload:
            result = ConsolidationCycleResult.from_dict(run.payload)
            result.duplicated = True
            result.run_id = run.id
            result.status = "completed"
            return result
        if not created and run.status == "running":
            return ConsolidationCycleResult(
                kind=kind,
                dry_run=False,
                run_id=run.id,
                window_start=window_start,
                window_end=window_end,
                duplicated=True,
                status="running",
                at=now_iso(),
                stages=["blocked_concurrent"],
                notes=["another consolidation run owns this window"],
            )
        if not created and run.status == "error" and not retry:
            result = ConsolidationCycleResult.from_dict(run.payload) if run.payload else ConsolidationCycleResult(
                kind=kind, dry_run=False, run_id=run.id,
                window_start=window_start, window_end=window_end,
            )
            result.duplicated = True
            result.run_id = run.id
            result.status = "error"
            result.error = run.error
            result.error_stage = run.error_stage
            result.notes = list(result.notes) + [
                "prior cycle failed; pass retry=True to reclaim",
            ]
            return result
        if not created and run.status == "error" and retry:
            claimed = False
            if hasattr(store, "try_claim_consolidation_retry"):
                claimed = store.try_claim_consolidation_retry(
                    run.id, started_at=now_iso(),
                )
            if not claimed:
                current = store.get_consolidation_run(run.id) if hasattr(store, "get_consolidation_run") else run
                if current is None:
                    current = run
                if current.status == "running":
                    return ConsolidationCycleResult(
                        kind=kind, dry_run=False, run_id=current.id,
                        window_start=window_start, window_end=window_end,
                        duplicated=True, status="running", at=now_iso(),
                        stages=["blocked_concurrent"],
                        notes=["another consolidation run owns this window"],
                    )
                if current.status == "completed" and current.payload:
                    result = ConsolidationCycleResult.from_dict(current.payload)
                    result.duplicated = True
                    result.run_id = current.id
                    result.status = "completed"
                    return result
                result = ConsolidationCycleResult.from_dict(current.payload) if current.payload else ConsolidationCycleResult(
                    kind=kind, dry_run=False, run_id=current.id,
                    window_start=window_start, window_end=window_end,
                )
                result.duplicated = True
                result.run_id = current.id
                result.status = current.status
                result.notes = list(result.notes) + ["retry claim lost to another executor"]
                return result
            run = store.get_consolidation_run(run.id)  # type: ignore[assignment]
            assert run is not None
            created = True
    elif dry_run and hasattr(store, "insert_consolidation_run"):
        store.insert_consolidation_run(run)

    before_mems, before_judgments = _confirmed_snapshot(store)

    result = ConsolidationCycleResult(
        kind=kind,
        dry_run=dry_run,
        run_id=run.id,
        window_start=window_start,
        window_end=window_end,
        duplicated=not created,
        status="running",
        at=now_iso(),
    )
    stage = "analyze"

    try:
        result.stages.append("analyze")
        if not dry_run:
            reports = analyze_candidates(store, embedder, limit=analyze_limit)
            result.analyzed = len(reports)
        else:
            queue = store.list_memories(status="candidate", needs_review=True, limit=analyze_limit)
            if not queue:
                queue = store.list_memories(status="candidate", limit=analyze_limit)
            result.analyzed = len(queue)
            result.notes.append("dry_run skipped quality analyzer writes")

        stage = "contradictions"
        result.stages.append("contradictions")
        conflict_ids: list[str] = []
        scanned = store.list_memories(limit=conflict_scan_limit)
        if len(scanned) >= conflict_scan_limit:
            result.truncated = True
            result.notes.append(
                f"conflict inventory truncated at {conflict_scan_limit} (not silent full scan)"
            )
        for mem in scanned:
            if "possible_conflict" in (mem.quality_flags or []):
                conflict_ids.append(mem.id)
        result.contradiction_memory_ids = conflict_ids

        stage = "safe_automation"
        result.stages.append("safe_automation")
        result.automation = apply_safe_automations(store, dry_run=dry_run)

        stage = "temporal_refresh"
        result.stages.append("temporal_refresh")
        updates, goals, belief_trunc = refresh_temporal_beliefs_and_goals(
            store, dry_run=dry_run, as_of=as_of,
        )
        result.temporal_updates = updates
        result.goals_observed = goals
        if belief_trunc:
            result.truncated = True
            result.notes.append("belief temporal refresh page truncated")

        if propose_judgment:
            stage = "judgment_proposals"
            result.stages.append("judgment_proposals")
            from ..judgment.proposals import propose_from_pattern
            detector = "simplicity_cluster_demo"
            if dry_run:
                result.notes.append("dry_run skipped judgment proposals")
            else:
                existing = _existing_window_proposals(
                    store, window_key=window_key, detector=detector,
                )
                if existing:
                    result.judgment_proposal_ids = existing
                    result.notes.append("reused judgment proposals for window")
                else:
                    proposals = propose_from_pattern(store, domain="technical")
                    for p in proposals:
                        meta = dict(getattr(p, "metadata", None) or {})
                        meta["consolidation_window"] = window_key
                        meta["consolidation_run_id"] = run.id
                        meta.setdefault("detector", detector)
                        if hasattr(store, "update_judgment_proposal"):
                            store.update_judgment_proposal(p.id, metadata=meta)
                        result.judgment_proposal_ids.append(p.id)

        stage = "invariant"
        result.stages.append("done")

        after_mems, after_judgments = _confirmed_snapshot(store)
        if after_mems != before_mems or after_judgments != before_judgments:
            raise ConsolidationInvariantError(
                "cycle mutated confirmed Memory/Judgment set"
            )
        result.notes.append(
            "invariant_ok: confirmed Memory/Judgment sets unchanged"
        )
        result.status = "completed"

        run.status = "completed"
        run.completed_at = now_iso()
        run.error = ""
        run.error_stage = ""
        run.payload = result.to_dict()
        if hasattr(store, "update_consolidation_run"):
            store.update_consolidation_run(run)
        return result
    except Exception as exc:
        run.status = "error"
        run.error = sanitize_error(exc)
        run.error_stage = stage
        run.completed_at = now_iso()
        result.status = "error"
        result.error = run.error
        result.error_stage = stage
        result.stages = list(result.stages) + ["error"]
        result.notes.append(f"failed at {stage}: {type(exc).__name__}")
        run.payload = result.to_dict()
        if hasattr(store, "update_consolidation_run"):
            store.update_consolidation_run(run)
        raise
