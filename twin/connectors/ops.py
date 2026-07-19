"""Connector operations helpers for Phase 9 — setup plan, due sync, doctor checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from ..clock import now_iso
from .credentials import CredentialStore, build_credential_store
from .health import connector_health
from .models import SYNCABLE_STATUSES, OwnershipClass
from .registry import get_manifest, list_adapters
from .scheduler import due_connectors, load_schedule, sync_due
from .service import backfill_preview


@dataclass
class SetupStep:
    id: str
    title: str
    status: str  # pending | ready | done | blocked
    detail: str = ""
    command: str = ""


def plan_connector_setup(
    store,
    *,
    connector_type: str,
    source_owner: str = "employer",
    vault_id: Optional[str] = None,
    org_key: Optional[str] = None,
    display_name: str = "",
    configuration: Optional[dict[str, Any]] = None,
    home: Optional[Path] = None,
) -> dict[str, Any]:
    """Guided setup plan — never starts ingestion (v0.6 §77).

    Returns ordered steps the operator must confirm. Preview-first: no secret
    and no sync are performed here.
    """
    adapters = list_adapters()
    if connector_type not in adapters:
        return {
            "ok": False,
            "error": f"unknown connector_type {connector_type!r}",
            "known": sorted(adapters),
        }
    try:
        owner = OwnershipClass(source_owner)
    except ValueError:
        return {
            "ok": False,
            "error": f"invalid source_owner {source_owner!r}",
            "allowed": [o.value for o in OwnershipClass],
        }

    manifest = get_manifest(connector_type)
    cfg = dict(configuration or {})
    steps: list[SetupStep] = [
        SetupStep(
            id="classify_ownership",
            title="Confirm ownership and vault",
            status="ready",
            detail=(
                f"source_owner={owner.value} vault={vault_id or '(auto)'} "
                f"org_key={org_key or '—'}"
            ),
            command=(
                f"twin connector add {connector_type} "
                f"--source-owner {owner.value}"
                + (f" --vault-id {vault_id}" if vault_id else "")
                + (f" --org-key {org_key}" if org_key else "")
                + (f" --name {display_name!r}" if display_name else "")
            ),
        ),
        SetupStep(
            id="authenticate",
            title="Provide credential (never logged)",
            status="pending",
            detail="Use --secret on add/configure; credentials never appear in exports",
            command="twin connector configure <conn_id> --secret <TOKEN>",
        ),
        SetupStep(
            id="select_scope",
            title="Select repositories / channels / folders",
            status="pending",
            detail=f"streams={list(manifest.streams) if manifest else []}",
            command=f"twin connector {connector_type} … <conn_id>  # discovery helper",
        ),
        SetupStep(
            id="backfill_preview",
            title="Preview backfill scope (no ingest)",
            status="pending",
            detail="Always run preview before historical import",
            command="twin connector backfill <conn_id> --preview",
        ),
        SetupStep(
            id="confirm_sync",
            title="Confirm continuous sync",
            status="pending",
            detail="Only after ownership, vault, scope and preview are accepted",
            command="twin connector sync <conn_id>",
        ),
    ]
    if cfg:
        steps[2].detail += f" configuration_keys={sorted(cfg.keys())}"

    return {
        "ok": True,
        "connector_type": connector_type,
        "source_owner": owner.value,
        "vault_id": vault_id,
        "org_key": org_key,
        "display_name": display_name,
        "configuration": cfg,
        "auth_mode": getattr(manifest, "auth_mode", None) if manifest else None,
        "started": False,
        "ingests": False,
        "steps": [s.__dict__ for s in steps],
        "note": (
            "Setup plan only — nothing is registered or fetched until you run "
            "the listed commands. Never import full history without preview."
        ),
        "planned_at": now_iso(),
    }


def list_due_connectors(store, home: Path) -> dict[str, Any]:
    """Which connectors the local scheduler would run now."""
    intervals = load_schedule(home)
    due = due_connectors(store, home)
    rows = []
    for cid in due:
        inst = store.get_connector_instance(cid)
        state = store.get_connector_sync_state(cid)
        rows.append({
            "connector_id": cid,
            "connector_type": inst.connector_type if inst else "?",
            "status": inst.status.value if inst else "?",
            "next_run_at": state.next_run_at if state else None,
            "interval_seconds": intervals.get(
                inst.connector_type if inst else "", 300,
            ),
            "paused": bool(state.paused) if state else False,
        })
    return {
        "due": rows,
        "count": len(rows),
        "intervals": intervals,
        "at": now_iso(),
    }


def run_sync_due(store, credentials: CredentialStore, home: Path, *,
                 emit_percepts: bool = True) -> list[dict[str, Any]]:
    """Run scheduler once; return compact per-connector results."""
    results = sync_due(store, credentials, home, emit_percepts=emit_percepts)
    out = []
    for r in results:
        out.append({
            "connector_id": r.connector_id,
            "ok": r.ok,
            "health": getattr(r.health, "value", r.health),
            "percepts": r.percepts,
            "streams": len(r.streams),
        })
    return out


def doctor_connector_checks(store, home: Path) -> list[dict[str, str]]:
    """Checks for ``twin doctor`` — credentials, instances, lag, schedule."""
    checks: list[dict[str, str]] = []
    try:
        intervals = load_schedule(home)
        checks.append({
            "name": "connectors:schedule",
            "status": "ok",
            "detail": f"{len(intervals)} interval entries",
        })
    except Exception as exc:
        checks.append({
            "name": "connectors:schedule",
            "status": "fail",
            "detail": str(exc),
        })

    try:
        creds = build_credential_store(home)
        checks.append({
            "name": "connectors:credentials",
            "status": "ok",
            "detail": type(creds).__name__,
        })
    except Exception as exc:
        checks.append({
            "name": "connectors:credentials",
            "status": "warn",
            "detail": f"credential store unavailable: {exc}",
        })

    if not hasattr(store, "list_connector_instances"):
        checks.append({
            "name": "connectors:instances",
            "status": "warn",
            "detail": "connector store unsupported",
        })
        return checks

    instances = store.list_connector_instances()
    if not instances:
        checks.append({
            "name": "connectors:instances",
            "status": "ok",
            "detail": "none registered",
        })
        return checks

    unhealthy = 0
    lagged = 0
    for inst in instances:
        h = connector_health(store, inst.id)
        if h.get("health") in ("failed", "unauthorized", "degraded"):
            unhealthy += 1
        if int(h.get("lag_seconds") or 0) > 3600:
            lagged += 1
        if inst.status in SYNCABLE_STATUSES and not inst.credential_ref:
            checks.append({
                "name": f"connectors:auth:{inst.id}",
                "status": "warn",
                "detail": "syncable but no credential_ref",
            })

    checks.append({
        "name": "connectors:instances",
        "status": "warn" if unhealthy else "ok",
        "detail": f"{len(instances)} registered, {unhealthy} unhealthy, {lagged} lag>1h",
    })
    due = due_connectors(store, home)
    checks.append({
        "name": "connectors:due",
        "status": "ok",
        "detail": f"{len(due)} due for sync",
    })
    return checks


def preview_or_error(
    store, credentials: CredentialStore, connector_id: str, *, principal_id: str,
) -> dict[str, Any]:
    """Thin wrapper so setup can chain into backfill preview safely."""
    preview = backfill_preview(
        store, credentials, connector_id, principal_id=principal_id,
    )
    assert preview.get("started") is False
    return preview
