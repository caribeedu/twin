"""Connector-framework store mixin — shared CRUD for SQLite and Postgres.

Idempotency lives here: raw items and records are keyed by a stable
``idempotency_key`` so a repeated fetch never duplicates. Raw payloads and
normalized content are encrypted at rest via ``self.codec``.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from twin.clock import now_iso
from twin.connectors.models import (
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
from twin.connectors.persistence import (
    account_to_row,
    batch_to_row,
    checkpoint_to_row,
    credential_ref_to_row,
    dead_letter_to_row,
    deletion_event_to_row,
    instance_to_row,
    raw_item_to_row,
    record_to_row,
    row_to_account,
    row_to_batch,
    row_to_checkpoint,
    row_to_credential_ref,
    row_to_dead_letter,
    row_to_deletion_event,
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

    # -- checkpoints (advance only on commit, guarded by CAS) --------------

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

    def cas_connector_checkpoint(
        self, checkpoint: ConnectorCheckpoint, expected_version: int,
    ) -> bool:
        """Compare-and-set: the checkpoint advances only from the exact
        version the batch started from. A stale worker (or an out-of-order
        retry) gets False and must abort — a newer cursor is never
        overwritten by an older one."""
        existing = self.get_connector_checkpoint(
            checkpoint.connector_id, checkpoint.stream
        )
        if existing is None:
            if expected_version != 0:
                return False
            fresh = checkpoint.model_copy(update={"version": 1})
            try:
                self._c_insert("connector_checkpoints", checkpoint_to_row(fresh))
            except Exception:  # unique(connector,stream) race — someone else won
                return False
            return True
        if existing.version != expected_version:
            return False
        merged = checkpoint.model_copy(
            update={"id": existing.id, "version": expected_version + 1,
                    "created_at": existing.created_at}
        )
        row = checkpoint_to_row(merged)
        cols = [c for c in row if c != "id"]
        sets = ", ".join(f"{c} = ?" for c in cols)
        cur = self._j_exec(
            f"UPDATE connector_checkpoints SET {sets} WHERE id = ? AND version = ?",
            tuple(row[c] for c in cols) + (existing.id, expected_version),
        )
        self._j_commit()
        return getattr(cur, "rowcount", 0) > 0

    # -- stream leases (one worker per connector+stream, fenced) ------------
    #
    # The lease version doubles as a monotonic FENCING TOKEN: it increments
    # every time ownership is granted (fresh acquire or takeover) and stays
    # constant across renewals by the same owner. A worker that lost its
    # lease holds a stale token and can no longer renew — and therefore can
    # no longer publish results, even if it is still running.

    def _lease_expiry(self, ttl_seconds: int) -> str:
        # same timespec as now_iso() so lexicographic comparison is sound
        return (datetime.now(timezone.utc)
                + timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds")

    def acquire_stream_lease(
        self, connector_id: str, stream: str, owner: str, *,
        ttl_seconds: int = 600,
    ) -> Optional[int]:
        """Acquire (or re-enter) the lease. Returns the fencing token, or
        None when another worker actively holds the stream.

        An EXPIRED lease is always a new grant — the token bumps even when
        the owner string repeats (e.g. a fixed scheduler name), so a late
        holder of the previous incarnation is fenced out of every lease
        mutation, release included."""
        now = now_iso()
        expires = self._lease_expiry(ttl_seconds)
        # 1. takeover of an expired lease — ownership change → token bumps,
        # regardless of whether the owner string happens to match
        cur = self._j_exec(
            "UPDATE connector_stream_leases SET lease_owner = ?,"
            " lease_expires_at = ?, version = version + 1"
            " WHERE connector_id = ? AND stream = ?"
            " AND lease_expires_at <= ?",
            (owner, expires, connector_id, stream, now),
        )
        if getattr(cur, "rowcount", 0) == 0:
            # 2. re-entrant acquire by the current, still-valid owner
            # (token unchanged)
            cur = self._j_exec(
                "UPDATE connector_stream_leases SET lease_expires_at = ?"
                " WHERE connector_id = ? AND stream = ? AND lease_owner = ?"
                " AND lease_expires_at > ?",
                (expires, connector_id, stream, owner, now),
            )
        if getattr(cur, "rowcount", 0) > 0:
            self._j_commit()
            row = self._j_fetchone(
                "SELECT version FROM connector_stream_leases"
                " WHERE connector_id = ? AND stream = ? AND lease_owner = ?",
                (connector_id, stream, owner),
            )
            return int(row["version"]) if row else None
        row = self._j_fetchone(
            "SELECT lease_owner FROM connector_stream_leases"
            " WHERE connector_id = ? AND stream = ?",
            (connector_id, stream),
        )
        if row is not None:
            return None  # actively held by another worker
        try:
            self._j_exec(
                "INSERT INTO connector_stream_leases"
                " (connector_id, stream, lease_owner, lease_expires_at, version)"
                " VALUES (?,?,?,?,1)",
                (connector_id, stream, owner, expires),
            )
            self._j_commit()
            return 1
        except Exception:  # insert race — the other worker holds it
            return None

    def renew_stream_lease(
        self, connector_id: str, stream: str, owner: str, fencing_token: int, *,
        ttl_seconds: int = 600,
    ) -> bool:
        """Extend the lease IF this worker still owns it under the same
        fencing token. False means authority was lost — the caller must stop
        publishing results for this stream."""
        cur = self._j_exec(
            "UPDATE connector_stream_leases SET lease_expires_at = ?"
            " WHERE connector_id = ? AND stream = ?"
            " AND lease_owner = ? AND version = ?",
            (self._lease_expiry(ttl_seconds), connector_id, stream,
             owner, fencing_token),
        )
        self._j_commit()
        return getattr(cur, "rowcount", 0) > 0

    def release_stream_lease(self, connector_id: str, stream: str, owner: str,
                             fencing_token: int) -> None:
        """EVERY lease mutation is fenced — release included. A late worker
        holding a stale token (same owner string, previous incarnation)
        cannot expire the lease a successor legitimately holds."""
        self._j_exec(
            "UPDATE connector_stream_leases SET lease_expires_at = ?"
            " WHERE connector_id = ? AND stream = ?"
            " AND lease_owner = ? AND version = ?",
            ("1970-01-01T00:00:00+00:00", connector_id, stream,
             owner, fencing_token),
        )
        self._j_commit()

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
        record = ConnectorRecord.model_validate(
            json.loads(self.codec.decrypt(row["payload"]))
        )
        # processing state lives in columns, never in the immutable payload
        record.percept_id = row["percept_id"]
        record.quarantined = bool(row["quarantined"])
        return record

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

    def list_connector_records_for_object(
        self, connector_id: str, external_type: str, external_id: str,
    ) -> list[ConnectorRecord]:
        """Every observed revision of one external object (lineage lookup)."""
        rows = self._j_fetchall(
            "SELECT * FROM connector_records WHERE connector_id = ?"
            " AND external_type = ? AND external_id = ? ORDER BY id",
            (connector_id, external_type, external_id),
        )
        return [self._decode_record(r) for r in rows]

    def set_connector_record_state(
        self, record_id: str, *, percept_id: Optional[str] = None,
        quarantined: Optional[bool] = None,
    ) -> None:
        """Processing state only. The canonical (encrypted) payload of a
        persisted record is immutable — there is deliberately no method that
        rewrites it."""
        sets, params = [], []
        if percept_id is not None:
            sets.append("percept_id = ?")
            params.append(percept_id)
        if quarantined is not None:
            sets.append("quarantined = ?")
            params.append(1 if quarantined else 0)
        if not sets:
            return
        self._j_exec(
            f"UPDATE connector_records SET {', '.join(sets)} WHERE id = ?",
            tuple(params) + (record_id,),
        )
        self._j_commit()

    # -- deletion events (tombstone → lineage impact) -----------------------

    def insert_connector_deletion_event(self, event: ConnectorDeletionEvent) -> str:
        self._c_insert("connector_deletion_events", deletion_event_to_row(event))
        return event.id

    def list_connector_deletion_events(
        self, connector_id: str, status: Optional[str] = None,
    ) -> list[ConnectorDeletionEvent]:
        if status:
            rows = self._j_fetchall(
                "SELECT * FROM connector_deletion_events WHERE connector_id = ?"
                " AND status = ? ORDER BY created_at DESC",
                (connector_id, status),
            )
        else:
            rows = self._j_fetchall(
                "SELECT * FROM connector_deletion_events WHERE connector_id = ?"
                " ORDER BY created_at DESC",
                (connector_id,),
            )
        return [row_to_deletion_event(r) for r in rows]

    # -- dead letters -----------------------------------------------------

    def insert_connector_dead_letter(self, dlq: ConnectorDeadLetter) -> str:
        self._c_insert("connector_dead_letters", dead_letter_to_row(dlq))
        return dlq.id

    def get_connector_dead_letter(self, dlq_id: str) -> Optional[ConnectorDeadLetter]:
        row = self._j_fetchone(
            "SELECT * FROM connector_dead_letters WHERE id = ?", (dlq_id,)
        )
        return row_to_dead_letter(row) if row else None

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

    def cas_connector_sync_state(
        self, state: ConnectorSyncState, expected_version: int,
    ) -> bool:
        """Compare-and-set on sync-state version. Used so webhook hints and
        scheduler consumption cannot silently clobber each other."""
        existing = self.get_connector_sync_state(state.id)
        if existing is None:
            if expected_version != 0:
                return False
            fresh = state.model_copy(update={"version": 1})
            try:
                self._c_insert("connector_sync_state", sync_state_to_row(fresh))
            except Exception:  # insert race — someone else created it
                return False
            return True
        if existing.version != expected_version:
            return False
        merged = state.model_copy(update={"version": expected_version + 1})
        row = sync_state_to_row(merged)
        cols = [c for c in row if c != "id"]
        sets = ", ".join(f"{c} = ?" for c in cols)
        cur = self._j_exec(
            f"UPDATE connector_sync_state SET {sets}"
            " WHERE id = ? AND version = ?",
            tuple(row[c] for c in cols) + (state.id, expected_version),
        )
        self._j_commit()
        return getattr(cur, "rowcount", 0) > 0

    def consume_connector_sync_hints_cas(
        self, connector_id: str, consumed_hints: list[dict[str, Any]],
    ) -> bool:
        """Remove specific hint generations inside an outer transaction.

        Does **not** call ``_j_commit`` — durability is owned by the caller's
        ``store.transaction()`` (connector finalize). Returns False when the
        sync-state version moved; the caller must abort the whole finalize
        so evidence/checkpoint/hints stay consistent.
        """
        if not consumed_hints:
            return True
        state = self.get_connector_sync_state(connector_id)
        if state is None:
            return True
        expected = state.version
        meta = dict(state.metadata or {})

        tomb_keys = {
            (h.get("channel"), str(h.get("ts") or "0"))
            for h in consumed_hints if h.get("kind") == "tombstone"
        }
        thread_ids = {
            h.get("id") for h in consumed_hints
            if h.get("kind") == "pending_thread" and h.get("id")
        }
        refresh_ids = {
            h.get("id") for h in consumed_hints
            if h.get("kind") == "pending_message_refresh" and h.get("id")
        }

        if tomb_keys:
            kept = [
                t for t in (meta.get("pending_tombstones") or [])
                if (t.get("channel"), str(t.get("ts") or "0")) not in tomb_keys
            ]
            if kept:
                meta["pending_tombstones"] = kept
            else:
                meta.pop("pending_tombstones", None)
        if thread_ids:
            kept = [
                t for t in (meta.get("pending_threads") or [])
                if t.get("id") not in thread_ids
            ]
            if kept:
                meta["pending_threads"] = kept
            else:
                meta.pop("pending_threads", None)
        if refresh_ids:
            kept = [
                t for t in (meta.get("pending_message_refreshes") or [])
                if t.get("id") not in refresh_ids
            ]
            if kept:
                meta["pending_message_refreshes"] = kept
            else:
                meta.pop("pending_message_refreshes", None)

        merged = state.model_copy(update={
            "version": expected + 1,
            "metadata": meta,
            "updated_at": now_iso(),
        })
        row = sync_state_to_row(merged)
        cols = [c for c in row if c != "id"]
        sets = ", ".join(f"{c} = ?" for c in cols)
        cur = self._j_exec(
            f"UPDATE connector_sync_state SET {sets}"
            " WHERE id = ? AND version = ?",
            tuple(row[c] for c in cols) + (connector_id, expected),
        )
        # No _j_commit here — finalize's transaction commits or rolls back.
        return getattr(cur, "rowcount", 0) > 0

    def apply_connector_sync_state(
        self, connector_id: str, apply_fn, *, retries: int = 10,
    ) -> ConnectorSyncState:
        """Load → mutate → CAS, retrying on concurrent writers."""
        last: Optional[ConnectorSyncState] = None
        for _ in range(retries):
            state = (self.get_connector_sync_state(connector_id)
                     or ConnectorSyncState(id=connector_id))
            expected = state.version
            apply_fn(state)
            if self.cas_connector_sync_state(state, expected_version=expected):
                return self.get_connector_sync_state(connector_id) or state
            last = state
        raise RuntimeError(
            f"CAS exhausted for connector_sync_state {connector_id}"
            + (f" (last version {last.version})" if last else "")
        )

    def upsert_connector_sync_state(
        self, state: ConnectorSyncState,
    ) -> ConnectorSyncState:
        """Compatibility wrapper: CAS-apply scalar fields only.

        ``metadata`` is intentionally left alone — concurrent webhook hints
        live there. Prefer ``apply_connector_sync_state`` / sync_state_cas
        helpers for metadata mutations."""
        snapshot = state.model_dump(mode="json")

        def _apply(current: ConnectorSyncState) -> None:
            for key, value in snapshot.items():
                if key in ("id", "version", "metadata"):
                    continue
                setattr(current, key, value)

        return self.apply_connector_sync_state(state.id, _apply)

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
