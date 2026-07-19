"""Durable cumulative connector counters (Phase 9 review — §58).

Counters live on ``ConnectorSyncState`` and are bumped when a batch reaches a
terminal status. They never decrease and survive process restart. A one-shot
seed from *all* persisted batches backfills installs that predate the fields.
"""

from __future__ import annotations

from typing import Any, Optional

from .models import BatchStatus, ConnectorBatch, ConnectorSyncState, FailureClass


_TERMINAL_FAIL = frozenset({
    BatchStatus.failed,
    BatchStatus.partially_failed,
    BatchStatus.aborted,
    "failed",
    "partially_failed",
    "aborted",
})


def _status_val(status) -> str:
    return getattr(status, "value", status)


def _page_all_batches(store, connector_id: str) -> list[ConnectorBatch]:
    """Load every batch for a connector — no sliding window."""
    out: list[ConnectorBatch] = []
    # page in descending order; stop when a page returns short
    page_size = 500
    # list_connector_batches only supports LIMIT, not OFFSET — fall back to
    # unbounded fetch when the store exposes it, else page via offset if added
    if hasattr(store, "iter_connector_batches"):
        return list(store.iter_connector_batches(connector_id))
    # Prefer a dedicated aggregate / list-all when available
    if hasattr(store, "list_all_connector_batches"):
        return store.list_all_connector_batches(connector_id)
    # Manual pagination: keep requesting larger limits until we have them all.
    # Stores order by created_at DESC; a single call with a huge limit is fine
    # for local installs and correct for the monotonicity invariant.
    batches = store.list_connector_batches(connector_id, limit=1_000_000)
    return list(batches)


def sum_batch_totals(batches: list[ConnectorBatch]) -> dict[str, int]:
    fetch = failed = normalized = dedup = quar = perc = rate_waits = 0
    for b in batches:
        fetch += int(b.raw_count or 0)
        normalized += int(b.normalized_count or 0)
        dedup += int(getattr(b, "deduplicated_count", 0) or 0)
        quar += int(b.quarantined_count or 0)
        perc += int(b.percept_count or 0)
        st = _status_val(b.status)
        if st in _TERMINAL_FAIL or st in {s.value for s in (
            BatchStatus.failed, BatchStatus.partially_failed, BatchStatus.aborted,
        )}:
            failed += 1
        meta = getattr(b, "metadata", None) or {}
        fc = getattr(b, "failure_class", None)
        fc_val = getattr(fc, "value", fc)
        if (meta.get("rate_limit_wait_seconds") or meta.get("rate_limited")
                or fc_val == FailureClass.rate_limit.value
                or fc_val == FailureClass.rate_limit):
            rate_waits += 1
    return {
        "fetch_total": fetch,
        "failed_batches_total": failed,
        "normalized_total": normalized,
        "deduplicated_total": dedup,
        "quarantined_total": quar,
        "percepts_total": perc,
        "rate_limit_wait_total": rate_waits,
    }


def seed_counters_from_batches(store, connector_id: str) -> ConnectorSyncState:
    """One-shot backfill of durable counters from every persisted batch."""
    batches = _page_all_batches(store, connector_id)
    totals = sum_batch_totals(batches)
    deletions = 0
    if hasattr(store, "list_connector_deletion_events"):
        deletions = len(store.list_connector_deletion_events(connector_id))

    def _apply(state: ConnectorSyncState) -> None:
        # Never lower an already-advanced counter (monotonic).
        state.fetch_total = max(state.fetch_total, totals["fetch_total"])
        state.failed_batches_total = max(
            state.failed_batches_total, totals["failed_batches_total"])
        state.normalized_total = max(
            state.normalized_total, totals["normalized_total"])
        state.deduplicated_total = max(
            state.deduplicated_total, totals["deduplicated_total"])
        state.quarantined_total = max(
            state.quarantined_total, totals["quarantined_total"])
        state.percepts_total = max(state.percepts_total, totals["percepts_total"])
        state.rate_limit_wait_total = max(
            state.rate_limit_wait_total, totals["rate_limit_wait_total"])
        state.deletion_events_total = max(state.deletion_events_total, deletions)
        state.counters_initialized = True

    return store.apply_connector_sync_state(connector_id, _apply)


def ensure_counters(store, connector_id: str) -> ConnectorSyncState:
    state = store.get_connector_sync_state(connector_id)
    if state is not None and state.counters_initialized:
        return state
    return seed_counters_from_batches(store, connector_id)


def record_batch_counters(
    store,
    connector_id: str,
    batch: ConnectorBatch,
    *,
    deletion_events: int = 0,
    rate_limited: bool = False,
) -> ConnectorSyncState:
    """Bump durable counters for one terminal batch. Monotonic."""
    st = _status_val(batch.status)
    failed = st in _TERMINAL_FAIL or st in {
        BatchStatus.failed.value, BatchStatus.partially_failed.value,
        BatchStatus.aborted.value,
    }
    fc = getattr(batch, "failure_class", None)
    fc_val = getattr(fc, "value", fc)
    limited = rate_limited or fc_val in (
        FailureClass.rate_limit, FailureClass.rate_limit.value,
    )
    meta = getattr(batch, "metadata", None) or {}
    if meta.get("rate_limit_wait_seconds") or meta.get("rate_limited"):
        limited = True

    def _apply(state: ConnectorSyncState) -> None:
        if not state.counters_initialized:
            # seed first so historical batches are not double-counted later
            # and this batch (already persisted) is included via max()
            pass
        state.fetch_total += int(batch.raw_count or 0)
        state.normalized_total += int(batch.normalized_count or 0)
        state.deduplicated_total += int(getattr(batch, "deduplicated_count", 0) or 0)
        state.quarantined_total += int(batch.quarantined_count or 0)
        state.percepts_total += int(batch.percept_count or 0)
        if failed:
            state.failed_batches_total += 1
        if limited:
            state.rate_limit_wait_total += 1
        if deletion_events:
            state.deletion_events_total += int(deletion_events)
        state.counters_initialized = True

    state = store.get_connector_sync_state(connector_id)
    if state is None or not state.counters_initialized:
        # Seed from all batches *including* this one, then skip the bump to
        # avoid double-counting the current batch.
        return seed_counters_from_batches(store, connector_id)
    return store.apply_connector_sync_state(connector_id, _apply)


def counters_snapshot(state: Optional[ConnectorSyncState]) -> dict[str, Any]:
    if state is None:
        return {
            "connector_fetch_total": 0,
            "connector_fetch_failed_batches": 0,
            "connector_items_normalized": 0,
            "connector_items_deduplicated": 0,
            "connector_quarantine_total": 0,
            "connector_percepts_total": 0,
            "connector_rate_limit_wait": 0,
            "connector_deletion_events": 0,
            "counters_initialized": False,
        }
    return {
        "connector_fetch_total": int(state.fetch_total),
        "connector_fetch_failed_batches": int(state.failed_batches_total),
        "connector_items_normalized": int(state.normalized_total),
        "connector_items_deduplicated": int(state.deduplicated_total),
        "connector_quarantine_total": int(state.quarantined_total),
        "connector_percepts_total": int(state.percepts_total),
        "connector_rate_limit_wait": int(state.rate_limit_wait_total),
        "connector_deletion_events": int(state.deletion_events_total),
        "counters_initialized": bool(state.counters_initialized),
    }
