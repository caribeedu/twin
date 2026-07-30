"""Connector health aggregation.

Health is derived from the last batch, checkpoint freshness, dead-letter depth
and auth state — never from a single boolean. Stored on ``ConnectorSyncState``
so the CLI/API/MCP can read it without re-running a sync.

 + review fixes:
- ``lag_seconds`` = schedule lag (``max(0, now - next_run_at)``), not checkpoint age
- ``checkpoint_age_seconds`` / ``source_lag_seconds`` exposed separately
- never-run connectors report ``health=unknown``, not healthy
- ``pending_items`` counts backlog queues only (not scope like targeted_streams)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from ..clock import now_iso
from .models import (
    BatchStatus,
    ConnectorStatus,
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def checkpoint_age_seconds(last_checkpoint_at: Optional[str]) -> Optional[int]:
    parsed = _parse_ts(last_checkpoint_at)
    if parsed is None:
        return None
    return max(0, int((_now() - parsed).total_seconds()))


def schedule_lag_seconds(state: Optional[ConnectorSyncState]) -> Optional[int]:
    """Seconds past ``next_run_at``. None when no schedule is known.

    Paused connectors are not lagged — the pause is intentional.
    """
    if state is None:
        return None
    if state.paused:
        return 0
    if state.status == HealthStatus.paused:
        return 0
    next_run = _parse_ts(state.next_run_at)
    if next_run is None:
        return None
    return max(0, int((_now() - next_run).total_seconds()))


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


# Metadata keys that are durable *backlog* queues — not selected scope.
_PENDING_QUEUE_KEYS = (
    "pending_threads",
    "pending_message_refreshes",
    "pending_tombstones",
    "pending_transcripts",
)


def pending_items_count(store, connector_id: str,
                        state: Optional[ConnectorSyncState]) -> int:
    """Open DLQ + explicit pending hint queues. Never counts scope lists."""
    dead = len(store.list_connector_dead_letters(connector_id, status="open"))
    meta = (state.metadata or {}) if state else {}
    hints = 0
    pending = meta.get("pending")
    if isinstance(pending, dict):
        for val in pending.values():
            if isinstance(val, list):
                hints += len(val)
            elif isinstance(val, dict):
                hints += len(val)
    for key in _PENDING_QUEUE_KEYS:
        val = meta.get(key)
        if isinstance(val, list):
            hints += len(val)
        elif isinstance(val, dict):
            hints += len(val)
    # targeted_streams is scope/hint of *what to sync*, not backlog depth
    return dead + hints


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
        state.pending_items = pending_items_count(store, connector_id, state)
        # schedule lag — never checkpoint age
        lag = schedule_lag_seconds(state)
        state.lag_seconds = 0 if lag is None else lag
        if status == HealthStatus.healthy:
            state.last_success_at = now_iso()
            state.retry_count = 0
            state.backoff_seconds = 0
        elif status == HealthStatus.awaiting_configuration:
            pass  # configuration gap — not a provider failure, no backoff
        elif status == HealthStatus.unknown:
            pass
        elif status in (HealthStatus.degraded, HealthStatus.failed,
                        HealthStatus.unauthorized):
            state.last_failure_at = now_iso()
            state.retry_count += 1
            backoff = min(3600, max(60, state.backoff_seconds * 2 or 60))
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
    ckpt_age = checkpoint_age_seconds(last_ckpt)
    sched_lag = schedule_lag_seconds(state)
    pending = pending_items_count(store, connector_id, state)
    meta = (state.metadata or {}) if state else {}

    if state is None:
        health = HealthStatus.unknown.value
    else:
        health = getattr(state.status, "value", state.status)
        # never-run: no success/failure evidence yet
        if (health in (HealthStatus.healthy.value, HealthStatus.unknown.value)
                and not state.last_success_at and not state.last_failure_at
                and not last_batch):
            health = HealthStatus.unknown.value
        if instance.status == ConnectorStatus.paused:
            health = HealthStatus.paused.value

    return {
        "connector_id": connector_id,
        "connector_type": instance.connector_type,
        "instance_status": instance.status.value,
        "health": health,
        "last_success_at": state.last_success_at if state else None,
        "last_failure_at": state.last_failure_at if state else None,
        "last_checkpoint_at": last_ckpt,
        # lag_seconds ≡ schedule lag (documented). None when unknown.
        "lag_seconds": sched_lag,
        "schedule_lag_seconds": sched_lag,
        "checkpoint_age_seconds": ckpt_age,
        "source_lag_seconds": meta.get("source_lag_seconds"),
        "pending_items": pending,
        "rate_limit_remaining": meta.get("rate_limit_remaining"),
        "rate_limit_retry_after": meta.get("rate_limit_retry_after"),
        "dead_letters": len(dead),
        "retry_count": state.retry_count if state else 0,
        "backoff_seconds": state.backoff_seconds if state else 0,
        "next_run_at": state.next_run_at if state else None,
        "interval_seconds": state.interval_seconds if state else None,
        "paused": bool(state.paused) if state else (
            instance.status == ConnectorStatus.paused
        ),
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
