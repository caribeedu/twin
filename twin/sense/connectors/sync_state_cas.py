"""Helpers for compare-and-set updates of ``ConnectorSyncState``.

Webhook hints and scheduler consumption must never lose concurrent writes
via read-modify-write without a version check.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from twin.clock import now_iso
from .models import ConnectorSyncState


ApplyFn = Callable[[ConnectorSyncState], None]


def apply_sync_state(store, connector_id: str, apply_fn: ApplyFn) -> ConnectorSyncState:
    return store.apply_connector_sync_state(connector_id, apply_fn)


def add_targeted_streams(store, connector_id: str, streams: list[str],
                         *, event: Optional[str] = None) -> ConnectorSyncState:
    wanted = set(streams)

    def _apply(state: ConnectorSyncState) -> None:
        state.next_run_at = now_iso()
        meta = dict(state.metadata or {})
        hinted = set(meta.get("targeted_streams") or [])
        meta["targeted_streams"] = sorted(hinted | wanted)
        if event is not None:
            meta["last_webhook_event"] = event
        state.metadata = meta
        state.updated_at = now_iso()

    return apply_sync_state(store, connector_id, _apply)


def consume_targeted_streams(store, connector_id: str,
                             processed: set[str]) -> ConnectorSyncState:
    """Remove only the streams observed at sync start; keep anything added
    concurrently (CAS retries if another writer raced)."""

    def _apply(state: ConnectorSyncState) -> None:
        meta = dict(state.metadata or {})
        remaining = [s for s in (meta.get("targeted_streams") or [])
                     if s not in processed]
        if remaining:
            meta["targeted_streams"] = remaining
        else:
            meta.pop("targeted_streams", None)
        state.metadata = meta
        state.updated_at = now_iso()

    return apply_sync_state(store, connector_id, _apply)
