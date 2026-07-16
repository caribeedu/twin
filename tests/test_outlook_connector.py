"""v0.6 Phase 4 — Outlook connector against the offline Graph double."""

from __future__ import annotations

import httpx
import pytest

from twin.connectors import (
    add_connector_instance,
    build_credential_store,
    register_source_account,
    sync_connector,
)
from twin.connectors.protocol import ConnectorError

from outlook_mock import FakeOutlookAPI

TOKEN = "ewog.test-token"
FOLDER = "Inbox"


@pytest.fixture()
def creds(tmp_path):
    return build_credential_store(tmp_path / "creds-home")


@pytest.fixture()
def outlook(monkeypatch):
    api = FakeOutlookAPI()
    from twin.connectors.outlook import client as oclient
    real_build = oclient._build_http

    def fake_build(base_url, token):
        original = real_build(base_url, token)
        headers = dict(original.headers)
        original.close()
        return httpx.Client(transport=api.transport(),
                            base_url="https://graph.microsoft.com/v1.0/",
                            headers=headers)

    monkeypatch.setattr(oclient, "_build_http", fake_build)
    return api


def _mk(store, creds, *, folders=(FOLDER,), secret=TOKEN, extra=None):
    acc = register_source_account(
        store, connector_type="outlook", source_owner="employer", org_key="acme",
        owner_principal_id="principal_test",
        external_account_id="edu@acme.com",
    )
    inst = add_connector_instance(
        store, creds, account_id=acc.id, secret=secret,
        configuration={"folders": list(folders), **(extra or {})},
    )
    return acc, inst


def test_empty_folders_await_configuration(store, creds, outlook):
    _acc, inst = _mk(store, creds, folders=())
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "awaiting_configuration"


def test_sync_ingests_message_with_thread(store, creds, outlook):
    outlook.add_message(
        "om1", conversation_id="conv1",
        subject="Prefer Postgres locks",
        body="Use advisory locks instead of Redis.",
        from_addr="alice@acme.com",
    )
    _acc, inst = _mk(store, creds)
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "healthy"
    assert result.percepts == 1
    rec = store.list_connector_records(inst.id)[0]
    assert rec.thread_key == "mail:outlook:edu@acme.com:conv1"
    assert rec.source_metadata["classification"] == "human_authored"
    assert rec.actor_ids == ["mail:alice@acme.com"]
    ckpt = store.get_connector_checkpoint(inst.id, f"folder:{FOLDER}")
    assert ckpt.cursor.get("delta_link")


def test_reply_shares_conversation_thread(store, creds, outlook):
    outlook.add_message(
        "om_root", conversation_id="conv9", subject="Architecture",
        body="Should we use Redis?", received="2023-11-14T22:13:21Z",
    )
    outlook.add_message(
        "om_reply", conversation_id="conv9", subject="Re: Architecture",
        body="No — prefer Postgres.", from_addr="edu@acme.com",
        received="2023-11-14T22:14:00Z", quoted=True,
    )
    _acc, inst = _mk(store, creds)
    sync_connector(store, creds, inst.id)
    recs = store.list_connector_records(inst.id)
    keys = {r.thread_key for r in recs}
    assert keys == {"mail:outlook:edu@acme.com:conv9"}
    assert any(r.source_metadata.get("is_reply") for r in recs)


def test_attachment_discovery_lists_real_metadata(store, creds, outlook):
    outlook.add_message(
        "om_att", conversation_id="c_att", subject="spec",
        body="see attached",
        attachment={
            "id": "att1",
            "name": "spec.pdf",
            "contentType": "application/pdf",
            "size": 1234,
            "isInline": False,
            "contentId": None,
            "@odata.type": "#microsoft.graph.fileAttachment",
        },
    )
    _acc, inst = _mk(store, creds)
    sync_connector(store, creds, inst.id)
    rec = store.list_connector_records(inst.id)[0]
    atts = [a for a in rec.artifact_refs if a.get("kind") == "email_attachment"]
    assert atts
    assert atts[0]["filename"] == "spec.pdf"
    assert atts[0]["external_id"] == "att1"
    assert atts[0]["download_status"] == "metadata_only"
    assert rec.source_metadata.get("attachment_mode") == "metadata_only"


def test_delta_removed_emits_deletion(store, creds, outlook):
    outlook.add_message(
        "om1", conversation_id="c1", subject="temp", body="temp",
    )
    _acc, inst = _mk(store, creds)
    sync_connector(store, creds, inst.id)
    outlook.remove_message("om1")
    result = sync_connector(store, creds, inst.id)
    assert result.streams[0].deletion_events >= 1
    assert store.list_connector_deletion_events(inst.id)


def test_delta_bootstrap_persists_enumeration_values(store, creds, outlook):
    outlook.add_message(
        "om_boot", conversation_id="c_b", subject="in delta enum",
        body="must be kept",
    )
    _acc, inst = _mk(store, creds)
    sync_connector(store, creds, inst.id)
    ids = {r.external_id for r in store.list_connector_records(inst.id)}
    assert "om_boot" in ids
    ckpt = store.get_connector_checkpoint(inst.id, f"folder:{FOLDER}")
    assert ckpt.cursor.get("delta_link")


def test_move_between_allowlisted_folders_is_not_global_delete(store, creds, outlook):
    outlook.add_message(
        "om_move", conversation_id="c_m", subject="moving", body="x",
        folder_id="Inbox",
    )
    _acc, inst = _mk(store, creds, folders=["Inbox", "Folder_Work"])
    sync_connector(store, creds, inst.id)
    before = len(store.list_connector_deletion_events(inst.id))
    outlook.move_message("om_move", "Folder_Work")
    sync_connector(store, creds, inst.id)
    assert len(store.list_connector_deletion_events(inst.id)) == before
    live = [r for r in store.list_connector_records(inst.id)
            if r.external_id == "om_move" and not r.deleted]
    assert live
    assert any(
        "folder:Folder_Work" in (r.source_metadata.get("source_memberships") or [])
        for r in live
    )


def test_move_outside_allowlist_tombs(store, creds, outlook):
    outlook.folders["Archive"] = {
        "id": "Archive", "displayName": "Archive", "totalItemCount": 0,
    }
    outlook.add_message(
        "om_out", conversation_id="c_o", subject="leaving", body="x",
        folder_id="Inbox",
    )
    _acc, inst = _mk(store, creds, folders=["Inbox"])
    sync_connector(store, creds, inst.id)
    outlook.move_message("om_out", "Archive")
    sync_connector(store, creds, inst.id)
    assert store.list_connector_deletion_events(inst.id)


def test_nextlink_rate_limit_raises(store, creds, outlook):
    from twin.connectors.outlook.client import OutlookClient
    client = OutlookClient(TOKEN)
    # Patch http to mock transport
    client._http = httpx.Client(
        transport=outlook.transport(),
        base_url="https://graph.microsoft.com/v1.0/",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    outlook.next_link_rate_limited = True
    with pytest.raises(ConnectorError) as ei:
        client.call_url(
            "https://graph.microsoft.com/v1.0/delta-next/page2")
    assert ei.value.failure_class.value == "rate_limit"
    client.close()


def test_rate_limit_degrades(store, creds, outlook):
    outlook.add_message("om1", conversation_id="c1", subject="x", body="y")
    _acc, inst = _mk(store, creds)
    outlook.rate_limited = True
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "degraded"
