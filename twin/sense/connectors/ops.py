"""Connector operations helpers for — setup plan, due sync, doctor checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from twin.clock import now_iso
from .credentials import CredentialStore, build_credential_store
from .health import connector_health, schedule_lag_seconds
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


# Per-connector-type scope: (configuration key that holds the selection,
# the discovery helper that lists candidates). Used to tell whether the
# "select scope" step is already satisfied.
_SCOPE_BY_TYPE: dict[str, tuple[str, str]] = {
    "github": ("repositories",
               "twin connector github repositories {cid} --select <owner/name> …"),
    "slack": ("channels",
              "twin connector slack channels {cid} --select <channel_id> …"),
    "gmail": ("labels",
              "twin connector gmail labels {cid} --select <label_id> …"),
}


def _find_setup_instance(store, connector_type: str, owner: OwnershipClass,
                         org_key: Optional[str], connector_id: Optional[str]):
    """Locate the connector this setup is about: an explicit id wins, else the
    most recent non-revoked instance matching (type, owner[, org_key]). Returns
    (instance, account) or (None, None)."""
    from .models import ConnectorStatus

    if connector_id:
        inst = store.get_connector_instance(connector_id)
        if inst is None:
            return None, None
        return inst, store.get_source_account(inst.account_id)

    revoked = {ConnectorStatus.revoked, ConnectorStatus.revoked_with_residual_secret}
    best = None
    best_acc = None
    for inst in store.list_connector_instances():
        if inst.connector_type != connector_type or inst.status in revoked:
            continue
        acc = store.get_source_account(inst.account_id)
        if acc is None or acc.source_owner != owner:
            continue
        if org_key and acc.org_key != org_key:
            continue
        if best is None or (inst.created_at or "") > (best.created_at or ""):
            best, best_acc = inst, acc
    return best, best_acc


def _setup_warnings(
    owner: OwnershipClass,
    vault_id: Optional[str],
    org_key: Optional[str],
) -> list[str]:
    warnings: list[str] = []
    if owner in (OwnershipClass.employer, OwnershipClass.client) and not org_key:
        warnings.append(
            f"{owner.value} ownership requires org_key before add "
            "(otherwise vault placement is refused)"
        )
    if owner == OwnershipClass.personal and org_key:
        warnings.append(
            "personal ownership with org_key is unusual — confirm this is intentional"
        )
    if vault_id:
        if owner == OwnershipClass.personal and vault_id.startswith("vault_work_"):
            warnings.append(
                f"personal ownership with work vault {vault_id!r} is inconsistent"
            )
        if owner in (OwnershipClass.employer, OwnershipClass.client):
            if vault_id in ("vault_personal", "vault_general"):
                warnings.append(
                    f"{owner.value} ownership should not use {vault_id!r}"
                )
        if owner == OwnershipClass.personal and vault_id == "vault_work_acme":
            warnings.append("personal + vault_work_acme looks like a misconfiguration")
    return warnings


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
    connector_id: Optional[str] = None,
) -> dict[str, Any]:
    """Guided, STATE-AWARE setup plan — never starts ingestion.

    Order: ownership/vault → authenticate → scope → backfill preview → confirm.
    If a matching connector already exists (same type + owner, or an explicit
    ``connector_id``), each step reflects the connector's real state so the
    wizard advances as you complete it instead of always showing the same
    static plan.
    """
    from .models import ConnectorStatus

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
    warnings = _setup_warnings(owner, vault_id, org_key)

    # -- reflect the real connector, if one already exists ----------------------
    inst, account = _find_setup_instance(store, connector_type, owner,
                                          org_key, connector_id)
    cid = inst.id if inst else "<conn_id>"
    scope_key, scope_cmd_tmpl = _SCOPE_BY_TYPE.get(
        connector_type, ("streams", "twin connector configure {cid} --config '{{…}}'"))
    inst_cfg = dict(inst.configuration) if inst else {}
    if inst:
        # merged view of what scope is selected (existing + this call's config)
        inst_cfg.update(cfg)
    scope_selected = bool(inst_cfg.get(scope_key))
    authed = bool(inst and inst.credential_ref
                  and inst.status not in (ConnectorStatus.awaiting_auth,
                                          ConnectorStatus.provisioning,
                                          ConnectorStatus.provisioning_failed,
                                          ConnectorStatus.unauthorized))
    synced = bool(inst and store.list_connector_checkpoints(inst.id))

    # 1. ownership / vault
    if inst:
        s_owner = "done"
        owner_detail = (f"registered as {inst.id} · owner={account.source_owner.value} "
                        f"vault={account.vault_id} status={inst.status.value}")
        owner_cmd = f"twin connector list   # {inst.id} already registered"
    else:
        s_owner = "ready" if not warnings else "blocked"
        owner_detail = (f"source_owner={owner.value} vault={vault_id or '(auto)'} "
                        f"org_key={org_key or '—'}")
        owner_cmd = (
            f"twin connector add {connector_type} --source-owner {owner.value}"
            + (f" --vault-id {vault_id}" if vault_id else "")
            + (f" --org-key {org_key}" if org_key else "")
            + (f" --name {display_name!r}" if display_name else "")
        )

    # 2. authenticate
    if authed:
        s_auth = "done"
        auth_detail = f"credential set · status={inst.status.value} (verify: twin connector test {cid})"
    elif inst and inst.status == ConnectorStatus.unauthorized:
        s_auth = "blocked"
        auth_detail = "credential rejected by the provider — rotate the token"
    else:
        s_auth = "ready" if inst else "pending"
        auth_detail = "Use --secret on add/configure; credentials never appear in exports"
    auth_cmd = f"twin connector configure {cid} --secret <TOKEN>"

    # 3. select scope
    if scope_selected:
        s_scope = "done"
        scope_detail = f"{scope_key}={inst_cfg.get(scope_key)}"
    elif authed:
        s_scope = "ready"
        scope_detail = f"pick {scope_key}; discover candidates with the command below"
    else:
        s_scope = "pending"
        scope_detail = f"authenticate first, then select {scope_key}"
    scope_cmd = scope_cmd_tmpl.format(cid=cid)

    # 4. backfill preview
    s_preview = "ready" if scope_selected else "pending"
    # 5. confirm sync
    if synced:
        s_sync = "done"
        sync_detail = "sync has run at least once (checkpoints exist)"
    elif scope_selected:
        s_sync = "ready"
        sync_detail = "scope selected — safe to run the first sync"
    else:
        s_sync = "pending"
        sync_detail = "Only after ownership, vault, scope and preview are accepted"

    steps: list[SetupStep] = [
        SetupStep("classify_ownership", "Confirm ownership and vault",
                  s_owner, owner_detail, owner_cmd),
        SetupStep("authenticate", "Provide credential (never logged)",
                  s_auth, auth_detail, auth_cmd),
        SetupStep("select_scope", "Select repositories / channels / folders",
                  s_scope, scope_detail, scope_cmd),
        SetupStep("backfill_preview", "Preview backfill scope (no ingest)",
                  s_preview, "Always run preview before historical import",
                  f"twin connector backfill {cid} --preview"),
        SetupStep("confirm_sync", "Confirm continuous sync",
                  s_sync, sync_detail, f"twin connector sync {cid}"),
    ]

    # what to do next — the first step that is not yet done
    next_step = next((s for s in steps if s.status != "done"), None)

    return {
        "ok": True,
        "connector_type": connector_type,
        "connector_id": inst.id if inst else None,
        "source_owner": (account.source_owner.value if account else owner.value),
        "vault_id": (account.vault_id if account else vault_id),
        "org_key": (account.org_key if account else org_key),
        "display_name": display_name,
        "configuration": cfg,
        "status": inst.status.value if inst else None,
        "auth_mode": getattr(manifest, "auth_mode", None) if manifest else None,
        "started": False,
        "ingests": False,
        "complete": next_step is None,
        "next_step": next_step.id if next_step else None,
        "warnings": warnings,
        "steps": [s.__dict__ for s in steps],
        "note": (
            "Setup reflects the connector's real state; nothing is fetched until "
            "you run the listed commands. Order: ownership → authenticate → "
            "scope → preview → confirm. Never import full history without preview."
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
        lag = schedule_lag_seconds(state)
        rows.append({
            "connector_id": cid,
            "connector_type": inst.connector_type if inst else "?",
            "status": inst.status.value if inst else "?",
            "next_run_at": state.next_run_at if state else None,
            "interval_seconds": intervals.get(
                inst.connector_type if inst else "", 300,
            ),
            "schedule_lag_seconds": lag,
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
    """Checks for ``twin doctor`` — credentials, instances, schedule lag."""
    checks: list[dict[str, str]] = []
    intervals: dict[str, int] = {}
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

    creds = None
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
    from .counters import reconcile_connector_counters

    for inst in instances:
        h = connector_health(store, inst.id)
        if h.get("health") in ("failed", "unauthorized", "degraded"):
            unhealthy += 1
        state = store.get_connector_sync_state(inst.id)
        if state and not state.paused and h.get("paused") is not True:
            lag = h.get("schedule_lag_seconds")
            interval = intervals.get(inst.connector_type, state.interval_seconds or 300)
            grace = max(60, int(interval))
            if lag is not None and lag > grace:
                lagged += 1

        try:
            report = reconcile_connector_counters(
                store, inst.id, apply_missing=False, repair=False,
            )
            if not report.get("ok"):
                checks.append({
                    "name": f"connectors:counters:{inst.id}",
                    "status": "warn",
                    "detail": (
                        "persisted counters differ from batch ledger; "
                        f"diverged={sorted((report.get('diverged') or {}).keys())}"
                    ),
                })
        except Exception as exc:
            checks.append({
                "name": f"connectors:counters:{inst.id}",
                "status": "warn",
                "detail": f"counter check failed: {type(exc).__name__}",
            })

        if inst.status in SYNCABLE_STATUSES:
            if not inst.credential_ref:
                if (get_manifest(inst.connector_type).auth_mode or "") == "none":
                    continue
                checks.append({
                    "name": f"connectors:auth:{inst.id}",
                    "status": "warn",
                    "detail": "syncable but no credential_ref",
                })
            elif creds is None:
                checks.append({
                    "name": f"connectors:auth:{inst.id}",
                    "status": "warn",
                    "detail": "credential_ref set but store unavailable",
                })
            else:
                try:
                    secret = creds.get(inst.credential_ref)
                except Exception as exc:
                    checks.append({
                        "name": f"connectors:auth:{inst.id}",
                        "status": "fail",
                        "detail": f"credential resolve error: {type(exc).__name__}",
                    })
                else:
                    if secret is None:
                        checks.append({
                            "name": f"connectors:auth:{inst.id}",
                            "status": "fail",
                            "detail": "credential_ref present but secret missing/unreadable",
                        })
                    else:
                        checks.append({
                            "name": f"connectors:auth:{inst.id}",
                            "status": "ok",
                            "detail": "credential resolvable",
                        })

    checks.append({
        "name": "connectors:instances",
        "status": "warn" if (unhealthy or lagged) else "ok",
        "detail": (
            f"{len(instances)} registered, {unhealthy} unhealthy, "
            f"{lagged} past schedule grace"
        ),
    })

    due = due_connectors(store, home)
    overdue = 0
    for cid in due:
        state = store.get_connector_sync_state(cid)
        lag = schedule_lag_seconds(state)
        inst = store.get_connector_instance(cid)
        interval = intervals.get(
            inst.connector_type if inst else "", 
            (state.interval_seconds if state else 300) or 300,
        )
        grace = max(60, int(interval))
        if lag is not None and lag > grace:
            overdue += 1
    if not due:
        due_status, due_detail = "ok", "0 due for sync"
    elif overdue:
        due_status = "warn" if overdue < 3 else "fail"
        due_detail = f"{len(due)} due ({overdue} past schedule grace)"
    else:
        due_status, due_detail = "ok", f"{len(due)} due within grace"
    checks.append({
        "name": "connectors:due",
        "status": due_status,
        "detail": due_detail,
    })

    # Ambient feed = the Analysis Context Compiler's food. A cognition pass can
    # only correlate/reflect over data the connectors actually pulled in, so a
    # lagging feed silently starves reflect + the pattern pass. Frame it that
    # way so the fix is "keep the feed running", not "the model is weak".
    if overdue:
        feed_status = "warn"
        feed_detail = (
            f"{overdue} connector(s) past schedule — analysis compiles on "
            "stale data; run `twin runtime start` for continuous sync + consolidate"
        )
    else:
        feed_status = "ok"
        feed_detail = "connectors fresh — analysis has current data to compile"
    checks.append({
        "name": "acc:feed",
        "status": feed_status,
        "detail": feed_detail,
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
