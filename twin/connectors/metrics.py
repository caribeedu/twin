"""Connector observability metrics (v0.6 Phase 9 §58).

Cumulative ``*_total`` counters are read from durable ``ConnectorSyncState``
fields (never from a sliding window of recent batches). Labels never carry
content — only connector/account/vault/type identifiers.

Payload shape separates summary time-series dimensions from per-instance
diagnostics so high-cardinality ids are not treated as Prometheus labels.
"""

from __future__ import annotations

from typing import Any

from .counters import counters_snapshot, ensure_counters
from .health import (
    checkpoint_age_seconds,
    pending_items_count,
    schedule_lag_seconds,
)
from .models import HealthStatus


def compute_connector_metrics(store) -> dict[str, Any]:
    """Return connector metrics for ``twin stats`` / ``/api/metrics``."""
    if not hasattr(store, "list_connector_instances"):
        return {"connectors": {"available": False}}

    instances = store.list_connector_instances()
    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_health: dict[str, int] = {}
    by_vault: dict[str, int] = {}

    fetch_total = 0
    fetch_failed = 0
    items_normalized = 0
    items_deduplicated = 0
    quarantine_total = 0
    percept_total = 0
    dead_letters_open = 0
    deletion_events = 0
    rate_limit_waits = 0
    schedule_lags: list[int] = []
    checkpoint_ages: list[int] = []

    diagnostics: list[dict[str, Any]] = []

    for inst in instances:
        ctype = inst.connector_type
        by_type[ctype] = by_type.get(ctype, 0) + 1
        st = getattr(inst.status, "value", inst.status)
        by_status[st] = by_status.get(st, 0) + 1

        acc = store.get_source_account(inst.account_id) if hasattr(store, "get_source_account") else None
        vault = (acc.vault_id if acc else "") or "vault_unknown"
        by_vault[vault] = by_vault.get(vault, 0) + 1

        state = ensure_counters(store, inst.id)
        health = (
            getattr(state.status, "value", state.status)
            if state else HealthStatus.unknown.value
        )
        by_health[health] = by_health.get(health, 0) + 1

        snap = counters_snapshot(state)
        fetch_total += snap["connector_fetch_total"]
        fetch_failed += snap["connector_fetch_failed_batches"]
        items_normalized += snap["connector_items_normalized"]
        items_deduplicated += snap["connector_items_deduplicated"]
        quarantine_total += snap["connector_quarantine_total"]
        percept_total += snap["connector_percepts_total"]
        rate_limit_waits += snap["connector_rate_limit_wait"]
        deletion_events += snap["connector_deletion_events"]

        dead = store.list_connector_dead_letters(inst.id, status="open")
        dead_letters_open += len(dead)

        sched_lag = schedule_lag_seconds(state)
        if sched_lag is not None:
            schedule_lags.append(sched_lag)
        ckpt_age = checkpoint_age_seconds(
            state.last_checkpoint_at if state else None
        )
        if ckpt_age is not None:
            checkpoint_ages.append(ckpt_age)

        diagnostics.append({
            "connector_id": inst.id,
            "connector_type": ctype,
            "vault_id": vault,
            "source_account_id": inst.account_id,
            "instance_status": st,
            "health": health,
            "fetch_total": snap["connector_fetch_total"],
            "normalized_total": snap["connector_items_normalized"],
            "deduplicated_total": snap["connector_items_deduplicated"],
            "quarantined_total": snap["connector_quarantine_total"],
            "percepts_total": snap["connector_percepts_total"],
            "failed_batches_total": snap["connector_fetch_failed_batches"],
            "dead_letters": len(dead),
            "schedule_lag_seconds": sched_lag,
            "checkpoint_age_seconds": ckpt_age,
            "pending_items": pending_items_count(store, inst.id, state),
            "rate_limit_remaining": (state.metadata or {}).get("rate_limit_remaining")
            if state else None,
        })

    return {
        "connectors": {
            "available": True,
            "instances": len(instances),
            # Low-cardinality summary — safe for time-series labels.
            "metrics": {
                "by_type": by_type,
                "by_instance_status": by_status,
                "by_health": by_health,
                "by_vault": by_vault,
                "connector_fetch_total": fetch_total,
                "connector_fetch_failed_batches": fetch_failed,
                "connector_items_normalized": items_normalized,
                "connector_items_deduplicated": items_deduplicated,
                "connector_quarantine_total": quarantine_total,
                "connector_percepts_total": percept_total,
                "connector_dead_letters": dead_letters_open,
                "connector_deletion_events": deletion_events,
                "connector_rate_limit_wait": rate_limit_waits,
                "connector_schedule_lag_max": max(schedule_lags) if schedule_lags else 0,
                "connector_schedule_lag_avg": (
                    round(sum(schedule_lags) / len(schedule_lags))
                    if schedule_lags else 0
                ),
                "connector_checkpoint_age_max": (
                    max(checkpoint_ages) if checkpoint_ages else 0
                ),
            },
            # High-cardinality diagnostics — do NOT export as TSDB labels.
            "instances_detail": diagnostics,
            # Backward-compatible flat aliases (summary metrics only).
            "by_type": by_type,
            "by_instance_status": by_status,
            "by_health": by_health,
            "by_vault": by_vault,
            "connector_fetch_total": fetch_total,
            "connector_fetch_failed_batches": fetch_failed,
            "connector_items_normalized": items_normalized,
            "connector_items_deduplicated": items_deduplicated,
            "connector_quarantine_total": quarantine_total,
            "connector_percepts_total": percept_total,
            "connector_dead_letters": dead_letters_open,
            "connector_deletion_events": deletion_events,
            "connector_rate_limit_wait": rate_limit_waits,
            "connector_checkpoint_lag_max": (
                max(schedule_lags) if schedule_lags else 0
            ),
            "connector_checkpoint_lag_avg": (
                round(sum(schedule_lags) / len(schedule_lags))
                if schedule_lags else 0
            ),
            "note": (
                "connector_*_total counters are durable and monotonic; "
                "instances_detail is diagnostic-only (not TSDB labels); "
                "lag fields are schedule lag, not checkpoint age."
            ),
        },
    }
