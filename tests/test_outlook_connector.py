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


def _mk(store, creds, *, folders=(FOLDER,), secret=TOKEN):
    acc = register_source_account(
        store, connector_type="outlook", source_owner="employer", org_key="acme",
        owner_principal_id="principal_test",
        external_account_id="edu@acme.com",
    )
    inst = add_connector_instance(
        store, creds, account_id=acc.id, secret=secret,
        configuration={"folders": list(folders)},
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
    assert store.get_connector_checkpoint(inst.id, f"folder:{FOLDER}")


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
    keys = {r.thread_key for r in store.list_connector_records(inst.id)}
    assert keys == {"mail:outlook:edu@acme.com:conv9"}
    assert any(r.external_type == "thread_message"
               for r in store.list_connector_records(inst.id))


def test_rate_limit_degrades(store, creds, outlook):
    outlook.add_message("om1", conversation_id="c1", subject="x", body="y")
    _acc, inst = _mk(store, creds)
    outlook.rate_limited = True
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "degraded"
