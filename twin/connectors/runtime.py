"""The sync runtime: fetch → raw → normalize → quarantine → percept → checkpoint.

Invariant: connectors capture evidence; cognition creates understanding. This
module writes Raw items, Records and Percepts — never confirmed Memory or
Judgment. The checkpoint advances only when a batch fully commits.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from ..clock import now_iso
from ..sensory.percept import Percept
from .models import (
    BatchStatus,
    ConnectorBatch,
    ConnectorCheckpoint,
    ConnectorDeadLetter,
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
from .protocol import ConnectorError, FetchPage
from .quarantine import screen_record


@dataclass
class StreamResult:
    stream: str
    committed: bool = False
    raw: int = 0
    normalized: int = 0
    deduplicated: int = 0
    quarantined: int = 0
    percepts: int = 0
    failed: int = 0
    failure_class: Optional[str] = None
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
        "source_owner": account.source_owner,
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
            "source_owner": account.source_owner,
        },
        metadata=metadata,
        source_trust=float(conf.get("source_trust", account.source_trust)),
        source_scope=conf.get("source_scope", account.source_scope),
        source_confidentiality=conf.get("source_confidentiality", account.confidentiality),
    )


def _dlq(store, instance: ConnectorInstance, stream: str, *,
         external_id: str, external_type: str, failure_class: FailureClass,
         error: str, raw_item_id: Optional[str] = None) -> None:
    store.insert_connector_dead_letter(ConnectorDeadLetter(
        connector_id=instance.id,
        stream=stream,
        external_id=external_id,
        external_type=external_type,
        failure_class=failure_class.value,
        last_error=error[:500],
        raw_item_id=raw_item_id,
        status=DeadLetterStatus.open.value,
    ))


def _process_page(
    store, adapter, instance: ConnectorInstance, account: SourceAccount,
    batch: ConnectorBatch, page: FetchPage, *, emit_percepts: bool,
) -> None:
    ct = instance.connector_type
    for raw in page.raw_items:
        key = idempotency_key(
            ct, account.id, raw.external_type, raw.external_id, raw.external_revision
        )
        content_hash = _raw_hash(raw.payload, raw.deleted)
        existing_raw = store.find_raw_item_by_key(key)
        if existing_raw is not None and existing_raw.content_hash == content_hash:
            batch.deduplicated_count += 1
            continue  # idempotent: same object, same revision, already captured

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
        if existing_raw is None:
            store.insert_connector_raw_item(item)
        else:
            item.id = existing_raw.id
        batch.raw_count += 1

        try:
            records = adapter.normalize(item)
        except ConnectorError as exc:
            batch.failed_count += 1
            batch.failure_class = exc.failure_class.value
            _dlq(store, instance, batch.stream, external_id=raw.external_id,
                 external_type=raw.external_type, failure_class=exc.failure_class,
                 error=str(exc), raw_item_id=item.id)
            continue
        except Exception as exc:  # normalization bug → dead-letter, keep syncing
            batch.failed_count += 1
            batch.failure_class = FailureClass.normalization.value
            _dlq(store, instance, batch.stream, external_id=raw.external_id,
                 external_type=raw.external_type,
                 failure_class=FailureClass.normalization,
                 error=repr(exc), raw_item_id=item.id)
            continue

        for rec in records:
            rec.idempotency_key = rec.idempotency_key or key
            rec.content_hash = rec.content_hash or _hash(rec.content)
            rec.ownership = rec.ownership or _ownership(account, instance)
            rec.confidentiality = rec.confidentiality or _confidentiality(account)

            existing_rec = store.find_record_by_key(rec.idempotency_key)
            if existing_rec is not None and existing_rec.content_hash == rec.content_hash:
                batch.deduplicated_count += 1
                continue

            if rec.deleted:
                rec.percept_id = None
                if existing_rec is None:
                    store.insert_connector_record(rec)
                else:
                    rec.id = existing_rec.id
                    store.update_connector_record(rec)
                batch.normalized_count += 1
                continue

            quar = screen_record(store, rec)
            if quar is not None:
                rec.quarantined = True
                rec.percept_id = None
                if existing_rec is None:
                    store.insert_connector_record(rec)
                else:
                    rec.id = existing_rec.id
                    store.update_connector_record(rec)
                batch.quarantined_count += 1
                continue

            if existing_rec is None:
                store.insert_connector_record(rec)
            else:
                rec.id = existing_rec.id
                store.update_connector_record(rec)
            batch.normalized_count += 1

            if emit_percepts:
                percept = build_percept(account, instance, rec)
                pid = store.insert_percept(percept)
                if pid is not None:
                    rec.percept_id = pid
                    store.update_connector_record(rec)
                    batch.percept_count += 1


def run_sync(
    store, adapter, instance: ConnectorInstance, account: SourceAccount, *,
    streams: Optional[list[str]] = None, emit_percepts: bool = True,
) -> SyncResult:
    result = SyncResult(connector_id=instance.id)

    if instance.status in (ConnectorStatus.revoked.value, ConnectorStatus.paused.value):
        result.health = (
            HealthStatus.revoked if instance.status == ConnectorStatus.revoked.value
            else HealthStatus.paused
        )
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
    target_streams = streams or manifest.streams or ["default"]

    worst = HealthStatus.healthy
    for stream in target_streams:
        sr = _sync_stream(store, adapter, instance, account, stream,
                          emit_percepts=emit_percepts)
        result.streams.append(sr)
        if sr.failure_class in (
            FailureClass.authentication.value, FailureClass.authorization.value
        ):
            worst = HealthStatus.unauthorized
        elif not sr.committed and worst == HealthStatus.healthy:
            worst = HealthStatus.degraded

    result.health = worst
    _persist_health(store, instance, result)
    return result


def _sync_stream(
    store, adapter, instance: ConnectorInstance, account: SourceAccount,
    stream: str, *, emit_percepts: bool,
) -> StreamResult:
    checkpoint = store.get_connector_checkpoint(instance.id, stream)
    plan = adapter.plan_sync(account, checkpoint, stream=stream)
    batch = ConnectorBatch(
        connector_id=instance.id, stream=stream,
        status=BatchStatus.fetching.value, cursor_before=plan.cursor_before,
    )
    store.insert_connector_batch(batch)

    sr = StreamResult(stream=stream, batch_id=batch.id)
    cursor: Optional[dict[str, Any]] = plan.cursor_before or None
    last_page: Optional[FetchPage] = None
    try:
        while True:
            page = adapter.fetch_batch(plan, cursor)
            _process_page(store, adapter, instance, account, batch, page,
                          emit_percepts=emit_percepts)
            last_page = page
            cursor = page.cursor_after
            if page.done:
                break
    except ConnectorError as exc:
        batch.status = BatchStatus.failed.value
        batch.failure_class = exc.failure_class.value
        batch.error = str(exc)
        batch.completed_at = now_iso()
        store.update_connector_batch(batch)
        if not exc.retryable:
            _dlq(store, instance, stream, external_id=exc.external_id,
                 external_type=exc.external_type, failure_class=exc.failure_class,
                 error=str(exc))
        _fill_stream(sr, batch)
        return sr  # checkpoint NOT advanced

    # Never gap-advance: any item failure keeps the watermark where it was.
    if batch.failed_count > 0:
        batch.status = BatchStatus.partially_failed.value
        batch.completed_at = now_iso()
        store.update_connector_batch(batch)
        _fill_stream(sr, batch)
        return sr

    cursor_after = adapter.acknowledge(plan, last_page or FetchPage())
    batch.cursor_after_proposed = cursor_after or {}
    batch.status = BatchStatus.committed.value
    batch.completed_at = now_iso()
    store.update_connector_batch(batch)

    store.upsert_connector_checkpoint(ConnectorCheckpoint(
        connector_id=instance.id,
        stream=stream,
        cursor=cursor_after or {},
        lookback_seconds=plan.lookback_seconds,
        committed_batch_id=batch.id,
        adapter_version=instance.adapter_version,
        updated_at=now_iso(),
    ))
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
    sr.failure_class = batch.failure_class


def _persist_health(store, instance: ConnectorInstance, result: SyncResult) -> None:
    from .health import snapshot_health
    snapshot_health(store, instance.id, result.health)
