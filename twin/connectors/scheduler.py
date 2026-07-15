"""Local, in-process sync scheduler.

Not a distributed queue: an interval map (from ``$TWIN_HOME/connectors.yaml``)
that decides which connectors are due, in the same spirit as ``twin watch``.
Phase 1 queues are the logical stages inside ``runtime.py``.

Robustness rules:

- an invalid schedule config is an explicit error, never a silent fall back
  to defaults;
- one failing connector never interrupts the others — each run is isolated,
  the failure is recorded on its sync state with backoff;
- stream-level mutual exclusion comes from the runtime's leases, so two
  schedulers racing the same connector degrade to one no-op, not duplicates.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from ..clock import now_iso
from .credentials import CredentialStore
from .errors import sanitize_error
from .models import ConnectorStatus, ConnectorSyncState, HealthStatus, SYNCABLE_STATUSES
from .runtime import SyncResult
from .service import sync_connector

logger = logging.getLogger("twin.connectors.scheduler")

_DEFAULT_INTERVALS = {"fake": 60, "github": 300, "slack": 120, "email": 300}


class ScheduleConfigError(ValueError):
    """connectors.yaml is present but invalid — surfaced, never swallowed."""


def load_schedule(home: Path) -> dict[str, int]:
    """Read interval overrides. An unreadable/invalid file raises — reverting
    silently to defaults would hide a misconfiguration for weeks."""
    path = Path(home) / "connectors.yaml"
    intervals = dict(_DEFAULT_INTERVALS)
    if not path.exists():
        return intervals
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        overrides = data.get("intervals") or {}
        if not isinstance(overrides, dict):
            raise TypeError("'intervals' must be a mapping of connector_type → seconds")
        for key, value in overrides.items():
            seconds = int(value)
            if seconds < 1:
                raise ValueError(f"interval for {key!r} must be >= 1 second")
            intervals[str(key)] = seconds
    except Exception as exc:
        raise ScheduleConfigError(
            f"invalid schedule config at {path}: {sanitize_error(exc)}"
        ) from exc
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
    due: list[str] = []
    for inst in store.list_connector_instances():
        if inst.status not in SYNCABLE_STATUSES:
            continue
        state = store.get_connector_sync_state(inst.id)
        if state is None:
            due.append(inst.id)
            continue
        if state.paused:
            continue
        next_run = _parse(state.next_run_at)
        if next_run is None or next_run <= at:
            due.append(inst.id)
    return due


def schedule_next(store, connector_id: str, home: Path,
                  *, at: Optional[datetime] = None,
                  intervals: Optional[dict[str, int]] = None) -> ConnectorSyncState:
    at = at or _now()
    inst = store.get_connector_instance(connector_id)
    intervals = intervals if intervals is not None else load_schedule(home)
    interval = intervals.get(inst.connector_type if inst else "", 300)
    state = store.get_connector_sync_state(connector_id) or ConnectorSyncState(id=connector_id)
    delay = interval + max(0, state.backoff_seconds)
    state.interval_seconds = interval
    state.next_run_at = (at + timedelta(seconds=delay)).isoformat()
    return store.upsert_connector_sync_state(state)


def _record_failure(store, connector_id: str, exc: Exception) -> None:
    state = store.get_connector_sync_state(connector_id) or ConnectorSyncState(id=connector_id)
    state.status = HealthStatus.failed
    state.last_failure_at = now_iso()
    state.retry_count += 1
    state.backoff_seconds = min(3600, max(60, state.backoff_seconds * 2 or 60))
    state.metadata = {**(state.metadata or {}), "last_error": sanitize_error(exc)}
    store.upsert_connector_sync_state(state)


def sync_due(
    store,
    credentials: CredentialStore,
    home: Path,
    *,
    emit_percepts: bool = True,
) -> list[SyncResult]:
    """Run every due connector, isolating failures per connector.

    Config errors raise before any sync starts (explicit, actionable);
    per-connector exceptions are recorded on that connector's sync state
    with backoff and the loop continues."""
    intervals = load_schedule(home)  # raises ScheduleConfigError when invalid
    results: list[SyncResult] = []
    for connector_id in due_connectors(store, home):
        # a webhook may have left a targeted-streams hint: honor it for this
        # run, then clear it — the regular cadence remains the authoritative
        # reconciliation over every stream
        state = store.get_connector_sync_state(connector_id)
        targeted = list((state.metadata or {}).get("targeted_streams") or []) \
            if state else []
        try:
            results.append(
                sync_connector(store, credentials, connector_id,
                               streams=targeted or None,
                               emit_percepts=emit_percepts)
            )
            if targeted:
                state = store.get_connector_sync_state(connector_id)
                if state is not None:
                    meta = dict(state.metadata or {})
                    meta.pop("targeted_streams", None)
                    state.metadata = meta
                    store.upsert_connector_sync_state(state)
        except Exception as exc:
            logger.warning("scheduled sync failed for %s: %s",
                           connector_id, sanitize_error(exc))
            _record_failure(store, connector_id, exc)
        finally:
            # success or failure, the connector gets its next slot
            schedule_next(store, connector_id, home, intervals=intervals)
    return results
