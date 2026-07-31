"""Daily/weekly consolidation cycles (twin.cognition.consolidation_cycle)."""

from datetime import datetime, timedelta, timezone

import pytest

from twin import ids
from twin.cognition.consolidation_cycle import (
    refresh_temporal_beliefs_and_goals,
    run_consolidation_cycle,
)
from twin.cognition.sessions import ensure_project
from twin.memory.models import MemoryItem, MemoryStatus


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


def _confirmed_ids(store):
    return {m.id for m in store.list_memories(status="confirmed", limit=10_000)}


def test_temporal_refresh_flags_expired_belief(store, embedder):
    past = (datetime.now(timezone.utc) - timedelta(days=10)).date().isoformat()
    mem = _belief(store, embedder, valid_until=past)
    updates, _goals, _trunc = refresh_temporal_beliefs_and_goals(store, dry_run=False)
    assert any(u["memory_id"] == mem.id for u in updates)
    refreshed = store.get_memory(mem.id)
    assert refreshed.needs_review is True
    assert "stale" in (refreshed.quality_flags or [])
    assert refreshed.status == MemoryStatus.confirmed


def test_daily_cycle_dry_run_no_writes(store, cfg, embedder):
    past = (datetime.now(timezone.utc) - timedelta(days=10)).date().isoformat()
    mem = _belief(store, embedder, valid_until=past)
    before = _confirmed_ids(store)
    result = run_consolidation_cycle(
        store, cfg, embedder, kind="daily", dry_run=True,
    )
    assert result.kind == "daily"
    assert result.dry_run is True
    assert "analyze" in result.stages
    assert "temporal_refresh" in result.stages
    assert "episode_cortex" in result.stages
    assert result.episode_cognition.get("dry_run") is True
    assert "episode_reflect" in result.stages
    assert "judgment_proposals" not in result.stages
    assert store.get_memory(mem.id).needs_review is False
    assert _confirmed_ids(store) == before
    assert any("invariant_ok" in n for n in result.notes)


def test_weekly_cycle_includes_judgment_stage(store, cfg, embedder):
    project = ensure_project(store, "Atlas")
    project.goals = ["Ship v0.8"]
    store.update_project(project)
    result = run_consolidation_cycle(
        store, cfg, embedder, kind="weekly", dry_run=True,
    )
    assert "episode_cortex" in result.stages
    assert "episode_reflect" in result.stages
    assert "judgment_proposals" in result.stages
    assert any(g["project_id"] == project.id for g in result.goals_observed)
    assert any("invariant_ok" in n for n in result.notes)


def test_weekly_rerun_does_not_duplicate_judgment_proposals(store, cfg, embedder):
    as_of = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
    first = run_consolidation_cycle(
        store, cfg, embedder, kind="weekly", dry_run=False, as_of=as_of,
    )
    second = run_consolidation_cycle(
        store, cfg, embedder, kind="weekly", dry_run=False, as_of=as_of,
    )
    assert second.duplicated is True
    assert second.run_id == first.run_id
    proposals = store.list_judgment_proposals(limit=500)
    # At most one simplicity detector proposal for this window (0 if no cluster).
    detectors = [
        p for p in proposals
        if (p.metadata or {}).get("detector") == "simplicity_cluster_demo"
        and (p.metadata or {}).get("consolidation_window", "").startswith("weekly:")
    ]
    assert len(detectors) <= 1


def test_concurrent_cycle_window_has_single_run(store, cfg, embedder):
    as_of = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    a = run_consolidation_cycle(
        store, cfg, embedder, kind="daily", dry_run=False, as_of=as_of,
    )
    b = run_consolidation_cycle(
        store, cfg, embedder, kind="daily", dry_run=False, as_of=as_of,
    )
    assert a.run_id
    assert b.duplicated is True
    assert b.run_id == a.run_id
    runs = []
    # one apply row for the window
    row = store.get_consolidation_run_for_window(
        kind="daily",
        window_start=a.window_start,
        window_end=a.window_end,
        dry_run=False,
    )
    assert row is not None
    assert row.id == a.run_id


