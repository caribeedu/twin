"""Atomic retry claims for workspace ticks / consolidation runs."""

from twin.clock import now_iso
from twin.memory.store.workspace_ops_mixin import (
    ConsolidationRunRecord,
    WorkspaceTickRecord,
)


def test_only_one_workspace_retry_claim_succeeds(store):
    tick = WorkspaceTickRecord(
        session_id="ses_cas",
        sequence=1,
        content_hash="abc",
        input_mode="delta",
        interpret=True,
        status="error",
        error="RuntimeError: boom",
        error_stage="observe",
        started_at=now_iso(),
        completed_at=now_iso(),
    )
    store.insert_workspace_tick(tick)

    first = store.try_claim_workspace_tick_retry(tick.id, started_at=now_iso())
    second = store.try_claim_workspace_tick_retry(tick.id, started_at=now_iso())
    assert first is True
    assert second is False
    claimed = store.get_workspace_tick(tick.id)
    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.error == ""
    assert claimed.error_stage == ""


def test_only_one_consolidation_retry_claim_succeeds(store):
    run = ConsolidationRunRecord(
        kind="daily",
        window_start="2026-10-01",
        window_end="2026-10-01",
        dry_run=False,
        status="error",
        error="RuntimeError: boom",
        error_stage="analyze",
        started_at=now_iso(),
        completed_at=now_iso(),
    )
    store.insert_consolidation_run(run)

    first = store.try_claim_consolidation_retry(run.id, started_at=now_iso())
    second = store.try_claim_consolidation_retry(run.id, started_at=now_iso())
    assert first is True
    assert second is False
    claimed = store.get_consolidation_run(run.id)
    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.error == ""
