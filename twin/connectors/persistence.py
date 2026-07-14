"""Row serializers for connector-framework entities.

Sensitive tables (``connector_raw_items``, ``connector_records``) keep the full
model dump in an encrypted ``payload`` column; the store mixin handles the
codec. Everything else stores plaintext JSON — it never holds secrets.
"""

from __future__ import annotations

import json
from typing import Any

from .models import (
    ConnectorBatch,
    ConnectorCheckpoint,
    ConnectorDeadLetter,
    ConnectorDeletionEvent,
    ConnectorInstance,
    ConnectorRecord,
    ConnectorSyncState,
    CredentialRef,
    RawConnectorItem,
    SourceAccount,
)


def _j(value: Any) -> str:
    return json.dumps(value if value is not None else {}, default=str)


def _loads(raw: Any, default: Any = None):
    if raw is None:
        return default if default is not None else {}
    if isinstance(raw, (dict, list)):
        return raw
    return json.loads(raw)


def account_to_row(a: SourceAccount) -> dict[str, Any]:
    return {
        "id": a.id,
        "connector_type": a.connector_type,
        "source_owner": a.source_owner,
        "vault_id": a.vault_id,
        "enabled": 1 if a.enabled else 0,
        "payload": _j(a.model_dump(mode="json")),
    }


def row_to_account(row: Any) -> SourceAccount:
    return SourceAccount.model_validate(_loads(row["payload"], {}))


def instance_to_row(i: ConnectorInstance) -> dict[str, Any]:
    return {
        "id": i.id,
        "connector_type": i.connector_type,
        "account_id": i.account_id,
        "status": i.status,
        "credential_ref": i.credential_ref,
        "payload": _j(i.model_dump(mode="json")),
    }


def row_to_instance(row: Any) -> ConnectorInstance:
    return ConnectorInstance.model_validate(_loads(row["payload"], {}))


def credential_ref_to_row(c: CredentialRef) -> dict[str, Any]:
    return {"id": c.id, "provider": c.provider, "payload": _j(c.model_dump(mode="json"))}


def row_to_credential_ref(row: Any) -> CredentialRef:
    return CredentialRef.model_validate(_loads(row["payload"], {}))


def checkpoint_to_row(c: ConnectorCheckpoint) -> dict[str, Any]:
    return {
        "id": c.id,
        "connector_id": c.connector_id,
        "stream": c.stream,
        "version": c.version,  # column so CAS can guard in SQL
        "payload": _j(c.model_dump(mode="json")),
    }


def row_to_checkpoint(row: Any) -> ConnectorCheckpoint:
    return ConnectorCheckpoint.model_validate(_loads(row["payload"], {}))


def batch_to_row(b: ConnectorBatch) -> dict[str, Any]:
    return {
        "id": b.id,
        "connector_id": b.connector_id,
        "status": b.status,
        "created_at": b.started_at,
        "payload": _j(b.model_dump(mode="json")),
    }


def row_to_batch(row: Any) -> ConnectorBatch:
    return ConnectorBatch.model_validate(_loads(row["payload"], {}))


def raw_item_to_row(item: RawConnectorItem, payload_json: str) -> dict[str, Any]:
    """``payload_json`` is the (already-encrypted) full dump for the payload col."""
    return {
        "id": item.id,
        "connector_id": item.connector_id,
        "idempotency_key": item.idempotency_key,
        "content_hash": item.content_hash,
        "deleted": 1 if item.deleted else 0,
        "payload": payload_json,
    }


def record_to_row(record: ConnectorRecord, payload_json: str) -> dict[str, Any]:
    """The encrypted ``payload`` is the immutable canonical envelope.
    ``percept_id``/``quarantined`` are processing-state columns updated via
    ``set_connector_record_state`` — the payload is written once, never
    rewritten."""
    return {
        "id": record.id,
        "connector_id": record.connector_id,
        "idempotency_key": record.idempotency_key,
        "external_type": record.external_type,
        "external_id": record.external_id,
        "deleted": 1 if record.deleted else 0,
        "percept_id": record.percept_id,
        "quarantined": 1 if record.quarantined else 0,
        "payload": payload_json,
    }


def deletion_event_to_row(d: ConnectorDeletionEvent) -> dict[str, Any]:
    return {
        "id": d.id,
        "connector_id": d.connector_id,
        "external_type": d.external_type,
        "external_id": d.external_id,
        "status": d.status.value,
        "created_at": d.created_at,
        "payload": _j(d.model_dump(mode="json")),
    }


def row_to_deletion_event(row: Any) -> ConnectorDeletionEvent:
    return ConnectorDeletionEvent.model_validate(_loads(row["payload"], {}))


def dead_letter_to_row(d: ConnectorDeadLetter) -> dict[str, Any]:
    return {
        "id": d.id,
        "connector_id": d.connector_id,
        "external_id": d.external_id,
        "failure_class": d.failure_class,
        "status": d.status,
        "created_at": d.created_at,
        "payload": _j(d.model_dump(mode="json")),
    }


def row_to_dead_letter(row: Any) -> ConnectorDeadLetter:
    return ConnectorDeadLetter.model_validate(_loads(row["payload"], {}))


def sync_state_to_row(s: ConnectorSyncState) -> dict[str, Any]:
    return {
        "id": s.id,
        "status": s.status,
        "next_run_at": s.next_run_at,
        "payload": _j(s.model_dump(mode="json")),
    }


def row_to_sync_state(row: Any) -> ConnectorSyncState:
    return ConnectorSyncState.model_validate(_loads(row["payload"], {}))
