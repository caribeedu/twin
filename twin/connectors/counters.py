"""Durable cumulative connector counters (Phase 9 — exactly-once per batch).

Each terminal batch contributes to ``ConnectorSyncState`` counters **at most
once**, gated by the ``connector_counter_batches`` ledger
(PRIMARY KEY connector_id, batch_id).

```text
batch reaches terminal status
→ claim ledger row (INSERT … unique)
→ if claimed: bump counters in the same transaction
→ retry / crash / second worker: claim fails → no bump
```

``reconcile_connector_counters`` finds uncounted terminal batches after a
crash and can repair divergence against the batch ledger (source of truth).
"""

from __future__ import annotations

from typing import Any, Optional

from ..clock import now_iso
from .models import BatchStatus, ConnectorBatch, ConnectorSyncState, FailureClass


_TERMINAL_FAIL = frozenset({
    BatchStatus.failed,
    BatchStatus.partially_failed,
    BatchStatus.aborted,
    BatchStatus.failed.value,
    BatchStatus.partially_failed.value,
    BatchStatus.aborted.value,
})

_TERMINAL = _TERMINAL_FAIL | {
    BatchStatus.committed,
    BatchStatus.committed.value,
}


def _status_val(status) -> str:
    return getattr(status, "value", status)


def is_terminal_batch(batch: ConnectorBatch) -> bool:
    return _status_val(batch.status) in _TERMINAL


def _page_all_batches(store, connector_id: str) -> list[ConnectorBatch]:
    if hasattr(store, "list_all_connector_batches"):
        return store.list_all_connector_batches(connector_id)
    return list(store.list_connector_batches(connector_id, limit=1_000_000))


def batch_contribution(
    batch: ConnectorBatch,
    *,
    deletion_events: int = 0,
    rate_limited: bool = False,
) -> dict[str, int]:
    """Numeric contribution of one terminal batch (for ledger + bump)."""
    st = _status_val(batch.status)
    failed = st in _TERMINAL_FAIL
    fc = getattr(batch, "failure_class", None)
    fc_val = getattr(fc, "value", fc)
    limited = rate_limited or fc_val in (
        FailureClass.rate_limit, FailureClass.rate_limit.value,
    )
    meta = getattr(batch, "metadata", None) or {}
    if meta.get("rate_limit_wait_seconds") or meta.get("rate_limited"):
        limited = True
    return {
        "fetch": int(batch.raw_count or 0),
        "normalized": int(batch.normalized_count or 0),
        "deduplicated": int(getattr(batch, "deduplicated_count", 0) or 0),
        "quarantined": int(batch.quarantined_count or 0),
        "percepts": int(batch.percept_count or 0),
        "failed_batch": 1 if failed else 0,
        "rate_limit_wait": 1 if limited else 0,
        "deletion_events": int(deletion_events or 0),
    }


def sum_batch_totals(batches: list[ConnectorBatch]) -> dict[str, int]:
    totals = {
        "fetch_total": 0,
        "failed_batches_total": 0,
        "normalized_total": 0,
        "deduplicated_total": 0,
        "quarantined_total": 0,
        "percepts_total": 0,
        "rate_limit_wait_total": 0,
        "deletion_events_total": 0,
    }
    for b in batches:
        if not is_terminal_batch(b):
            continue
        c = batch_contribution(b)
        totals["fetch_total"] += c["fetch"]
        totals["normalized_total"] += c["normalized"]
        totals["deduplicated_total"] += c["deduplicated"]
        totals["quarantined_total"] += c["quarantined"]
        totals["percepts_total"] += c["percepts"]
        totals["failed_batches_total"] += c["failed_batch"]
        totals["rate_limit_wait_total"] += c["rate_limit_wait"]
        # deletion_events are not on the batch row — filled by reconcile
    return totals


def _bump_state(state: ConnectorSyncState, contrib: dict[str, int]) -> None:
    state.fetch_total += int(contrib.get("fetch", 0))
    state.normalized_total += int(contrib.get("normalized", 0))
    state.deduplicated_total += int(contrib.get("deduplicated", 0))
    state.quarantined_total += int(contrib.get("quarantined", 0))
    state.percepts_total += int(contrib.get("percepts", 0))
    state.failed_batches_total += int(contrib.get("failed_batch", 0))
    state.rate_limit_wait_total += int(contrib.get("rate_limit_wait", 0))
    state.deletion_events_total += int(contrib.get("deletion_events", 0))
    state.counters_initialized = True


def record_batch_counters(
    store,
    connector_id: str,
    batch: ConnectorBatch,
    *,
    deletion_events: int = 0,
    rate_limited: bool = False,
) -> ConnectorSyncState:
    """Apply one terminal batch's contribution exactly once.

    Ledger claim + counter bump run in one transaction. Retries and concurrent
    workers that lose the claim are no-ops.
    """
    if not is_terminal_batch(batch):
        state = store.get_connector_sync_state(connector_id)
        return state or store.apply_connector_sync_state(
            connector_id, lambda s: None,
        )

    contrib = batch_contribution(
        batch, deletion_events=deletion_events, rate_limited=rate_limited,
    )

    with store.transaction():
        claimed = store.claim_connector_counter_batch(
            connector_id, batch.id, contrib,
        )
        if not claimed:
            state = store.get_connector_sync_state(connector_id)
            if state is not None:
                return state
            # ledger says counted but sync state missing — repair path later
            return store.apply_connector_sync_state(connector_id, lambda s: None)

        def _apply(state: ConnectorSyncState) -> None:
            _bump_state(state, contrib)

        return store.apply_connector_sync_state(connector_id, _apply)


