"""The sync runtime: fetch → stage → quarantine → atomic commit → checkpoint.

Invariants this module enforces:

- **Nothing becomes cognitively visible before a consistent commit.** Records
  and Percepts are staged in memory and persisted only inside the single
  transaction that also marks the batch committed and CAS-advances the
  checkpoint. A partially failed batch persists raw items (source cache, for
  DLQ replay) and dead letters — never Records or Percepts.
- **batch committed ⇔ checkpoint references that batch.** Both happen in one
  transaction; a failure between them is impossible by construction, and a
  checkpoint CAS conflict aborts the batch instead of committing it.
- **One worker per (connector, stream).** A stream lease is acquired before
  planning and released after; a concurrent sync observes ``already_running``.
- **External revisions are immutable.** The same idempotency key with a
  different content hash is a provider contract violation → dead letter with
  ``revision_collision``; existing evidence is never overwritten.
- **Deletions resolve lineage.** A tombstone locates every prior revision and
  its Percepts and files a ``ConnectorDeletionEvent`` for the deletion
  planner — it never cascades deletes or creates new content by itself.

This module writes Raw items, Records and Percepts — never confirmed Memory
or Judgment.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from ..clock import now_iso
from ..sensory.percept import Percept
from .errors import sanitize_error
from .models import (
    SYNCABLE_STATUSES,
    BatchStatus,
    ConnectorBatch,
    ConnectorCheckpoint,
    ConnectorDeadLetter,
    ConnectorDeletionEvent,
    ConnectorInstance,
    ConnectorRecord,
    ConnectorStatus,
    DeadLetterStatus,
    FailureClass,
    HealthStatus,
    RawConnectorItem,
    SourceAccount,
    idempotency_key,
)
from .protocol import ConnectorError, FetchPage, RawFetchItem
from .quarantine import screen_record

logger = logging.getLogger("twin.connectors.runtime")

LEASE_TTL_SECONDS = 600


class CheckpointConflict(RuntimeError):
    """The checkpoint moved underneath this batch — abort, never regress."""


class LeaseLost(RuntimeError):
    """This worker no longer holds the stream lease (fencing token stale) —
    it must stop publishing results, even mid-flight."""


@dataclass
class StreamResult:
    stream: str
    committed: bool = False
    skipped: Optional[str] = None      # e.g. "already_running"
    raw: int = 0
    normalized: int = 0
    deduplicated: int = 0
    quarantined: int = 0
    percepts: int = 0
    failed: int = 0
    deletion_events: int = 0
    failure_class: Optional[str] = None
    retry_after: Optional[int] = None  # provider-instructed wait (rate limits)
    batch_id: Optional[str] = None
    cursor_after: dict[str, Any] = field(default_factory=dict)


@dataclass
class SyncResult:
    connector_id: str
    health: HealthStatus = HealthStatus.healthy
    streams: list[StreamResult] = field(default_factory=list)

    @property
    def percepts(self) -> int:
        return sum(s.percepts for s in self.streams)

    @property
    def ok(self) -> bool:
        return self.health in (HealthStatus.healthy, HealthStatus.degraded)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _raw_hash(payload: dict[str, Any], deleted: bool) -> str:
    return _hash(json.dumps(payload, sort_keys=True, default=str) + f"|deleted={deleted}")


def _ownership(account: SourceAccount, instance: ConnectorInstance) -> dict[str, Any]:
    return {
        "source_account_id": account.id,
        "source_owner": account.source_owner.value,
        "vault_id": account.vault_id,
        "org_key": account.org_key,
        "connector_id": instance.id,
        "connector_type": instance.connector_type,
        "persona": account.persona,
    }


def _confidentiality(account: SourceAccount) -> dict[str, Any]:
    return {
        "confidentiality": account.confidentiality,
        "source_scope": account.source_scope,
        "source_trust": account.source_trust,
        "source_confidentiality": account.confidentiality,
    }


def build_percept(
    account: SourceAccount, instance: ConnectorInstance, record: ConnectorRecord,
) -> Percept:
    """Seal ownership/vault/source lineage into the Percept metadata."""
    ownership = record.ownership or _ownership(account, instance)
    conf = record.confidentiality or _confidentiality(account)
    metadata = {
        **ownership,
        "external_type": record.external_type,
        "external_id": record.external_id,
        "external_revision": record.external_revision,
        "connector_record_id": record.id,
        "idempotency_key": record.idempotency_key,
        "thread_key": record.thread_key,
        "project_hint": record.project_hint,
    }
    # instance-level candidate-policy override rides with the percept so the
    # extraction pipeline (not the adapter) can enforce it (§49–50)
    policy_override = (instance.configuration or {}).get("ingestion_policy")
    if isinstance(policy_override, dict) and policy_override:
        metadata["ingestion_policy"] = policy_override
    # source_metadata the cognitive layers may need (author kind, lineage…)
    if record.source_metadata:
        metadata["source_metadata"] = record.source_metadata
    return Percept(
        percept_type=f"connector_{record.external_type}",
        source_sensor=instance.connector_type,
        occurred_at=record.occurred_at,
        ingested_at=now_iso(),
        actors=record.actor_ids,
        content=record.content,
        content_refs=[{
            "connector_id": instance.id,
            "source_account_id": account.id,
            "external_type": record.external_type,
            "external_id": record.external_id,
            "external_revision": record.external_revision,
            "record_id": record.id,
        }],
        privacy_hints={
            "domain_hint": account.default_domain,
            "sensitivity_hint": conf.get("confidentiality", "internal"),
            "vault_id": account.vault_id,
            "source_owner": account.source_owner.value,
        },
        metadata=metadata,
        source_trust=float(conf.get("source_trust", account.source_trust)),
        source_scope=conf.get("source_scope", account.source_scope),
        source_confidentiality=conf.get("source_confidentiality", account.confidentiality),
    )


# -- staging ------------------------------------------------------------------
#
# Fetch and normalization run OUTSIDE any transaction and produce a plan of
# what would be persisted. Nothing cognitive is written until the batch can
# commit as a whole. A batch must be idempotent even within itself: the
# staged indexes dedupe (and collision-check) duplicates the provider sends
# twice in the same page or across pages of one fetch.


@dataclass
class _Staged:
    new_raw_items: list[RawConnectorItem] = field(default_factory=list)
    records: list[ConnectorRecord] = field(default_factory=list)
    dead_letters: list[ConnectorDeadLetter] = field(default_factory=list)
    # in-batch idempotency: everything seen in THIS batch, keyed like the store
    raw_by_key: dict[str, RawConnectorItem] = field(default_factory=dict)
    record_by_key: dict[str, ConnectorRecord] = field(default_factory=dict)


def _stage_dlq(
    staged: _Staged, batch: ConnectorBatch, instance: ConnectorInstance, *,
    external_id: str, external_type: str, failure_class: FailureClass,
    exc: BaseException | str, raw_item_id: Optional[str] = None,
) -> None:
    batch.failed_count += 1
    batch.failure_class = failure_class
    staged.dead_letters.append(ConnectorDeadLetter(
        connector_id=instance.id,
        stream=batch.stream,
        external_id=external_id,
        external_type=external_type,
        failure_class=failure_class,
        last_error=sanitize_error(exc),
        raw_item_id=raw_item_id,
        status=DeadLetterStatus.open,
    ))


def stage_raw_fetch_item(
    store, adapter, instance: ConnectorInstance, account: SourceAccount,
    batch: ConnectorBatch, staged: _Staged, raw: RawFetchItem,
) -> None:
    """Stage one raw object: dedupe (store AND in-batch), collision-check,
    normalize — all in memory."""
    ct = instance.connector_type
    key = idempotency_key(
        ct, account.id, raw.external_type, raw.external_id, raw.external_revision
    )
    content_hash = _raw_hash(raw.payload, raw.deleted)

    staged_raw = staged.raw_by_key.get(key)
    if staged_raw is not None:
        if staged_raw.content_hash == content_hash:
            batch.deduplicated_count += 1  # provider sent the item twice
        else:
            _stage_dlq(
                staged, batch, instance,
                external_id=raw.external_id, external_type=raw.external_type,
                failure_class=FailureClass.revision_collision,
                exc=(f"provider returned two different payloads for revision "
                     f"{raw.external_revision} within one batch"),
                raw_item_id=staged_raw.id,
            )
        return

    existing_raw = store.find_raw_item_by_key(key)
    if existing_raw is not None and existing_raw.content_hash != content_hash:
        # same external revision, different content: contract violation —
        # the stored evidence is NEVER overwritten
        _stage_dlq(
            staged, batch, instance,
            external_id=raw.external_id, external_type=raw.external_type,
            failure_class=FailureClass.revision_collision,
            exc=(f"provider returned different content for already-observed "
                 f"revision {raw.external_revision}"),
            raw_item_id=existing_raw.id,
        )
        return

    if existing_raw is not None:
        item = existing_raw  # same revision, same content — already captured
    else:
        item = RawConnectorItem(
            connector_id=instance.id,
            source_account_id=account.id,
            external_type=raw.external_type,
            external_id=raw.external_id,
            external_revision=raw.external_revision,
            idempotency_key=key,
            content_hash=content_hash,
            payload=raw.payload,
            deleted=raw.deleted,
            metadata={"occurred_at": raw.occurred_at},
        )
        staged.new_raw_items.append(item)
    staged.raw_by_key[key] = item
    batch.raw_count += 1

    try:
        records = adapter.normalize(item)
    except ConnectorError as exc:
        _stage_dlq(staged, batch, instance, external_id=raw.external_id,
                   external_type=raw.external_type, failure_class=exc.failure_class,
                   exc=exc, raw_item_id=item.id)
        return
    except Exception as exc:  # normalization bug → dead-letter, keep staging
        _stage_dlq(staged, batch, instance, external_id=raw.external_id,
                   external_type=raw.external_type,
                   failure_class=FailureClass.normalization,
                   exc=exc, raw_item_id=item.id)
        return

    for rec in records:
        rec.idempotency_key = rec.idempotency_key or key
        rec.content_hash = rec.content_hash or _hash(rec.content)
        rec.ownership = rec.ownership or _ownership(account, instance)
        rec.confidentiality = rec.confidentiality or _confidentiality(account)

        staged_rec = staged.record_by_key.get(rec.idempotency_key)
        if staged_rec is not None:
            if staged_rec.content_hash == rec.content_hash:
                batch.deduplicated_count += 1
            else:
                _stage_dlq(
                    staged, batch, instance,
                    external_id=rec.external_id, external_type=rec.external_type,
                    failure_class=FailureClass.revision_collision,
                    exc=("two different normalizations for revision "
                         f"{rec.external_revision} within one batch"),
                    raw_item_id=item.id,
                )
            continue

        existing_rec = store.find_record_by_key(rec.idempotency_key)
        if existing_rec is not None:
            if existing_rec.content_hash == rec.content_hash:
                batch.deduplicated_count += 1
                continue
            # persisted records are immutable per revision — a different
            # normalization under the same key is a collision, not an update
            _stage_dlq(
                staged, batch, instance,
                external_id=rec.external_id, external_type=rec.external_type,
                failure_class=FailureClass.revision_collision,
                exc=("normalized content changed for already-persisted "
                     f"revision {rec.external_revision}"),
                raw_item_id=item.id,
            )
            continue

        staged.records.append(rec)
        staged.record_by_key[rec.idempotency_key] = rec
        batch.normalized_count += 1


def _persist_partial(store, batch: ConnectorBatch, staged: _Staged) -> None:
    """A failed batch persists ONLY non-cognitive material: raw items (source
    cache, needed for DLQ replay) and dead letters. No Records, no Percepts —
    nothing from an uncommitted stream is visible to extraction."""
    with store.transaction():
        for item in staged.new_raw_items:
            store.insert_connector_raw_item(item)
        for dlq in staged.dead_letters:
            store.insert_connector_dead_letter(dlq)
        batch.status = BatchStatus.partially_failed
        batch.completed_at = now_iso()
        store.update_connector_batch(batch)


def persist_committed_record(
    store, account: SourceAccount, instance: ConnectorInstance,
    rec: ConnectorRecord, batch: ConnectorBatch, *, emit_percepts: bool,
) -> None:
    """Persist one staged record inside the commit transaction: quarantine
    screen → immutable record row → optional Percept → processing state."""
    if rec.deleted:
        rec.percept_id = None
        store.insert_connector_record(rec)
        return
    quar = screen_record(store, rec)
    if quar is not None:
        rec.quarantined = True
        rec.percept_id = None
        store.insert_connector_record(rec)
        batch.quarantined_count += 1
        return
    store.insert_connector_record(rec)
    if emit_percepts:
        percept = build_percept(account, instance, rec)
        pid = store.insert_percept(percept)
        if pid is not None:
            rec.percept_id = pid
            # processing state only — the canonical payload is never rewritten
            store.set_connector_record_state(rec.id, percept_id=pid)
            batch.percept_count += 1


def _finalize_committed(
    store, instance: ConnectorInstance, account: SourceAccount,
    batch: ConnectorBatch, staged: _Staged, *,
    cursor_after: dict[str, Any], plan, expected_version: int,
    emit_percepts: bool, lease_owner: str, fencing_token: int,
) -> int:
    """The single transaction that makes a stream's evidence visible:

        lease fence check
        + raw + records + percepts + deletion events
        + batch committed
        + checkpoint CAS

    All of it or none of it. ``batch committed ⇔ checkpoint references it``,
    and only the worker that still holds the lease (same fencing token) may
    publish. Returns the number of deletion events filed."""
    deletion_events = 0
    with store.transaction():
        # fencing write: a worker whose lease expired (or was taken over)
        # cannot publish, even though it is still running
        if not store.renew_stream_lease(instance.id, batch.stream, lease_owner,
                                        fencing_token,
                                        ttl_seconds=LEASE_TTL_SECONDS):
            raise LeaseLost(
                f"lease for {instance.id}/{batch.stream} no longer held "
                f"(fencing token {fencing_token})"
            )
        for item in staged.new_raw_items:
            store.insert_connector_raw_item(item)
        for rec in staged.records:
            persist_committed_record(store, account, instance, rec, batch,
                                     emit_percepts=emit_percepts)
        # deletion events resolve AFTER records/percepts persisted, so a
        # revision created earlier in this same batch is part of the lineage
        for rec in staged.records:
            if not rec.deleted:
                continue
            prior = [
                p for p in store.list_connector_records_for_object(
                    instance.id, rec.external_type, rec.external_id)
                if not p.deleted and p.id != rec.id
            ]
            store.insert_connector_deletion_event(ConnectorDeletionEvent(
                connector_id=instance.id,
                source_account_id=account.id,
                external_type=rec.external_type,
                external_id=rec.external_id,
                tombstone_revision=rec.external_revision,
                prior_record_ids=[p.id for p in prior],
                affected_percept_ids=[p.percept_id for p in prior if p.percept_id],
                vault_id=account.vault_id,
            ))
            deletion_events += 1
        batch.status = BatchStatus.committed
        batch.completed_at = now_iso()
        batch.cursor_after_proposed = cursor_after or {}
        store.update_connector_batch(batch)
        ok = store.cas_connector_checkpoint(
            ConnectorCheckpoint(
                connector_id=instance.id,
                stream=batch.stream,
                cursor=cursor_after or {},
                lookback_seconds=plan.lookback_seconds,
                committed_batch_id=batch.id,
                adapter_version=instance.adapter_version,
                updated_at=now_iso(),
            ),
            expected_version=expected_version,
        )
        if not ok:
            # someone advanced the stream while we ran without a valid lease
            # window — abort the whole transaction rather than regress
            raise CheckpointConflict(
                f"checkpoint for {instance.id}/{batch.stream} moved "
                f"(expected version {expected_version})"
            )
    return deletion_events


def run_sync(
    store, adapter, instance: ConnectorInstance, account: SourceAccount, *,
    streams: Optional[list[str]] = None, emit_percepts: bool = True,
    lease_owner: Optional[str] = None,
) -> SyncResult:
    result = SyncResult(connector_id=instance.id)

    if instance.status not in SYNCABLE_STATUSES:
        if instance.status in (ConnectorStatus.revoked,
                               ConnectorStatus.revoking,
                               ConnectorStatus.revoked_with_residual_secret):
            result.health = HealthStatus.revoked
        elif instance.status == ConnectorStatus.paused:
            result.health = HealthStatus.paused
        else:  # provisioning / awaiting_auth / failed …
            result.health = HealthStatus.unauthorized
        _persist_health(store, instance, result)
        return result

    health = adapter.validate_credentials()
    if health.status == HealthStatus.unauthorized:
        result.health = HealthStatus.unauthorized
        store.update_connector_instance(
            instance.id, status=ConnectorStatus.unauthorized.value,
            last_health_check=now_iso(),
        )
        _persist_health(store, instance, result)
        return result

    manifest = adapter.adapter_manifest()
    target_streams = streams
    if not target_streams:
        plan_streams = getattr(adapter, "plan_streams", None)
        if callable(plan_streams):
            target_streams = plan_streams(account)
    if not target_streams:
        if manifest.dynamic_streams:
            result.health = HealthStatus.awaiting_configuration
            _persist_health(store, instance, result)
            return result
        target_streams = manifest.streams or ["default"]
    owner = lease_owner or f"worker_{uuid.uuid4().hex[:12]}"

    # Cap how many durable continuation batches one sync call may commit per
    # stream. 0 / missing = keep going until the window finishes (or fails).
    max_batches = int((instance.configuration or {})
                      .get("max_batches_per_stream") or 0)

    worst = HealthStatus.healthy
    for stream in target_streams:
        batches = 0
        while True:
            sr = _sync_stream(store, adapter, instance, account, stream,
                              emit_percepts=emit_percepts, lease_owner=owner)
            result.streams.append(sr)
            batches += 1
            if sr.skipped:
                break  # another worker owns the stream — not a health problem
            if sr.failure_class in (
                FailureClass.authentication.value, FailureClass.authorization.value
            ):
                worst = HealthStatus.unauthorized
            elif not sr.committed and worst == HealthStatus.healthy:
                worst = HealthStatus.degraded
            if not sr.committed:
                break
            if not _window_incomplete(sr.cursor_after):
                break
            if max_batches and batches >= max_batches:
                break

    result.health = worst
    _persist_health(store, instance, result)
    return result


def _window_incomplete(cursor: Optional[dict[str, Any]]) -> bool:
    """Durable continuation cursor: watermark not yet promoted."""
    return bool(cursor and cursor.get("substream") and "progress" in cursor)


def _sync_stream(
    store, adapter, instance: ConnectorInstance, account: SourceAccount,
    stream: str, *, emit_percepts: bool, lease_owner: str,
) -> StreamResult:
    fencing_token = store.acquire_stream_lease(instance.id, stream, lease_owner,
                                               ttl_seconds=LEASE_TTL_SECONDS)
    if fencing_token is None:
        logger.info("stream %s/%s already leased; skipping", instance.id, stream)
        return StreamResult(stream=stream, skipped="already_running")
    try:
        return _sync_stream_leased(store, adapter, instance, account, stream,
                                   emit_percepts=emit_percepts,
                                   lease_owner=lease_owner,
                                   fencing_token=fencing_token)
    finally:
        # fenced release: if the lease expired mid-run and someone else took
        # it over (even under the same owner string), this stale token no
        # longer matches and the successor's lease is left untouched
        store.release_stream_lease(instance.id, stream, lease_owner,
                                   fencing_token)


def _abort_batch(store, batch: ConnectorBatch, sr: StreamResult,
                 exc: BaseException) -> None:
    """A finalize that failed for ANY reason leaves the batch in a terminal,
    diagnosable state — never dangling in `fetching` — with the previous
    checkpoint intact and nothing cognitive persisted (the transaction
    rolled back)."""
    logger.warning("aborting batch %s: %s", batch.id, sanitize_error(exc))
    batch.status = BatchStatus.aborted
    if batch.failure_class is None:
        batch.failure_class = FailureClass.storage
    batch.error = sanitize_error(exc)
    batch.completed_at = now_iso()
    # counters describe what was staged, but nothing cognitive persisted
    batch.percept_count = 0
    batch.quarantined_count = 0
    try:
        store.update_connector_batch(batch)
    except Exception:  # even this failing must not mask the original error
        logger.exception("could not persist aborted state for batch %s", batch.id)
    _fill_stream(sr, batch)


def _sync_stream_leased(
    store, adapter, instance: ConnectorInstance, account: SourceAccount,
    stream: str, *, emit_percepts: bool, lease_owner: str, fencing_token: int,
) -> StreamResult:
    checkpoint = store.get_connector_checkpoint(instance.id, stream)
    expected_version = checkpoint.version if checkpoint else 0
    plan = adapter.plan_sync(account, checkpoint, stream=stream)
    batch = ConnectorBatch(
        connector_id=instance.id, stream=stream,
        status=BatchStatus.fetching, cursor_before=plan.cursor_before,
    )
    store.insert_connector_batch(batch)

    sr = StreamResult(stream=stream, batch_id=batch.id)
    staged = _Staged()
    cursor: Optional[dict[str, Any]] = plan.cursor_before or None
    last_page: Optional[FetchPage] = None
    try:
        # 1. fetch + stage — outside any transaction, nothing persisted yet.
        # The lease is renewed after every page so a slow provider or a long
        # backfill never outlives its authority silently.
        while True:
            page = adapter.fetch_batch(plan, cursor)
            for raw in page.raw_items:
                stage_raw_fetch_item(store, adapter, instance, account,
                                     batch, staged, raw)
            last_page = page
            cursor = page.cursor_after
            if not store.renew_stream_lease(instance.id, stream, lease_owner,
                                            fencing_token,
                                            ttl_seconds=LEASE_TTL_SECONDS):
                raise LeaseLost(
                    f"lease for {instance.id}/{stream} lost mid-fetch "
                    f"(fencing token {fencing_token})"
                )
            if page.done:
                break
    except LeaseLost as exc:
        _abort_batch(store, batch, sr, exc)
        return sr  # another worker owns the stream now; publish nothing
    except ConnectorError as exc:
        batch.status = BatchStatus.failed
        batch.failure_class = exc.failure_class
        batch.error = sanitize_error(exc)
        batch.completed_at = now_iso()
        sr.retry_after = exc.retry_after
        with store.transaction():
            for item in staged.new_raw_items:
                store.insert_connector_raw_item(item)
            for dlq in staged.dead_letters:
                store.insert_connector_dead_letter(dlq)
            if not exc.retryable:
                store.insert_connector_dead_letter(ConnectorDeadLetter(
                    connector_id=instance.id, stream=stream,
                    external_id=exc.external_id, external_type=exc.external_type,
                    failure_class=exc.failure_class,
                    last_error=sanitize_error(exc),
                ))
            store.update_connector_batch(batch)
        _fill_stream(sr, batch)
        return sr  # checkpoint NOT advanced

    # 2a. any item failure → nothing cognitive persists, watermark stays put
    if batch.failed_count > 0:
        _persist_partial(store, batch, staged)
        _fill_stream(sr, batch)
        return sr

    # 2b. full success → single atomic finalize (fenced)
    cursor_after = adapter.acknowledge(plan, last_page or FetchPage())
    try:
        sr.deletion_events = _finalize_committed(
            store, instance, account, batch, staged,
            cursor_after=cursor_after or {}, plan=plan,
            expected_version=expected_version, emit_percepts=emit_percepts,
            lease_owner=lease_owner, fencing_token=fencing_token,
        )
    except (CheckpointConflict, LeaseLost) as exc:
        _abort_batch(store, batch, sr, exc)
        return sr
    except Exception as exc:
        # unexpected storage/normalization failure inside the transaction:
        # terminal aborted state, checkpoint preserved — then re-raise, a
        # framework bug must stay visible
        _abort_batch(store, batch, sr, exc)
        raise

    sr.committed = True
    sr.cursor_after = cursor_after or {}
    _fill_stream(sr, batch)
    return sr


def _fill_stream(sr: StreamResult, batch: ConnectorBatch) -> None:
    sr.raw = batch.raw_count
    sr.normalized = batch.normalized_count
    sr.deduplicated = batch.deduplicated_count
    sr.quarantined = batch.quarantined_count
    sr.percepts = batch.percept_count
    sr.failed = batch.failed_count
    sr.failure_class = batch.failure_class.value if batch.failure_class else None


def _persist_health(store, instance: ConnectorInstance, result: SyncResult) -> None:
    from .health import snapshot_health
    retry_after = max(
        (s.retry_after for s in result.streams if s.retry_after), default=None,
    )
    snapshot_health(store, instance.id, result.health, retry_after=retry_after)
