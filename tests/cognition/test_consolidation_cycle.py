"""Daily/weekly consolidation cycles (twin.cognition.consolidation_cycle)."""

from datetime import datetime, timedelta, timezone

from twin import ids
from twin.cognition.consolidation_cycle import (
    refresh_temporal_beliefs_and_goals,
    run_consolidation_cycle,
)
from twin.cognition.sessions import ensure_project
from twin.memory.models import MemoryItem


def _belief(store, embedder, **kw):
    base = dict(
        id=ids.memory_id(), type="belief",
        title="Local-first storage",
        summary="Prefer local SQLite before shared infra.",
        domain="technical", confidence=0.85, status="confirmed",
    )
    base.update(kw)
    mem = MemoryItem(**base)
    store.insert_memory(mem)
    store.store_embedding(
        mem.id, "memory", embedder.name,
        embedder.embed(f"{mem.title}\n{mem.summary}"),
    )
    return mem


def test_temporal_refresh_flags_expired_belief(store, embedder):
    past = (datetime.now(timezone.utc) - timedelta(days=10)).date().isoformat()
    mem = _belief(store, embedder, valid_until=past)
    updates, _goals = refresh_temporal_beliefs_and_goals(store, dry_run=False)
    assert any(u["memory_id"] == mem.id for u in updates)
    refreshed = store.get_memory(mem.id)
    assert refreshed.needs_review is True
    assert "stale" in (refreshed.quality_flags or [])
    assert refreshed.status.value == "confirmed"


def test_daily_cycle_dry_run_no_writes(store, cfg, embedder):
    past = (datetime.now(timezone.utc) - timedelta(days=10)).date().isoformat()
    mem = _belief(store, embedder, valid_until=past)
    result = run_consolidation_cycle(
        store, cfg, embedder, kind="daily", dry_run=True,
    )
    assert result.kind == "daily"
    assert result.dry_run is True
    assert "analyze" in result.stages
    assert "temporal_refresh" in result.stages
    assert "judgment_proposals" not in result.stages
    # dry-run must not flag the belief
    assert store.get_memory(mem.id).needs_review is False


def test_weekly_cycle_includes_judgment_stage(store, cfg, embedder):
    project = ensure_project(store, "Atlas")
    project.goals = ["Ship v0.8"]
    store.update_project(project)
    result = run_consolidation_cycle(
        store, cfg, embedder, kind="weekly", dry_run=True,
    )
    assert "judgment_proposals" in result.stages
    assert any(g["project_id"] == project.id for g in result.goals_observed)
    assert any("never confirms" in n for n in result.notes)