def test_cycle_never_confirms_memory_or_judgment(store, cfg, embedder):
    cand = MemoryItem(
        id=ids.memory_id(), type="fact", title="Candidate only",
        summary="Must stay candidate through consolidation.",
        domain="technical", confidence=0.8, status="candidate",
        needs_review=True,
    )
    store.insert_memory(cand)
    before_confirmed = _confirmed_ids(store)
    result = run_consolidation_cycle(
        store, cfg, embedder, kind="daily", dry_run=False,
        as_of=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    assert store.get_memory(cand.id).status == MemoryStatus.candidate
    assert _confirmed_ids(store) == before_confirmed
    assert any("invariant_ok" in n for n in result.notes)


def test_cycle_invariant_violation_fails_run(store, cfg, embedder, monkeypatch):
    from twin.cognition.consolidation_cycle import ConsolidationInvariantError

    as_of = datetime(2026, 8, 1, tzinfo=timezone.utc)

    def poison_snapshot(store):
        # first call = before, second = after with an extra fake id
        if not hasattr(poison_snapshot, "n"):
            poison_snapshot.n = 0
        poison_snapshot.n += 1
        if poison_snapshot.n == 1:
            return set(), set()
        return {"mem_fake_confirmed"}, set()

    monkeypatch.setattr(
        "twin.cognition.consolidation_cycle._confirmed_snapshot",
        poison_snapshot,
    )
    with pytest.raises(ConsolidationInvariantError):
        run_consolidation_cycle(
            store, cfg, embedder, kind="daily", dry_run=False, as_of=as_of,
        )
    row = store.get_consolidation_run_for_window(
        kind="daily",
        window_start=as_of.date().isoformat(),
        window_end=as_of.date().isoformat(),
        dry_run=False,
    )
    assert row is not None
    assert row.status == "error"
    assert row.error_stage == "invariant"
    assert "ConsolidationInvariantError" in row.error

    # without retry, stuck on error
    blocked = run_consolidation_cycle(
        store, cfg, embedder, kind="daily", dry_run=False, as_of=as_of,
    )
    assert blocked.status == "error"
    assert blocked.duplicated is True


def test_consolidation_retry_claim_blocks_second_executor(store, cfg, embedder, monkeypatch):
    as_of = datetime(2026, 11, 1, tzinfo=timezone.utc)

    def boom(*_a, **_k):
        raise RuntimeError("analyze boom")

    monkeypatch.setattr(
        "twin.cognition.consolidation_cycle.analyze_candidates", boom,
    )
    with pytest.raises(RuntimeError):
        run_consolidation_cycle(
            store, cfg, embedder, kind="daily", dry_run=False, as_of=as_of,
        )
    row = store.get_consolidation_run_for_window(
        kind="daily",
        window_start=as_of.date().isoformat(),
        window_end=as_of.date().isoformat(),
        dry_run=False,
    )
    assert row is not None and row.status == "error"
    assert store.try_claim_consolidation_retry(row.id) is True
    second = run_consolidation_cycle(
        store, cfg, embedder, kind="daily", dry_run=False, as_of=as_of, retry=True,
    )
    assert second.duplicated is True
    assert second.stages == ["blocked_concurrent"]


def test_consolidation_retry_can_complete_after_transient_failure(store, cfg, embedder, monkeypatch):
    as_of = datetime(2026, 12, 1, tzinfo=timezone.utc)
    blows = {"n": 0}

    def flaky_analyze(*_a, **_k):
        blows["n"] += 1
        if blows["n"] == 1:
            raise RuntimeError("transient analyze")
        return []

    monkeypatch.setattr(
        "twin.cognition.consolidation_cycle.analyze_candidates",
        flaky_analyze,
    )
    with pytest.raises(RuntimeError):
        run_consolidation_cycle(
            store, cfg, embedder, kind="daily", dry_run=False, as_of=as_of,
        )
    ok = run_consolidation_cycle(
        store, cfg, embedder, kind="daily", dry_run=False, as_of=as_of, retry=True,
    )
    assert ok.status == "completed"
    assert ok.error == ""
    assert any("invariant_ok" in n for n in ok.notes)
    row = store.get_consolidation_run(ok.run_id)
    assert row.status == "completed"
    assert row.error == ""


def test_operational_stages_and_replay_report(store, cfg, embedder):
    from twin.cognition.sessions import start_session, complete_session

    started = start_session(store, cfg, embedder, "consolidate me", client="cli")
    complete_session(store, cfg, embedder, started.session.id, summary="shipped runtime")
    cand = MemoryItem(
        id=ids.memory_id(), type="task", title="Open task",
        summary="Still pending work",
        domain="technical", confidence=0.7, status="candidate",
        needs_review=True, review_reason="needs human",
    )
    store.insert_memory(cand)

    as_of = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    first = run_consolidation_cycle(
        store, cfg, embedder, kind="daily", dry_run=False, as_of=as_of,
    )
    assert "closed_sessions" in first.stages
    assert "open_tasks" in first.stages
    assert "review_prepare" in first.stages
    assert "change_report" in first.stages
    assert any(s["session_id"] == started.session.id for s in first.closed_sessions)
    assert any(t["memory_id"] == cand.id for t in first.open_tasks)
    assert first.cognitive_change_report.get("kind") == "daily"
    assert "no Memory/Judgment confirmation" in " ".join(
        first.cognitive_change_report.get("notes") or [],
    )
    # review stamp
    assert (store.get_memory(cand.id).payload or {}).get("formation_state") == "awaiting_review"

    second = run_consolidation_cycle(
        store, cfg, embedder, kind="daily", dry_run=False, as_of=as_of,
    )
    assert second.duplicated is True
    assert second.cognitive_change_report == first.cognitive_change_report
    assert second.closed_sessions == first.closed_sessions
