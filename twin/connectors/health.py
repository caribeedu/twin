"""Connector health aggregation.

Health is derived from the last batch, checkpoint freshness, dead-letter depth
and auth state — never from a single boolean. Stored on ``ConnectorSyncState``
so the CLI/API/MCP can read it without re-running a sync.

Phase 9 (§57): snapshots expose ``lag_seconds``, ``pending_items``,
``last_checkpoint_at`` and ``rate_limit_remaining`` alongside status.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from ..clock import now_iso
from .models import (
    BatchStatus,
    ConnectorSyncState,
    HealthStatus,
)


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _compute_lag_seconds(state: Optional[ConnectorSyncState],
                         last_checkpoint_at: Optional[str]) -> int:
    """Seconds since last durable progress (checkpoint, else success)."""
    if state is not None and int(state.lag_seconds or 0) > 0:
        # keep an explicitly set lag unless we can compute fresher from timestamps
        stored = int(state.lag_seconds)
    else:
        stored = 0
    ref = last_checkpoint_at or (state.last_success_at if state else None)
    parsed = _parse_ts(ref)
    if parsed is None:
        return stored
    age = int((datetime.now(timezone.utc) - parsed).total_seconds())
    return max(0, age, stored)


def _pending_items(store, connector_id: str, state: Optional[ConnectorSyncState]) -> int:
    """Open DLQ + durable pending hint queues (never content)."""
    dead = len(store.list_connector_dead_letters(connector_id, status="open"))
    meta = (state.metadata or {}) if state else {}
    hints = 0
    for key in ("pending_threads", "pending_message_refreshes",
                "pending_tombstones", "pending_transcripts", "targeted_streams"):
        val = meta.get(key)
        if isinstance(val, list):
            hints += len(val)
        elif isinstance(val, dict):
            hints += len(val)
    if state is not None and int(state.pending_items or 0) > dead + hints:
        return int(state.pending_items)
    return dead + hints


def _latest_checkpoint_at(store, connector_id: str) -> Optional[str]:
    checkpoints = store.list_connector_checkpoints(connector_id)
    latest: Optional[str] = None
    latest_dt: Optional[datetime] = None
    for c in checkpoints:
        ts = getattr(c, "updated_at", None)
        parsed = _parse_ts(ts)
        if parsed is None:
            continue
        if latest_dt is None or parsed > latest_dt:
            latest_dt = parsed
            latest = ts
    return latest


def snapshot_health(store, connector_id: str, status: HealthStatus,
                    retry_after: int | None = None) -> ConnectorSyncState:
    dead = store.list_connector_dead_letters(connector_id, status="open")
    n_dead = len(dead)
    last_ckpt = _latest_checkpoint_at(store, connector_id)

    def _apply(state: ConnectorSyncState) -> None:
        state.status = status
        state.updated_at = now_iso()
        state.dead_letters = n_dead
        if last_ckpt:
            state.last_checkpoint_at = last_ckpt
        state.pending_items = _pending_items(store, connector_id, state)
        # after a successful sync, lag resets to time-since-checkpoint (= ~0)
        if status == HealthStatus.healthy:
            state.last_success_at = now_iso()
            state.retry_count = 0
            state.backoff_seconds = 0
            state.lag_seconds = 0
        else:
            state.lag_seconds = _compute_lag_seconds(state, state.last_checkpoint_at)
        if status == HealthStatus.awaiting_configuration:
            pass  # configuration gap — not a provider failure, no backoff
        elif status in (HealthStatus.degraded, HealthStatus.failed,
                        HealthStatus.unauthorized):
            state.last_failure_at = now_iso()
            state.retry_count += 1
            backoff = min(3600, max(60, state.backoff_seconds * 2 or 60))
            # a provider-instructed wait (rate limit reset) overrides the
            # exponential guess — the provider knows its own window
            if retry_after is not None:
                backoff = max(backoff, min(int(retry_after), 6 * 3600))
            state.backoff_seconds = backoff
            meta = dict(state.metadata or {})
            if retry_after is not None:
                meta["rate_limit_retry_after"] = int(retry_after)
            state.metadata = meta

    return store.apply_connector_sync_state(connector_id, _apply)


def connector_health(store, connector_id: str) -> dict[str, Any]:
    instance = store.get_connector_instance(connector_id)
    if instance is None:
        return {"connector_id": connector_id, "error": "not found"}
    state = store.get_connector_sync_state(connector_id)
    batches = store.list_connector_batches(connector_id, limit=1)
    last_batch = batches[0] if batches else None
    checkpoints = store.list_connector_checkpoints(connector_id)
    dead = store.list_connector_dead_letters(connector_id, status="open")
    last_ckpt = (
        (state.last_checkpoint_at if state else None)
        or _latest_checkpoint_at(store, connector_id)
    )
    lag = _compute_lag_seconds(state, last_ckpt) if state else 0
    if state and state.status == HealthStatus.healthy and state.last_success_at:
        # just-succeeded connectors report near-zero lag
        succ = _parse_ts(state.last_success_at)
        if succ is not None and (datetime.now(timezone.utc) - succ).total_seconds() < 60:
            lag = 0
    pending = _pending_items(store, connector_id, state)
    meta = (state.metadata or {}) if state else {}
    rate_remaining = meta.get("rate_limit_remaining")
    return {
        "connector_id": connector_id,
        "connector_type": instance.connector_type,
        "instance_status": instance.status.value,
        "health": (getattr(state.status, "value", state.status) if state
                   else HealthStatus.healthy.value),
        "last_success_at": state.last_success_at if state else None,
        "last_failure_at": state.last_failure_at if state else None,
        "last_checkpoint_at": last_ckpt,
        "lag_seconds": lag,
        "pending_items": pending,
        "rate_limit_remaining": rate_remaining,
        "rate_limit_retry_after": meta.get("rate_limit_retry_after"),
        "dead_letters": len(dead),
        "retry_count": state.retry_count if state else 0,
        "backoff_seconds": state.backoff_seconds if state else 0,
        "next_run_at": state.next_run_at if state else None,
        "paused": bool(state.paused) if state else False,
        "last_batch": (
            {
                "id": last_batch.id, "stream": last_batch.stream,
                "status": last_batch.status,
                "committed": last_batch.status == BatchStatus.committed.value,
                "raw": last_batch.raw_count,
                "normalized": last_batch.normalized_count,
                "quarantined": last_batch.quarantined_count,
                "percepts": last_batch.percept_count,
                "failed": last_batch.failed_count,
            }
            if last_batch else None
        ),
        "checkpoints": [
            {"stream": c.stream, "cursor": c.cursor,
             "committed_batch_id": c.committed_batch_id}
            for c in checkpoints
        ],
    }
