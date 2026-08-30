"""Consolidation caps + Narrative auto-commit invariant."""

from __future__ import annotations

from twin.cognize.services.consolidation_cycle import (
    MAX_JUDGMENT_DRAFTS_PER_WINDOW,
    run_consolidation_cycle,
)


def test_weekly_cycle_never_auto_commits_narrative(store, cfg, embedder):
    before = (
        {n.id for n in store.list_narratives("default")}
        if hasattr(store, "list_narratives")
        else set()
    )
    result = run_consolidation_cycle(
        store, cfg, embedder, kind="weekly", dry_run=True,
    )
    assert "fade_recommend" in result.stages
    after = (
        {n.id for n in store.list_narratives("default")}
        if hasattr(store, "list_narratives")
        else set()
    )
    assert after == before
    assert any("invariant_ok" in n for n in result.notes)


def test_judgment_draft_cap_constant():
    assert MAX_JUDGMENT_DRAFTS_PER_WINDOW > 0
    assert MAX_JUDGMENT_DRAFTS_PER_WINDOW <= 50
