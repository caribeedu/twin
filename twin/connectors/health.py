"""Connector health aggregation.

Health is derived from the last batch, checkpoint freshness, dead-letter depth
and auth state — never from a single boolean. Stored on ``ConnectorSyncState``
so the CLI/API/MCP can read it without re-running a sync.
"""

from __future__ import annotations

from typing import Any

from ..clock import now_iso
from .models import (
    BatchStatus,
    ConnectorSyncState,
    HealthStatus,
)


def snapshot_health(store, connector_id: str, status: HealthStatus,
                    retry_after: int | None = None) -> ConnectorSyncState:
    state = store.get_connector_sync_state(connector_id) or ConnectorSyncState(id=connector_id)
    state.status = status
    state.updated_at = now_iso()
    dead = store.list_connector_dead_letters(connector_id, status="open")
    state.dead_letters = len(dead)
    if status == HealthStatus.healthy:
        state.last_success_at = now_iso()
        state.retry_count = 0
        state.backoff_seconds = 0
    elif status in (HealthStatus.degraded, HealthStatus.failed, HealthStatus.unauthorized):
        state.last_failure_at = now_iso()
        state.retry_count += 1
        backoff = min(3600, max(60, state.backoff_seconds * 2 or 60))
        # a provider-instructed wait (rate limit reset) overrides the
        # exponential guess — the provider knows its own window
        if retry_after is not None:
            backoff = max(backoff, min(int(retry_after), 6 * 3600))
        state.backoff_seconds = backoff
    store.upsert_connector_sync_state(state)
    return state


def connector_health(store, connector_id: str) -> dict[str, Any]:
    instance = store.get_connector_instance(connector_id)
    if instance is None:
        return {"connector_id": connector_id, "error": "not found"}
    state = store.get_connector_sync_state(connector_id)
    batches = store.list_connector_batches(connector_id, limit=1)
    last_batch = batches[0] if batches else None
    checkpoints = store.list_connector_checkpoints(connector_id)
    dead = store.list_connector_dead_letters(connector_id, status="open")
    return {
        "connector_id": connector_id,
        "connector_type": instance.connector_type,
        "instance_status": instance.status.value,
        "health": (getattr(state.status, "value", state.status) if state
                   else HealthStatus.healthy.value),
        "last_success_at": state.last_success_at if state else None,
        "last_failure_at": state.last_failure_at if state else None,
        "dead_letters": len(dead),
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
