"""Connector observability metrics (v0.6 Phase 9 §58).

Aggregates from batches, DLQ, deletion events and sync state. Labels never
carry content — only connector/account/vault/type identifiers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .models import BatchStatus, HealthStatus


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def compute_connector_metrics(store) -> dict[str, Any]:
    """Return connector_* counters suitable for ``twin stats`` / ``/api/metrics``."""
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
    checkpoint_lags: list[int] = []
    rate_limit_waits = 0

    per_connector: list[dict[str, Any]] = []

    for inst in instances:
        ctype = inst.connector_type
        by_type[ctype] = by_type.get(ctype, 0) + 1
        st = getattr(inst.status, "value", inst.status)
        by_status[st] = by_status.get(st, 0) + 1

        acc = store.get_source_account(inst.account_id) if hasattr(store, "get_source_account") else None
        vault = (acc.vault_id if acc else "") or "vault_unknown"
        by_vault[vault] = by_vault.get(vault, 0) + 1

        state = store.get_connector_sync_state(inst.id)
        health = (
            getattr(state.status, "value", state.status)
            if state else HealthStatus.healthy.value
        )
        by_health[health] = by_health.get(health, 0) + 1

        batches = store.list_connector_batches(inst.id, limit=500)
        c_fetch = 0
        c_fail = 0
        c_norm = 0
        c_dedup = 0
        c_quar = 0
        c_perc = 0
        for b in batches:
            c_fetch += int(b.raw_count or 0)
            c_fail += int(b.failed_count or 0)
            c_norm += int(b.normalized_count or 0)
            c_dedup += int(getattr(b, "deduplicated_count", 0) or 0)
            c_quar += int(b.quarantined_count or 0)
            c_perc += int(b.percept_count or 0)
            meta = getattr(b, "metadata", None) or {}
            if meta.get("rate_limit_wait_seconds") or meta.get("rate_limited"):
                rate_limit_waits += 1
            if b.status in (
                BatchStatus.failed.value, BatchStatus.partially_failed.value,
                "failed", "partially_failed",
            ):
                fetch_failed += 1

        fetch_total += c_fetch
        items_normalized += c_norm
        items_deduplicated += c_dedup
        quarantine_total += c_quar
        percept_total += c_perc

        dead = store.list_connector_dead_letters(inst.id, status="open")
        dead_letters_open += len(dead)

        if hasattr(store, "list_connector_deletion_events"):
            deletion_events += len(store.list_connector_deletion_events(inst.id))

        lag = int(state.lag_seconds) if state else 0
        if state and state.last_checkpoint_at:
            ckpt_at = _parse_ts(state.last_checkpoint_at)
            if ckpt_at is not None:
                lag = max(lag, int((datetime.now(timezone.utc) - ckpt_at).total_seconds()))
        if lag:
            checkpoint_lags.append(lag)

        per_connector.append({
            "connector_id": inst.id,
            "connector_type": ctype,
            "vault_id": vault,
            "source_account_id": inst.account_id,
            "instance_status": st,
            "health": health,
            "fetch_raw": c_fetch,
            "normalized": c_norm,
            "deduplicated": c_dedup,
            "quarantined": c_quar,
            "percepts": c_perc,
            "failed_items": c_fail,
            "dead_letters": len(dead),
            "lag_seconds": lag,
            "pending_items": int(state.pending_items) if state else 0,
            "rate_limit_remaining": (state.metadata or {}).get("rate_limit_remaining")
            if state else None,
        })

    return {
        "connectors": {
            "available": True,
            "instances": len(instances),
            "by_type": by_type,
            "by_instance_status": by_status,
            "by_health": by_health,
            "by_vault": by_vault,
            # §58 counter names (aggregated; no sensitive content)
            "connector_fetch_total": fetch_total,
            "connector_fetch_failed_batches": fetch_failed,
            "connector_items_normalized": items_normalized,
            "connector_items_deduplicated": items_deduplicated,
            "connector_quarantine_total": quarantine_total,
            "connector_memory_candidates": percept_total,  # percepts → candidates later
            "connector_dead_letters": dead_letters_open,
            "connector_deletion_events": deletion_events,
            "connector_rate_limit_wait": rate_limit_waits,
            "connector_checkpoint_lag_max": max(checkpoint_lags) if checkpoint_lags else 0,
            "connector_checkpoint_lag_avg": (
                round(sum(checkpoint_lags) / len(checkpoint_lags))
                if checkpoint_lags else 0
            ),
            "per_connector": per_connector,
        },
    }
