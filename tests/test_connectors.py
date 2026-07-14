"""v0.6 Phase 1 — connector framework contract suite (on FakeConnector).

Proves the framework invariants without any real provider:
- idempotency, checkpoint-only-on-commit, never-gap-advance
- edits, deletions (tombstone), auth-expiry, rate-limit
- prompt-injection quarantine never reaching extraction
- ownership/vault lineage sealed into every Percept
- credentials never leak into store payloads or explain dumps
- no connector path writes confirmed Memory or Judgment
"""

from __future__ import annotations

import json

import pytest

from twin.connectors import (
    add_connector_instance,
    build_credential_store,
    connector_health,
    register_source_account,
    revoke_connector,
    sync_connector,
    validate_account_vault,
)
from twin.connectors.fake import _MALICIOUS


@pytest.fixture()
def creds(tmp_path):
    return build_credential_store(tmp_path / "creds-home")


def _make(store, creds, *, source_owner="personal", org_key=None, vault_id=None,
          secret="tok-secret-value", configuration=None):
    acc = register_source_account(
        store, connector_type="fake", source_owner=source_owner,
        org_key=org_key, vault_id=vault_id,
    )
    inst = add_connector_instance(
        store, creds, account_id=acc.id, secret=secret, configuration=configuration,
    )
    return acc, inst


def test_sync_produces_raw_record_and_percept_with_lineage(store, creds):
    acc, inst = _make(store, creds, source_owner="employer", org_key="acme")
    result = sync_connector(store, creds, inst.id)

    assert result.health.value == "healthy"
    assert len(store.list_connector_raw_items(inst.id)) == 3
    assert len(store.list_connector_records(inst.id)) == 3
    percepts = store.list_percepts()
    assert len(percepts) == 3
    for p in percepts:
        assert p.metadata["source_account_id"] == acc.id
        assert p.metadata["source_owner"] == "employer"
        assert p.metadata["vault_id"] == "vault_work_acme"
        assert p.metadata["connector_id"] == inst.id


def test_second_sync_is_idempotent(store, creds):
    _acc, inst = _make(store, creds)
    sync_connector(store, creds, inst.id)
    second = sync_connector(store, creds, inst.id)
    assert second.percepts == 0
    assert len(store.list_connector_records(inst.id)) == 3
    assert len(store.list_percepts()) == 3


def test_checkpoint_advances_only_after_commit(store, creds):
    _acc, inst = _make(store, creds)
    assert store.get_connector_checkpoint(inst.id, "issues") is None
    sync_connector(store, creds, inst.id)
    ckpt = store.get_connector_checkpoint(inst.id, "issues")
    assert ckpt is not None
    assert ckpt.cursor.get("seq") == 2
    assert ckpt.committed_batch_id is not None


def test_partial_failure_leaves_checkpoint_unchanged(store, creds):
    _acc, inst = _make(store, creds, configuration={"normalize_fail_ids": ["1"]})
    result = sync_connector(store, creds, inst.id)
    issues = next(s for s in result.streams if s.stream == "issues")
    assert issues.committed is False
    assert issues.failed == 1
    # never gap-advance: watermark stays put after a partial failure
    assert store.get_connector_checkpoint(inst.id, "issues") is None
    assert len(store.list_connector_dead_letters(inst.id)) == 1


def test_edit_creates_new_revision_old_retained(store, creds):
    fx = {"issues": [{"external_id": "1", "external_revision": "1", "seq": 1,
                      "content": "v1 original"}], "pull_requests": []}
    _acc, inst = _make(store, creds, configuration={"fixtures": fx})
    sync_connector(store, creds, inst.id)

    fx2 = {"issues": [{"external_id": "1", "external_revision": "2", "seq": 2,
                       "content": "v2 edited"}], "pull_requests": []}
    store.update_connector_instance(inst.id, configuration={"fixtures": fx2})
    sync_connector(store, creds, inst.id)

    records = store.list_connector_records(inst.id)
    revisions = sorted(r.external_revision for r in records)
    assert revisions == ["1", "2"]  # old revision retained alongside the edit


