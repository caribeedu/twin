"""High-level connector operations shared by CLI, API and MCP.

Registration enforces explicit ownership + vault at configure time; credentials
are stored only via the CredentialStore; sync builds the adapter from the
registry and delegates to the runtime.

Lifecycle rules:

- provisioning is *compensable*: an instance starts as ``provisioning`` and
  only becomes ``active``/``awaiting_auth`` when every step succeeded; any
  failure rolls back what was written (no orphan secret, no orphan ref, no
  usable half-configured connector);
- revocation is *resumable*: ``revoking`` → delete secret → verify absent →
  clear ref → ``revoked``; residual secret material is reported as
  ``revoked_with_residual_secret``, never claimed clean;
- only adapters that declare ``auth_mode=generated_local_token`` may receive
  a framework-generated secret — an external provider without a credential is
  ``awaiting_auth``, not active with a fake token.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

from ..clock import now_iso
from .credentials import CredentialStore, generate_token
from .errors import sanitize_error
from .models import (
    ConnectorDeadLetter,
    ConnectorInstance,
    ConnectorStatus,
    CredentialRef,
    DeadLetterStatus,
    HealthStatus,
    OwnershipClass,
    SourceAccount,
    SyncMode,
)
from .ownership import (
    default_vault_for,
    ensure_vault_for_account,
    validate_account_vault,
)
from .registry import build_adapter, get_manifest
from .runtime import SyncResult, persist_committed_record, run_sync

logger = logging.getLogger("twin.connectors.service")


def register_source_account(
    store,
    *,
    connector_type: str,
    source_owner: str,
    owner_principal_id: str,
    vault_id: Optional[str] = None,
    org_key: Optional[str] = None,
    persona: str = "individual",
    default_domain: str = "work",
    confidentiality: str = "internal",
    source_scope: str = "work",
    source_trust: float = 0.8,
    sync_mode: str = SyncMode.manual.value,
    external_account_id: str = "",
    display_name: str = "",
    metadata: Optional[dict[str, Any]] = None,
) -> SourceAccount:
    """Create an account with declared ownership. Fails closed on bad ownership.

    ``owner_principal_id`` is mandatory and comes from the resolved caller —
    a missing principal fails instead of defaulting to a privileged one.
    Employer/client ownership requires an ``org_key`` (the organization or
    client identifier) even when a vault is passed explicitly."""
    if not owner_principal_id:
        raise ValueError("owner_principal_id is required — accounts never "
                         "default to a privileged principal")
    if source_owner in (OwnershipClass.employer.value, OwnershipClass.client.value) \
            and not org_key:
        raise ValueError(f"{source_owner} account requires an org_key "
                         "(organization/client identifier)")
    if vault_id is None:
        vault_id = default_vault_for(source_owner, org_key)
    validate_account_vault(source_owner, vault_id)
    ensure_vault_for_account(store, source_owner, vault_id, org_key)

    account = SourceAccount(
        connector_type=connector_type,
        external_account_id=external_account_id,
        display_name=display_name or external_account_id or connector_type,
        owner_principal_id=owner_principal_id,
        source_owner=source_owner,
        org_key=org_key,
        persona=persona,
        vault_id=vault_id,
        default_domain=default_domain,
        confidentiality=confidentiality,
        source_scope=source_scope,
        source_trust=source_trust,
        sync_mode=sync_mode,
        metadata={**(metadata or {}),
                  "classified_by": owner_principal_id,
                  "classified_at": now_iso()},
    )
    store.insert_source_account(account)
    return account


def _reclassify_fingerprint(account, proposed: dict[str, Any],
                            actor_principal_id: str) -> str:
    """Covers the account's CURRENT classification state and the exact
    proposal + actor: any drift (ownership, vault, org, prior
    reclassification) between preview and apply changes the token."""
    basis = json.dumps({
        "account_id": account.id,
        "current": {"source_owner": account.source_owner.value,
                    "org_key": account.org_key, "vault_id": account.vault_id},
        "reclassifications": len((account.metadata or {}).get(
            "reclassifications", [])),
        "proposed": proposed,
        "actor": actor_principal_id,
    }, sort_keys=True, default=str)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def reclassify_source_account(
    store,
    account_id: str,
    *,
    actor_principal_id: str,
    source_owner: Optional[str] = None,
    org_key: Optional[str] = None,
    vault_id: Optional[str] = None,
    apply: bool = False,
    confirm_token: Optional[str] = None,
) -> dict[str, Any]:
    """Ownership/vault reclassification is preview-first, STATE-AWARE and
    audited.

    The preview returns a ``confirm_token`` fingerprinting the account's
    current classification plus the exact proposal and actor. ``apply=True``
    only executes with a matching token — if the account changed between
    preview and apply (ownership, vault, org, another reclassification), the
    token no longer matches and a fresh preview is required."""
    account = store.get_source_account(account_id)
    if account is None:
        raise ValueError(f"source account {account_id} not found")
    new_owner = source_owner or account.source_owner.value
    new_org = org_key if org_key is not None else account.org_key
    if new_owner in (OwnershipClass.employer.value, OwnershipClass.client.value) \
            and not new_org:
        raise ValueError(f"{new_owner} account requires an org_key")
    new_vault = vault_id or default_vault_for(new_owner, new_org)
    validate_account_vault(new_owner, new_vault)

    proposed = {"source_owner": new_owner, "org_key": new_org,
                "vault_id": new_vault}
    fingerprint = _reclassify_fingerprint(account, proposed, actor_principal_id)
    preview = {
        "account_id": account_id,
        "current": {"source_owner": account.source_owner.value,
                    "org_key": account.org_key, "vault_id": account.vault_id},
        "proposed": proposed,
        "vault_changes": account.vault_id != new_vault,
        "policy_impact": (
            "existing artifacts keep their original vault lineage; only "
            "newly ingested items land in the proposed vault"
        ),
        "confirm_token": fingerprint,
        "applied": False,
    }
    if not apply:
        return preview
    if confirm_token != fingerprint:
        raise ValueError(
            "stale or missing confirm_token — the account changed since the "
            "preview (or none was requested); request a fresh preview"
        )

    ensure_vault_for_account(store, new_owner, new_vault, new_org)
    audit = dict(account.metadata or {})
    audit.setdefault("reclassifications", []).append({
        "at": now_iso(), "actor": actor_principal_id,
        "from": preview["current"], "to": preview["proposed"],
    })
    store.update_source_account(
        account_id, source_owner=new_owner, org_key=new_org,
        vault_id=new_vault, metadata=audit,
    )
    preview["applied"] = True
    return preview


def set_credential(
    store,
    credentials: CredentialStore,
    connector_id: str,
    secret: Optional[str] = None,
    *,
    scopes: Optional[list[str]] = None,
    expires_at: Optional[str] = None,
) -> Optional[str]:
    """Store a secret via the CredentialStore; DB keeps only the ref + metadata.

    Without a secret: adapters that declare ``generated_local_token`` get a
    generated one; every other provider stays ``awaiting_auth`` — a random
    token pretending to be a GitHub/Slack/Gmail credential is worse than no
    credential."""
    instance = store.get_connector_instance(connector_id)
    if instance is None:
        raise ValueError(f"connector {connector_id} not found")
    manifest = get_manifest(instance.connector_type)

    if not secret:
        if manifest.auth_mode == "generated_local_token":
            secret = generate_token()
        elif manifest.auth_mode == "none":
            store.update_connector_instance(
                connector_id, status=ConnectorStatus.active.value)
            return None
        else:
            store.update_connector_instance(
                connector_id, status=ConnectorStatus.awaiting_auth.value)
            return None

    ref = CredentialRef(
        provider=getattr(credentials, "provider", "encrypted_file"),
        scopes=scopes or manifest.default_scopes,
        expires_at=expires_at,
    )
    store.insert_credential_ref(ref)
    secret_written = False
    try:
        credentials.put(ref.id, secret)
        secret_written = True
        store.update_connector_instance(
            connector_id, credential_ref=ref.id,
            status=ConnectorStatus.active.value,
        )
    except Exception:
        # compensate: no orphan secret, no orphan ref
        if secret_written:
            try:
                credentials.delete(ref.id)
            except Exception:
                logger.warning("compensation could not remove secret %s", ref.id)
        try:
            store.delete_credential_ref(ref.id)
        except Exception:
            logger.warning("compensation could not remove credential ref %s", ref.id)
        raise
    return ref.id


def add_connector_instance(
    store,
    credentials: CredentialStore,
    *,
    account_id: str,
    secret: Optional[str] = None,
    scopes: Optional[list[str]] = None,
    configuration: Optional[dict[str, Any]] = None,
    adapter_version: str = "1.0",
) -> ConnectorInstance:
    """Compensable provisioning: the instance is usable only after every step
    succeeded. On failure it is marked ``provisioning_failed`` and any secret
    or credential ref already written is removed."""
    account = store.get_source_account(account_id)
    if account is None:
        raise ValueError(f"source account {account_id} not found")
    instance = ConnectorInstance(
        connector_type=account.connector_type,
        account_id=account_id,
        adapter_version=adapter_version,
        configuration=configuration or {},
        status=ConnectorStatus.provisioning,
    )
    store.insert_connector_instance(instance)
    try:
        set_credential(store, credentials, instance.id, secret, scopes=scopes)
    except Exception:
        try:
            store.update_connector_instance(
                instance.id, status=ConnectorStatus.provisioning_failed.value)
        except Exception:
            logger.warning("could not mark %s provisioning_failed", instance.id)
        raise
    return store.get_connector_instance(instance.id)  # reload with credential_ref


def _load_adapter(store, credentials: CredentialStore, connector_id: str):
    instance = store.get_connector_instance(connector_id)
    if instance is None:
        raise ValueError(f"connector {connector_id} not found")
    account = store.get_source_account(instance.account_id)
    if account is None:
        raise ValueError(f"account {instance.account_id} not found")
    secret = (
        credentials.get(instance.credential_ref) if instance.credential_ref else None
    )
    return build_adapter(instance, account, secret), instance, account


def validate_connector(store, credentials: CredentialStore, connector_id: str):
    adapter, instance, _ = _load_adapter(store, credentials, connector_id)
    health = adapter.validate_credentials()
    store.update_connector_instance(connector_id, last_health_check=now_iso())
    if instance.credential_ref:
        store.update_credential_ref(instance.credential_ref, last_used_at=now_iso())
    return health


def sync_connector(
    store,
    credentials: CredentialStore,
    connector_id: str,
    *,
    streams: Optional[list[str]] = None,
    emit_percepts: bool = True,
    lease_owner: Optional[str] = None,
    execution_context: Optional["SyncExecutionContext"] = None,
) -> SyncResult:
    from .models import SyncExecutionContext

    adapter, instance, account = _load_adapter(store, credentials, connector_id)
    return run_sync(
        store, adapter, instance, account,
        streams=streams, emit_percepts=emit_percepts,
        lease_owner=lease_owner,
        execution_context=execution_context or SyncExecutionContext(),
    )


def sync_fingerprint(
    store, connector_id: str, *, principal_id: str,
    streams: Optional[list[str]] = None, emit_percepts: bool = True,
) -> str:
    """State fingerprint for preview→confirm: covers the connector, its
    account/vault/ownership, configuration, adapter version, checkpoints and
    the requesting principal. Any drift between preview and apply changes the
    token and forces a fresh preview."""
    instance = store.get_connector_instance(connector_id)
    if instance is None:
        raise ValueError(f"connector {connector_id} not found")
    account = store.get_source_account(instance.account_id)
    checkpoints = {
        c.stream: {"cursor": c.cursor, "version": c.version}
        for c in store.list_connector_checkpoints(connector_id)
    }
    basis = json.dumps({
        "connector_id": instance.id,
        "status": instance.status.value,
        "account_id": instance.account_id,
        "source_owner": account.source_owner.value if account else None,
        "vault_id": account.vault_id if account else None,
        "configuration": instance.configuration,
        "adapter_version": instance.adapter_version,
        "checkpoints": checkpoints,
        "streams": sorted(streams or []),
        "emit_percepts": emit_percepts,
        "principal": principal_id,
    }, sort_keys=True, default=str)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def backfill_preview(
    store, credentials: CredentialStore, connector_id: str, *,
    principal_id: str,
) -> dict[str, Any]:
    """What a backfill WOULD ingest — scope, vault, policy, per-stream state
    and (when the adapter offers it) provider-side volume estimates. Read
    only: previewing never starts ingestion (v0.6 §77–79).

    Phase 4 adds a year-month partition plan for mail connectors; creating a
    ``BackfillJob`` is a separate mutating call (``create_backfill_job``)."""
    from .mail.backfill import plan_year_month_partitions
    from .models import BackfillJobStatus

    adapter, instance, account = _load_adapter(store, credentials, connector_id)
    manifest = adapter.adapter_manifest()
    plan_streams = getattr(adapter, "plan_streams", None)
    streams = ((plan_streams(account) if callable(plan_streams) else None)
               or list(manifest.streams) or ["default"])
    estimates: dict[str, Any] = {}
    estimator = getattr(adapter, "estimate_backfill", None)
    if callable(estimator):
        estimates = estimator()
    config = instance.configuration or {}
    stream_rows = []
    for stream in streams:
        ckpt = store.get_connector_checkpoint(connector_id, stream)
        stream_rows.append({
            "stream": stream,
            # no checkpoint yet → the next sync IS the backfill for this stream
            "mode": "incremental" if ckpt else "backfill",
            "watermark": (ckpt.cursor or {}).get("watermark") if ckpt else None,
            "estimate": estimates.get(stream),
        })
    partitions = []
    if instance.connector_type in ("gmail", "outlook", "email"):
        partitions = plan_year_month_partitions(
            range_start=config.get("backfill_since"),
            range_end=config.get("backfill_until"),
        )
    existing = [
        {"id": j.id, "status": j.status.value,
         "completed_partitions": (j.progress or {}).get("completed_partitions"),
         "total_partitions": (j.progress or {}).get("total_partitions")}
        for j in store.list_backfill_jobs(connector_id)
        if j.status in (BackfillJobStatus.planned, BackfillJobStatus.running,
                        BackfillJobStatus.paused)
    ]
    return {
        "connector_id": connector_id,
        "connector_type": instance.connector_type,
        "source_owner": account.source_owner.value,
        "vault_id": account.vault_id,
        "backfill_since": config.get("backfill_since"),
        "backfill_until": config.get("backfill_until"),
        "ingestion_policy": config.get("ingestion_policy"),
        "streams": stream_rows,
        "partitions": partitions,
        "partition_strategy": "year_month" if partitions else None,
        "active_jobs": existing,
        "requested_by": principal_id,
        "started": False,  # a preview NEVER ingests
    }


def create_backfill_job(
    store, credentials: CredentialStore, connector_id: str, *,
    range_start: Optional[str] = None,
    range_end: Optional[str] = None,
) -> "BackfillJob":
    """Create a partitionable BackfillJob from the current configuration.

    Does not ingest. Use ``run_backfill_partition`` (or CLI) to advance one
    partition at a time through the normal sync spine. Stored ``streams`` are
    continuous base streams (``label:…`` / ``folder:…``); each partition run
    namespaces them under ``backfill:{job}:{partition}:…``.
    """
    from .mail.backfill import plan_year_month_partitions
    from .mail.streams import continuous_base_streams
    from .models import BackfillJob, BackfillJobStatus

    adapter, instance, account = _load_adapter(store, credentials, connector_id)
    config = dict(instance.configuration or {})
    since = range_start or config.get("backfill_since")
    until = range_end or config.get("backfill_until")
    plan_streams = getattr(adapter, "plan_streams", None)
    streams = ((plan_streams(account) if callable(plan_streams) else None)
               or list(adapter.adapter_manifest().streams) or [])
    streams = continuous_base_streams(list(streams))
    if not streams:
        raise ValueError(
            f"connector {connector_id} has no streams configured for backfill")
    partitions = plan_year_month_partitions(range_start=since, range_end=until)
    if not partitions:
        raise ValueError("backfill range produced no partitions")
    job = BackfillJob(
        connector_id=connector_id,
        status=BackfillJobStatus.planned,
        range_start=since,
        range_end=until,
        streams=list(streams),
        progress={
            "partitions": partitions,
            "completed_partitions": 0,
            "total_partitions": len(partitions),
        },
        metadata={"vault_id": account.vault_id,
                  "source_owner": account.source_owner.value},
    )
    store.insert_backfill_job(job)
    return job


def run_backfill_partition(
    store, credentials: CredentialStore, job_id: str, *,
    emit_percepts: bool = True,
    worker_id: Optional[str] = None,
) -> dict[str, Any]:
    """Advance one BackfillJob partition via namespaced sync streams.

    Invariants:
    - does NOT mutate ``ConnectorInstance.configuration``;
    - uses ``backfill:{job}:{partition}:{base}`` streams so continuous
      checkpoints never regress;
    - claims the partition via CAS + fencing token;
    - marks the partition completed only when every stream reports ``done``.
    """
    import uuid

    from .mail.backfill import (
        apply_partition_claim,
        has_live_partition_claim,
        next_runnable_partition,
        release_partition_claim,
    )
    from .mail.streams import format_backfill_stream
    from .models import BackfillJobStatus, SyncExecutionContext

    job = store.get_backfill_job(job_id)
    if job is None:
        raise ValueError(f"backfill job {job_id} not found")
    if job.status in (BackfillJobStatus.completed, BackfillJobStatus.cancelled):
        raise ValueError(f"backfill job {job_id} is {job.status.value}")

    owner = worker_id or f"backfill_{uuid.uuid4().hex[:12]}"
    expected = job.version
    part = next_runnable_partition(job.progress or {})
    if part is None:
        if has_live_partition_claim(job.progress or {}):
            raise ValueError(
                f"backfill job {job_id} partition already claimed")
        job.status = BackfillJobStatus.completed
        job.completed_at = now_iso()
        if not store.cas_backfill_job(job, expected):
            raise ValueError(f"backfill job {job_id} claim lost (complete race)")
        return {"job_id": job.id, "status": job.status.value, "done": True}

    claim_token = (part.get("claim_token") or 0) + 1
    job.status = BackfillJobStatus.running
    job.progress = apply_partition_claim(
        job.progress, part["partition_key"],
        worker_id=owner, claim_token=claim_token,
    )
    if not store.cas_backfill_job(job, expected):
        raise ValueError(
            f"backfill job {job_id} partition {part['partition_key']} "
            "already claimed")

    # Config must stay untouched — snapshot to prove it after sync.
    instance = store.get_connector_instance(job.connector_id)
    if instance is None:
        raise ValueError(f"connector {job.connector_id} not found")
    cfg_before = dict(instance.configuration or {})

    bf_streams = [
        format_backfill_stream(job.id, part["partition_key"], base)
        for base in (job.streams or [])
    ]
    ctx = SyncExecutionContext(
        mode="backfill",
        job_id=job.id,
        partition_key=part["partition_key"],
        range_start=part["range_start"],
        range_end=part["range_end"],
        claim_token=claim_token,
        worker_id=owner,
        attachment_mode=(cfg_before.get("attachment_mode") or "metadata_only"),
    )
    result = sync_connector(
        store, credentials, job.connector_id,
        streams=bf_streams,
        emit_percepts=emit_percepts,
        lease_owner=owner,
        execution_context=ctx,
    )

    instance_after = store.get_connector_instance(job.connector_id)
    cfg_after = dict((instance_after.configuration if instance_after else {}) or {})
    if cfg_after != cfg_before:
        raise RuntimeError(
            "backfill mutated connector configuration — invariant violated")

    # Refresh job for CAS after sync (version already bumped by claim).
    job = store.get_backfill_job(job_id)
    if job is None:
        raise ValueError(f"backfill job {job_id} disappeared")
    expected = job.version

    streams_ok = all(
        s.skipped or (s.committed and s.done) for s in result.streams
    )
    any_continuation = any(
        s.committed and not s.done and not s.skipped for s in result.streams
    )
    if result.ok and streams_ok and result.streams:
        status = "completed"
        job.progress = release_partition_claim(
            job.progress, part["partition_key"],
            status="completed", claim_token=claim_token,
        )
        if next_runnable_partition(job.progress) is None:
            job.status = BackfillJobStatus.completed
            job.completed_at = now_iso()
        else:
            job.status = BackfillJobStatus.running
    elif result.ok and any_continuation:
        status = "continuation_pending"
        job.progress = release_partition_claim(
            job.progress, part["partition_key"],
            status="continuation_pending", claim_token=claim_token,
            continuation_pending=True,
        )
        job.status = BackfillJobStatus.running
    else:
        status = "failed"
        job.progress = release_partition_claim(
            job.progress, part["partition_key"],
            status="failed", claim_token=claim_token,
            last_error="partition sync degraded or failed",
        )
        job.status = BackfillJobStatus.failed
        job.last_error = "partition sync degraded or failed"

    if not store.cas_backfill_job(job, expected):
        # Stale worker lost the claim — do not overwrite successor progress.
        return {
            "job_id": job_id,
            "partition_key": part["partition_key"],
            "partition_status": "claim_lost",
            "job_status": "unknown",
            "health": result.health.value,
            "percepts": result.percepts,
            "done": False,
        }
    return {
        "job_id": job.id,
        "partition_key": part["partition_key"],
        "partition_status": status,
        "job_status": job.status.value,
        "health": result.health.value,
        "percepts": result.percepts,
        "done": job.status == BackfillJobStatus.completed,
        "continuation_pending": status == "continuation_pending",
    }


def pause_connector(store, connector_id: str) -> ConnectorInstance:
    return store.update_connector_instance(
        connector_id, status=ConnectorStatus.paused.value
    )


def resume_connector(store, connector_id: str) -> ConnectorInstance:
    instance = store.get_connector_instance(connector_id)
    if instance is None:
        raise ValueError(f"connector {connector_id} not found")
    if instance.status != ConnectorStatus.paused:
        raise ValueError(f"connector {connector_id} is {instance.status.value}, "
                         "not paused — only paused connectors resume")
    return store.update_connector_instance(
        connector_id, status=ConnectorStatus.active.value
    )


def revoke_connector(
    store, credentials: CredentialStore, connector_id: str,
) -> ConnectorInstance:
    """Resumable, verifiable revocation. Never claims a clean revocation
    while secret material may still exist:

        revoking → stop scheduler → delete secret → verify absent
                 → clear ref → revoked

    A failure leaves ``revoking`` (retryable) or
    ``revoked_with_residual_secret`` (sync stopped, cleanup owed)."""
    instance = store.get_connector_instance(connector_id)
    if instance is None:
        raise ValueError(f"connector {connector_id} not found")

    # 1. stop everything first — whatever happens next, no more fetches
    store.update_connector_instance(
        connector_id, status=ConnectorStatus.revoking.value)
    def _pause(state) -> None:
        state.paused = True
        state.status = HealthStatus.revoked

    store.apply_connector_sync_state(connector_id, _pause)

    # 2. destroy + verify secret material
    residual = False
    if instance.credential_ref:
        try:
            credentials.delete(instance.credential_ref)
        except Exception as exc:
            logger.warning("secret deletion failed for %s: %s",
                           connector_id, sanitize_error(exc))
            residual = True
        if not residual:
            try:
                residual = credentials.get(instance.credential_ref) is not None
            except Exception:
                residual = True  # cannot verify → do not claim clean
        if not residual:
            try:
                store.delete_credential_ref(instance.credential_ref)
            except Exception as exc:
                logger.warning("credential ref cleanup failed for %s: %s",
                               connector_id, sanitize_error(exc))

    if residual:
        # keep the ref so a later revoke retry can still find and destroy the
        # secret; never report this as a clean revocation
        return store.update_connector_instance(
            connector_id,
            status=ConnectorStatus.revoked_with_residual_secret.value,
            revoked_at=now_iso(),
        )
    return store.update_connector_instance(
        connector_id,
        status=ConnectorStatus.revoked.value,
        credential_ref=None,
        revoked_at=now_iso(),
    )


# -- dead-letter operations -----------------------------------------------------


def retry_dead_letter(
    store, credentials: CredentialStore, dlq_id: str, *,
    emit_percepts: bool = True,
) -> ConnectorDeadLetter:
    """Reprocess one dead letter from its raw item: normalize again and, on
    success, persist record/Percept idempotently and resolve the entry."""
    dlq = store.get_connector_dead_letter(dlq_id)
    if dlq is None:
        raise ValueError(f"dead letter {dlq_id} not found")
    if dlq.status in (DeadLetterStatus.resolved, DeadLetterStatus.discarded):
        return dlq
    if not dlq.raw_item_id:
        raise ValueError(f"dead letter {dlq_id} has no raw item to replay")
    raw = store.get_connector_raw_item(dlq.raw_item_id)
    if raw is None:
        raise ValueError(f"raw item {dlq.raw_item_id} not found")

    adapter, instance, account = _load_adapter(store, credentials, dlq.connector_id)
    dlq.attempts += 1
    dlq.status = DeadLetterStatus.retrying
    dlq.updated_at = now_iso()
    store.update_connector_dead_letter(dlq)

    from .models import ConnectorBatch  # counters only; not persisted
    scratch = ConnectorBatch(connector_id=instance.id, stream=dlq.stream)
    try:
        records = adapter.normalize(raw)
        with store.transaction():
            for rec in records:
                rec.idempotency_key = rec.idempotency_key or raw.idempotency_key
                rec.content_hash = rec.content_hash or hashlib.sha256(
                    rec.content.encode("utf-8")).hexdigest()
                existing = store.find_record_by_key(rec.idempotency_key)
                if existing is not None:
                    continue  # idempotent — already landed via another path
                persist_committed_record(store, account, instance, rec, scratch,
                                         emit_percepts=emit_percepts)
        dlq.status = DeadLetterStatus.resolved
        dlq.last_error = ""
    except Exception as exc:
        dlq.status = DeadLetterStatus.open
        dlq.last_error = sanitize_error(exc)
    dlq.updated_at = now_iso()
    store.update_connector_dead_letter(dlq)
    return dlq


def discard_dead_letter(store, dlq_id: str) -> ConnectorDeadLetter:
    dlq = store.get_connector_dead_letter(dlq_id)
    if dlq is None:
        raise ValueError(f"dead letter {dlq_id} not found")
    dlq.status = DeadLetterStatus.discarded
    dlq.updated_at = now_iso()
    store.update_connector_dead_letter(dlq)
    return dlq


def resolve_dead_letter(store, dlq_id: str) -> ConnectorDeadLetter:
    dlq = store.get_connector_dead_letter(dlq_id)
    if dlq is None:
        raise ValueError(f"dead letter {dlq_id} not found")
    dlq.status = DeadLetterStatus.resolved
    dlq.updated_at = now_iso()
    store.update_connector_dead_letter(dlq)
    return dlq
