"""Connector-framework store mixin — shared CRUD for SQLite and Postgres.

Idempotency lives here: raw items and records are keyed by a stable
``idempotency_key`` so a repeated fetch never duplicates. Raw payloads and
normalized content are encrypted at rest via ``self.codec``.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from twin.connectors.models import (
    ConnectorBatch,
    ConnectorCheckpoint,
    ConnectorDeadLetter,
    ConnectorInstance,
    ConnectorRecord,
    ConnectorSyncState,
    CredentialRef,
    RawConnectorItem,
    SourceAccount,
)
from twin.connectors.persistence import (
    account_to_row,
    batch_to_row,
    checkpoint_to_row,
    credential_ref_to_row,
    dead_letter_to_row,
    instance_to_row,
    raw_item_to_row,
    record_to_row,
    row_to_account,
    row_to_batch,
    row_to_checkpoint,
    row_to_credential_ref,
    row_to_dead_letter,
    row_to_instance,
    row_to_sync_state,
    sync_state_to_row,
)


class ConnectorStoreMixin:
    """Duck-typed connector persistence. Mix into SqliteStore / PostgresStore."""

    def _c_insert(self, table: str, row: dict[str, Any]) -> None:
        cols = list(row.keys())
        ph = ", ".join("?" for _ in cols)
        self._j_exec(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({ph})",
            tuple(row[c] for c in cols),
        )
        self._j_commit()

    def _c_update(self, table: str, entity_id: str, row: dict[str, Any]) -> None:
        cols = [c for c in row if c != "id"]
        sets = ", ".join(f"{c} = ?" for c in cols)
        self._j_exec(
            f"UPDATE {table} SET {sets} WHERE id = ?",
            tuple(row[c] for c in cols) + (entity_id,),
        )
        self._j_commit()

    def _enc(self, model: Any) -> str:
        return self.codec.encrypt(json.dumps(model.model_dump(mode="json"), default=str))

    # -- source accounts --------------------------------------------------

    def insert_source_account(self, account: SourceAccount) -> str:
        self._c_insert("connector_source_accounts", account_to_row(account))
        return account.id

    def get_source_account(self, account_id: str) -> Optional[SourceAccount]:
        row = self._j_fetchone(
            "SELECT * FROM connector_source_accounts WHERE id = ?", (account_id,)
        )
        return row_to_account(row) if row else None

    def list_source_accounts(
        self, connector_type: Optional[str] = None,
    ) -> list[SourceAccount]:
        if connector_type:
            rows = self._j_fetchall(
                "SELECT * FROM connector_source_accounts WHERE connector_type = ?"
                " ORDER BY id", (connector_type,),
            )
        else:
            rows = self._j_fetchall(
                "SELECT * FROM connector_source_accounts ORDER BY id", ()
            )
        return [row_to_account(r) for r in rows]

    def update_source_account(self, account_id: str, **fields: Any) -> SourceAccount:
        acc = self.get_source_account(account_id)
        if acc is None:
            raise ValueError(f"source account {account_id} not found")
        data = acc.model_dump(mode="json")
        data.update(fields)
        updated = SourceAccount.model_validate(data)
        self._c_update("connector_source_accounts", account_id, account_to_row(updated))
        return updated

    # -- connector instances ----------------------------------------------

    def insert_connector_instance(self, instance: ConnectorInstance) -> str:
        self._c_insert("connector_instances", instance_to_row(instance))
        return instance.id

    def get_connector_instance(self, connector_id: str) -> Optional[ConnectorInstance]:
        row = self._j_fetchone(
            "SELECT * FROM connector_instances WHERE id = ?", (connector_id,)
        )
        return row_to_instance(row) if row else None

    def list_connector_instances(
        self, connector_type: Optional[str] = None,
    ) -> list[ConnectorInstance]:
        if connector_type:
            rows = self._j_fetchall(
                "SELECT * FROM connector_instances WHERE connector_type = ? ORDER BY id",
                (connector_type,),
            )
        else:
            rows = self._j_fetchall("SELECT * FROM connector_instances ORDER BY id", ())
        return [row_to_instance(r) for r in rows]

    def update_connector_instance(
        self, connector_id: str, **fields: Any
    ) -> ConnectorInstance:
        inst = self.get_connector_instance(connector_id)
        if inst is None:
            raise ValueError(f"connector {connector_id} not found")
        data = inst.model_dump(mode="json")
        data.update(fields)
        updated = ConnectorInstance.model_validate(data)
        self._c_update("connector_instances", connector_id, instance_to_row(updated))
        return updated

    # -- credential refs (metadata only) ----------------------------------

    def insert_credential_ref(self, ref: CredentialRef) -> str:
        self._c_insert("connector_credential_refs", credential_ref_to_row(ref))
        return ref.id

    def get_credential_ref(self, credential_ref: str) -> Optional[CredentialRef]:
        row = self._j_fetchone(
            "SELECT * FROM connector_credential_refs WHERE id = ?", (credential_ref,)
        )
        return row_to_credential_ref(row) if row else None

    def update_credential_ref(self, credential_ref: str, **fields: Any) -> CredentialRef:
        ref = self.get_credential_ref(credential_ref)
        if ref is None:
            raise ValueError(f"credential {credential_ref} not found")
        data = ref.model_dump(mode="json")
        data.update(fields)
        updated = CredentialRef.model_validate(data)
        self._c_update(
            "connector_credential_refs", credential_ref, credential_ref_to_row(updated)
        )
        return updated

    def delete_credential_ref(self, credential_ref: str) -> None:
        self._j_exec(
            "DELETE FROM connector_credential_refs WHERE id = ?", (credential_ref,)
        )
        self._j_commit()

    # -- checkpoints (advance only on commit) -----------------------------

    def get_connector_checkpoint(
        self, connector_id: str, stream: str,
    ) -> Optional[ConnectorCheckpoint]:
        row = self._j_fetchone(
            "SELECT * FROM connector_checkpoints WHERE connector_id = ? AND stream = ?",
            (connector_id, stream),
        )
        return row_to_checkpoint(row) if row else None

    def list_connector_checkpoints(self, connector_id: str) -> list[ConnectorCheckpoint]:
        rows = self._j_fetchall(
            "SELECT * FROM connector_checkpoints WHERE connector_id = ? ORDER BY stream",
            (connector_id,),
        )
        return [row_to_checkpoint(r) for r in rows]

    def upsert_connector_checkpoint(
        self, checkpoint: ConnectorCheckpoint,
    ) -> ConnectorCheckpoint:
        existing = self.get_connector_checkpoint(
            checkpoint.connector_id, checkpoint.stream
        )
        if existing is None:
            self._c_insert("connector_checkpoints", checkpoint_to_row(checkpoint))
            return checkpoint
        merged = checkpoint.model_copy(update={"id": existing.id})
        self._c_update("connector_checkpoints", existing.id, checkpoint_to_row(merged))
        return merged

    # -- batches ----------------------------------------------------------

    def insert_connector_batch(self, batch: ConnectorBatch) -> str:
        self._c_insert("connector_batches", batch_to_row(batch))
        return batch.id

    def get_connector_batch(self, batch_id: str) -> Optional[ConnectorBatch]:
        row = self._j_fetchone(
            "SELECT * FROM connector_batches WHERE id = ?", (batch_id,)
        )
        return row_to_batch(row) if row else None

    def update_connector_batch(self, batch: ConnectorBatch) -> None:
        self._c_update("connector_batches", batch.id, batch_to_row(batch))

    def list_connector_batches(
        self, connector_id: str, limit: int = 50,
    ) -> list[ConnectorBatch]:
        rows = self._j_fetchall(
            "SELECT * FROM connector_batches WHERE connector_id = ?"
            " ORDER BY created_at DESC LIMIT ?",
            (connector_id, limit),
        )
        return [row_to_batch(r) for r in rows]

    # -- raw items (encrypted payload) ------------------------------------

    def insert_connector_raw_item(self, item: RawConnectorItem) -> str:
        self._c_insert(
            "connector_raw_items", raw_item_to_row(item, self._enc(item))
        )
        return item.id

    def _decode_raw_item(self, row: Any) -> RawConnectorItem:
        return RawConnectorItem.model_validate(
            json.loads(self.codec.decrypt(row["payload"]))
        )

    def get_connector_raw_item(self, item_id: str) -> Optional[RawConnectorItem]:
        row = self._j_fetchone(
            "SELECT * FROM connector_raw_items WHERE id = ?", (item_id,)
        )
        return self._decode_raw_item(row) if row else None

    def find_raw_item_by_key(self, key: str) -> Optional[RawConnectorItem]:
        row = self._j_fetchone(
            "SELECT * FROM connector_raw_items WHERE idempotency_key = ?", (key,)
        )
        return self._decode_raw_item(row) if row else None

    def list_connector_raw_items(self, connector_id: str) -> list[RawConnectorItem]:
        rows = self._j_fetchall(
            "SELECT * FROM connector_raw_items WHERE connector_id = ? ORDER BY id",
            (connector_id,),
        )
        return [self._decode_raw_item(r) for r in rows]

    # -- records (encrypted content) --------------------------------------

    def insert_connector_record(self, record: ConnectorRecord) -> str:
        self._c_insert("connector_records", record_to_row(record, self._enc(record)))
        return record.id

    def _decode_record(self, row: Any) -> ConnectorRecord:
        return ConnectorRecord.model_validate(
            json.loads(self.codec.decrypt(row["payload"]))
        )

    def get_connector_record(self, record_id: str) -> Optional[ConnectorRecord]:
        row = self._j_fetchone(
            "SELECT * FROM connector_records WHERE id = ?", (record_id,)
        )
        return self._decode_record(row) if row else None

    def find_record_by_key(self, key: str) -> Optional[ConnectorRecord]:
        row = self._j_fetchone(
            "SELECT * FROM connector_records WHERE idempotency_key = ?", (key,)
        )
        return self._decode_record(row) if row else None

    def list_connector_records(self, connector_id: str) -> list[ConnectorRecord]:
        rows = self._j_fetchall(
            "SELECT * FROM connector_records WHERE connector_id = ? ORDER BY id",
            (connector_id,),
        )
        return [self._decode_record(r) for r in rows]

    def update_connector_record(self, record: ConnectorRecord) -> None:
        self._c_update(
            "connector_records", record.id, record_to_row(record, self._enc(record))
        )

    # -- dead letters -----------------------------------------------------

    def insert_connector_dead_letter(self, dlq: ConnectorDeadLetter) -> str:
        self._c_insert("connector_dead_letters", dead_letter_to_row(dlq))
        return dlq.id

    def list_connector_dead_letters(
        self, connector_id: str, status: Optional[str] = None,
    ) -> list[ConnectorDeadLetter]:
        if status:
            rows = self._j_fetchall(
                "SELECT * FROM connector_dead_letters WHERE connector_id = ?"
                " AND status = ? ORDER BY created_at DESC",
                (connector_id, status),
            )
        else:
            rows = self._j_fetchall(
                "SELECT * FROM connector_dead_letters WHERE connector_id = ?"
                " ORDER BY created_at DESC",
                (connector_id,),
            )
        return [row_to_dead_letter(r) for r in rows]

    def update_connector_dead_letter(self, dlq: ConnectorDeadLetter) -> None:
        self._c_update("connector_dead_letters", dlq.id, dead_letter_to_row(dlq))

    # -- sync state -------------------------------------------------------

    def upsert_connector_sync_state(
        self, state: ConnectorSyncState,
    ) -> ConnectorSyncState:
        existing = self.get_connector_sync_state(state.id)
        if existing is None:
            self._c_insert("connector_sync_state", sync_state_to_row(state))
        else:
            self._c_update("connector_sync_state", state.id, sync_state_to_row(state))
        return state

    def get_connector_sync_state(
        self, connector_id: str,
    ) -> Optional[ConnectorSyncState]:
        row = self._j_fetchone(
            "SELECT * FROM connector_sync_state WHERE id = ?", (connector_id,)
        )
        return row_to_sync_state(row) if row else None

    def list_connector_sync_states(self) -> list[ConnectorSyncState]:
        rows = self._j_fetchall("SELECT * FROM connector_sync_state", ())
        return [row_to_sync_state(r) for r in rows]
