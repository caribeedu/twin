"""Local, in-process sync scheduler.

Not a distributed queue: an interval map (from ``$TWIN_HOME/connectors.yaml``)
that decides which connectors are due, in the same spirit as ``twin watch``.
Phase 1 queues are the logical stages inside ``runtime.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from .credentials import CredentialStore
from .models import ConnectorStatus, ConnectorSyncState
from .runtime import SyncResult
from .service import sync_connector

_DEFAULT_INTERVALS = {"fake": 60, "github": 300, "slack": 120, "email": 300}


def load_schedule(home: Path) -> dict[str, int]:
    path = Path(home) / "connectors.yaml"
    intervals = dict(_DEFAULT_INTERVALS)
    if path.exists():
        try:
            import yaml
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            intervals.update({k: int(v) for k, v in (data.get("intervals") or {}).items()})
        except Exception:
            pass
    return intervals


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def due_connectors(store, home: Path, *, at: Optional[datetime] = None) -> list[str]:
    at = at or _now()
    intervals = load_schedule(home)
    due: list[str] = []
    for inst in store.list_connector_instances():
        if inst.status in (ConnectorStatus.revoked.value, ConnectorStatus.paused.value):
            continue
        state = store.get_connector_sync_state(inst.id)
        if state is None or state.paused:
            if state is None:
                due.append(inst.id)
            continue
        next_run = _parse(state.next_run_at)
        if next_run is None or next_run <= at:
            due.append(inst.id)
        _ = intervals  # intervals used when scheduling below
    return due


def schedule_next(store, connector_id: str, home: Path,
                  *, at: Optional[datetime] = None) -> ConnectorSyncState:
    at = at or _now()
    inst = store.get_connector_instance(connector_id)
    intervals = load_schedule(home)
    interval = intervals.get(inst.connector_type if inst else "", 300)
    state = store.get_connector_sync_state(connector_id) or ConnectorSyncState(id=connector_id)
    delay = interval + max(0, state.backoff_seconds)
    state.interval_seconds = interval
    state.next_run_at = (at + timedelta(seconds=delay)).isoformat()
    return store.upsert_connector_sync_state(state)


def sync_due(
    store,
    credentials: CredentialStore,
    home: Path,
    *,
    emit_percepts: bool = True,
) -> list[SyncResult]:
    results: list[SyncResult] = []
    for connector_id in due_connectors(store, home):
        results.append(
            sync_connector(store, credentials, connector_id, emit_percepts=emit_percepts)
        )
        schedule_next(store, connector_id, home)
    return results