def expected_totals(store, connector_id: str) -> dict[str, int]:
    """Source-of-truth totals from every terminal batch + deletion events."""
    batches = _page_all_batches(store, connector_id)
    totals = sum_batch_totals(batches)
    if hasattr(store, "list_connector_deletion_events"):
        totals["deletion_events_total"] = len(
            store.list_connector_deletion_events(connector_id)
        )
    return totals


def _state_totals(state: Optional[ConnectorSyncState]) -> dict[str, int]:
    if state is None:
        return {
            "fetch_total": 0,
            "failed_batches_total": 0,
            "normalized_total": 0,
            "deduplicated_total": 0,
            "quarantined_total": 0,
            "percepts_total": 0,
            "rate_limit_wait_total": 0,
            "deletion_events_total": 0,
        }
    return {
        "fetch_total": int(state.fetch_total),
        "failed_batches_total": int(state.failed_batches_total),
        "normalized_total": int(state.normalized_total),
        "deduplicated_total": int(state.deduplicated_total),
        "quarantined_total": int(state.quarantined_total),
        "percepts_total": int(state.percepts_total),
        "rate_limit_wait_total": int(state.rate_limit_wait_total),
        "deletion_events_total": int(state.deletion_events_total),
    }


def reconcile_connector_counters(
    store,
    connector_id: str,
    *,
    apply_missing: bool = True,
    repair: bool = True,
) -> dict[str, Any]:
    """Ensure every terminal batch is ledger-counted; optionally repair state.

    1. If ``apply_missing``: claim+bump terminal batches missing from the ledger
       (crash recovery).
    2. Compare persisted counters to batch-derived expected totals.
    3. If ``repair`` and still diverged (e.g. historical double-count), reset
       counters to expected and audit the correction in sync-state metadata.
       This is the only path that may lower a counter — never silent.

    Doctor uses ``apply_missing=False, repair=False`` (read-only detect).
    """
    batches = [b for b in _page_all_batches(store, connector_id)
               if is_terminal_batch(b)]
    claimed = set()
    if hasattr(store, "list_connector_counter_batch_ids"):
        claimed = set(store.list_connector_counter_batch_ids(connector_id))

    uncounted = [b for b in batches if b.id not in claimed]
    applied_missing = 0
    if apply_missing:
        for batch in uncounted:
            record_batch_counters(store, connector_id, batch)
            if store.connector_counter_batch_claimed(connector_id, batch.id):
                applied_missing += 1
                claimed.add(batch.id)

    expected = expected_totals(store, connector_id)
    state = store.get_connector_sync_state(connector_id)
    actual = _state_totals(state)
    diverged = {k: (actual[k], expected[k])
                for k in expected if actual.get(k, 0) != expected[k]}
    # Uncounted batches are a divergence even before comparing totals
    if uncounted and not apply_missing:
        diverged = dict(diverged)
        diverged["uncounted_batches"] = (len(uncounted), 0)

    repaired = False
    if diverged and repair:
        def _reset(s: ConnectorSyncState) -> None:
            s.fetch_total = expected["fetch_total"]
            s.failed_batches_total = expected["failed_batches_total"]
            s.normalized_total = expected["normalized_total"]
            s.deduplicated_total = expected["deduplicated_total"]
            s.quarantined_total = expected["quarantined_total"]
            s.percepts_total = expected["percepts_total"]
            s.rate_limit_wait_total = expected["rate_limit_wait_total"]
            s.deletion_events_total = expected["deletion_events_total"]
            s.counters_initialized = True
            meta = dict(s.metadata or {})
            audit = list(meta.get("counter_reconcile_audit") or [])
            audit.append({
                "at": now_iso(),
                "reason": "repair_to_batch_truth",
                "before": actual,
                "after": expected,
                "diverged_keys": sorted(diverged),
            })
            meta["counter_reconcile_audit"] = audit[-20:]  # cap history
            s.metadata = meta

        state = store.apply_connector_sync_state(connector_id, _reset)
        repaired = True
        # ensure ledger rows exist for every terminal batch (no second bump)
        for batch in batches:
            if not store.connector_counter_batch_claimed(connector_id, batch.id):
                store.claim_connector_counter_batch(
                    connector_id, batch.id, batch_contribution(batch),
                )
        actual = _state_totals(state)
        diverged = {k: (actual[k], expected[k])
                    for k in expected if actual.get(k, 0) != expected[k]}
    elif state is None or not state.counters_initialized:
        def _init(s: ConnectorSyncState) -> None:
            s.counters_initialized = True
        state = store.apply_connector_sync_state(connector_id, _init)

    return {
        "connector_id": connector_id,
        "batches_terminal": len(batches),
        "ledger_size": len(claimed),
        "applied_missing": applied_missing,
        "expected": expected,
        "actual": actual,
        "diverged": diverged,
        "ok": not diverged,
        "repaired": repaired,
    }


def seed_counters_from_batches(store, connector_id: str) -> ConnectorSyncState:
    """Back-compat entry: reconcile with repair (idempotent)."""
    reconcile_connector_counters(store, connector_id, repair=True)
    return (store.get_connector_sync_state(connector_id)
            or store.apply_connector_sync_state(connector_id, lambda s: None))


def ensure_counters(store, connector_id: str) -> ConnectorSyncState:
    """Always recover missing ledger contributions (even if initialized)."""
    reconcile_connector_counters(store, connector_id, repair=True)
    return (store.get_connector_sync_state(connector_id)
            or store.apply_connector_sync_state(connector_id, lambda s: None))


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