def test_delete_creates_tombstone_and_no_percept(store, creds):
    fx = {"issues": [{"external_id": "1", "external_revision": "9", "seq": 9,
                      "content": "removed upstream", "deleted": True}],
          "pull_requests": []}
    _acc, inst = _make(store, creds, configuration={"fixtures": fx})
    result = sync_connector(store, creds, inst.id)
    assert result.percepts == 0
    records = store.list_connector_records(inst.id)
    assert records and all(r.deleted for r in records)
    assert store.list_percepts() == []


def test_auth_expiry_reports_unauthorized_and_no_checkpoint(store, creds):
    _acc, inst = _make(store, creds, configuration={"fail_mode": "auth_expired"})
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "unauthorized"
    assert store.get_connector_checkpoint(inst.id, "issues") is None
    assert connector_health(store, inst.id)["health"] == "unauthorized"


def test_rate_limit_degrades_and_keeps_checkpoint(store, creds):
    _acc, inst = _make(store, creds, configuration={"fail_mode": "rate_limit"})
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "degraded"
    assert store.get_connector_checkpoint(inst.id, "issues") is None
    assert store.list_percepts() == []


def test_malicious_content_quarantined_never_extracted(store, creds, cfg, embedder):
    fx = {"issues": [{"external_id": "1", "external_revision": "1", "seq": 1,
                      "content": _MALICIOUS}], "pull_requests": []}
    _acc, inst = _make(store, creds, configuration={"fixtures": fx})
    result = sync_connector(store, creds, inst.id)

    assert result.percepts == 0
    records = store.list_connector_records(inst.id)
    assert records and records[0].quarantined is True
    assert store.list_percepts() == []
    assert store.list_quarantine(status="quarantined")

    # extraction has nothing to chew on → no memories
    from twin.cognition import extract_pending
    extract_pending(store, cfg, embedder)
    assert store.list_memories() == []


def test_employer_account_rejected_for_personal_vault(store, creds):
    with pytest.raises(ValueError):
        validate_account_vault("employer", "vault_personal")
    with pytest.raises(ValueError):
        register_source_account(
            store, connector_type="fake", source_owner="employer",
            vault_id="vault_personal",
        )


def test_credentials_absent_from_store_payloads(store, creds):
    secret = "super-secret-token-42"
    _acc, inst = _make(store, creds, secret=secret)
    sync_connector(store, creds, inst.id)

    # the secret must live only in the CredentialStore, never in the DB
    inst_row = store._j_fetchone(
        "SELECT payload FROM connector_instances WHERE id = ?", (inst.id,)
    )
    assert secret not in inst_row["payload"]
    cred_rows = store._j_fetchall("SELECT payload FROM connector_credential_refs", ())
    for r in cred_rows:
        assert secret not in r["payload"]
    # but it is retrievable via the credential store by ref
    assert creds.get(inst.credential_ref) == secret


def test_revoke_removes_secret_and_stops_sync(store, creds):
    _acc, inst = _make(store, creds, secret="tok-to-destroy")
    ref = inst.credential_ref
    assert creds.get(ref) == "tok-to-destroy"

    revoke_connector(store, creds, inst.id)
    assert creds.get(ref) is None
    reloaded = store.get_connector_instance(inst.id)
    assert reloaded.status == "revoked"
    assert reloaded.credential_ref is None

    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "revoked"
    assert store.list_percepts() == []


def test_no_confirmed_memory_or_judgment_written(store, creds):
    _acc, inst = _make(store, creds, source_owner="employer", org_key="acme")
    sync_connector(store, creds, inst.id)
    # framework produces percepts only; cognition remains untouched
    assert store.list_memories(status="confirmed") == []
    assert store.list_memories() == []
    if hasattr(store, "list_judgment_items"):
        assert store.list_judgment_items() == []


def test_org_vault_isolated_and_declared(store, creds):
    _acc, inst = _make(store, creds, source_owner="employer", org_key="Globex Inc")
    vault = store.get_vault("vault_work_globex_inc")
    assert vault is not None
    assert vault.source_owner == "employer"
    assert vault.storage_backend == "shared_db"
    assert vault.backup_class == "employer"


def test_manifest_and_adapter_registration():
    from twin.connectors import get_manifest, list_adapters
    assert "fake" in list_adapters()
    manifest = get_manifest("fake")
    assert manifest.connector_type == "fake"
    assert "issues" in manifest.streams
    assert manifest.affordances["deletions"] is True
