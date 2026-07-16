"""v0.6 Phase 3 — Slack connector against the offline API double."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx
import pytest

from twin.connectors import (
    add_connector_instance,
    build_credential_store,
    register_source_account,
    sync_connector,
)

from slack_mock import FakeSlackAPI

TOKEN = "xoxb-test-token"
CHANNEL = "C_ENG"


@pytest.fixture()
def creds(tmp_path):
    return build_credential_store(tmp_path / "creds-home")


@pytest.fixture()
def slack(monkeypatch):
    api = FakeSlackAPI()
    api.add_channel(CHANNEL, name="engineering-architecture")

    from twin.connectors.slack import client as slclient
    real_build = slclient._build_http

    def fake_build(base_url, token):
        original = real_build(base_url, token)
        headers = dict(original.headers)
        original.close()
        return httpx.Client(transport=api.transport(),
                            base_url="https://slack.com/api/", headers=headers)

    monkeypatch.setattr(slclient, "_build_http", fake_build)
    return api


def _mk(store, creds, *, channels=(CHANNEL,), secret=TOKEN, extra_config=None):
    acc = register_source_account(
        store, connector_type="slack", source_owner="employer", org_key="acme",
        owner_principal_id="principal_test",
    )
    inst = add_connector_instance(
        store, creds, account_id=acc.id, secret=secret,
        configuration={"channels": list(channels), **(extra_config or {})},
    )
    return acc, inst


def _records_by_type(store, connector_id):
    out: dict[str, list] = {}
    for rec in store.list_connector_records(connector_id):
        out.setdefault(rec.external_type, []).append(rec)
    return out


# -- streams, lineage, trust -------------------------------------------------------


def test_dynamic_streams_one_checkpoint_per_channel(store, creds, slack):
    slack.add_message(CHANNEL, "1700000001.000100", text="We decided to use PostgreSQL.")
    _acc, inst = _mk(store, creds)
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "healthy"
    assert {s.stream for s in result.streams} == {f"channel:{CHANNEL}"}
    ckpt = store.get_connector_checkpoint(inst.id, f"channel:{CHANNEL}")
    assert ckpt is not None
    assert ckpt.cursor["watermark"] == "1700000001.000100"


def test_thread_shares_lineage_and_bot_is_derived(store, creds, slack):
    slack.add_message(CHANNEL, "1700000001.000100",
                      text="Should we use Redis?", reply_count=0)
    slack.add_reply(CHANNEL, "1700000001.000100", "1700000001.000200",
                    text="No — prefer PostgreSQL advisory locks.")
    slack.add_message(CHANNEL, "1700000002.000100",
                      text="GitHub: PR #8 merged in acme/atlas",
                      user="U_BOT", bot_id="B_GITHUB",
                      subtype="bot_message")
    # fix reply_count on parent after add_reply
    for m in slack.messages[CHANNEL]:
        if m["ts"] == "1700000001.000100":
            m["reply_count"] = 1

    _acc, inst = _mk(store, creds)
    sync_connector(store, creds, inst.id)
    by_type = _records_by_type(store, inst.id)
    assert "message" in by_type and "thread_reply" in by_type
    root = next(r for r in by_type["message"]
                if "Should we use Redis" in r.content)
    reply = by_type["thread_reply"][0]
    assert root.thread_key == reply.thread_key == f"slack:{CHANNEL}:1700000001.000100"
    assert reply.source_metadata["lineage_root"] == root.thread_key
    assert root.actor_ids == ["slack:U_ALICE"]

    bot = next(r for r in by_type["message"] if "PR #8" in r.content)
    assert bot.confidentiality["source_trust"] == 0.45
    assert bot.source_metadata["derived"] == "likely_notification"
    assert bot.source_metadata.get("github_refs")


def test_edit_creates_new_revision(store, creds, slack):
    msg = slack.add_message(CHANNEL, "1700000001.000100", text="v1 decision")
    _acc, inst = _mk(store, creds)
    sync_connector(store, creds, inst.id)

    msg["text"] = "v2 — edited decision"
    msg["edited"] = {"ts": "1700000003.000000", "user": "U_ALICE"}
    sync_connector(store, creds, inst.id)
    messages = _records_by_type(store, inst.id)["message"]
    assert len(messages) == 2
    assert any("v1" in m.content for m in messages)
    assert any("v2" in m.content for m in messages)


def test_empty_channels_await_configuration(store, creds, slack):
    _acc, inst = _mk(store, creds, channels=())
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "awaiting_configuration"
    assert result.streams == []


def test_same_sync_twice_is_idempotent(store, creds, slack):
    slack.add_message(CHANNEL, "1700000001.000100", text="one")
    _acc, inst = _mk(store, creds)
    first = sync_connector(store, creds, inst.id)
    again = sync_connector(store, creds, inst.id)
    assert first.percepts == 1
    assert again.percepts == 0


def test_rate_limit_degrades(store, creds, slack):
    slack.add_message(CHANNEL, "1700000001.000100", text="one")
    _acc, inst = _mk(store, creds)
    slack.rate_limited = True
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "degraded"
    assert store.list_percepts() == []


def test_deletion_tombstone_from_webhook(store, creds, slack, tmp_path):
    from twin.connectors.scheduler import sync_due
    from twin.connectors.slack.webhook import (
        handle_slack_webhook,
        set_webhook_secret,
    )

    slack.add_message(CHANNEL, "1700000001.000100", text="ephemeral")
    _acc, inst = _mk(store, creds)
    sync_connector(store, creds, inst.id)
    assert len(store.list_connector_records(inst.id)) == 1

    set_webhook_secret(store, creds, inst.id, "slack-signing")
    # remove from mock so history won't re-fetch it; tombstone comes from hint
    slack.messages[CHANNEL] = []
    body = json.dumps({
        "type": "event_callback",
        "event": {
            "type": "message",
            "subtype": "message_deleted",
            "channel": CHANNEL,
            "deleted_ts": "1700000001.000100",
        },
    }).encode()
    ts = str(int(time.time()))
    sig = "v0=" + hmac.new(
        b"slack-signing", f"v0:{ts}:".encode() + body, hashlib.sha256,
    ).hexdigest()
    out = handle_slack_webhook(store, creds, inst.id, body=body,
                               timestamp=ts, signature=sig)
    assert out["scheduled"] == [f"channel:{CHANNEL}"]

    results = sync_due(store, creds, tmp_path)
    assert results
    deletions = store.list_connector_deletion_events(inst.id)
    assert deletions
    assert deletions[0].external_id == f"{CHANNEL}:1700000001.000100"


def test_webhook_cannot_widen_to_unconfigured_channel(store, creds, slack):
    from twin.connectors.slack.webhook import (
        handle_slack_webhook,
        set_webhook_secret,
    )

    _acc, inst = _mk(store, creds)
    set_webhook_secret(store, creds, inst.id, "slack-signing")
    body = json.dumps({
        "type": "event_callback",
        "event": {"type": "message", "channel": "C_EVIL", "ts": "1.0",
                  "text": "nope"},
    }).encode()
    ts = str(int(time.time()))
    sig = "v0=" + hmac.new(
        b"slack-signing", f"v0:{ts}:".encode() + body, hashlib.sha256,
    ).hexdigest()
    out = handle_slack_webhook(store, creds, inst.id, body=body,
                               timestamp=ts, signature=sig)
    assert out["scheduled"] == []


def test_webhook_url_verification(store, creds, slack):
    from twin.connectors.slack.webhook import (
        handle_slack_webhook,
        set_webhook_secret,
    )

    _acc, inst = _mk(store, creds)
    set_webhook_secret(store, creds, inst.id, "slack-signing")
    body = json.dumps({"type": "url_verification",
                       "challenge": "abc123"}).encode()
    ts = str(int(time.time()))
    sig = "v0=" + hmac.new(
        b"slack-signing", f"v0:{ts}:".encode() + body, hashlib.sha256,
    ).hexdigest()
    out = handle_slack_webhook(store, creds, inst.id, body=body,
                               timestamp=ts, signature=sig)
    assert out == {"challenge": "abc123"}


def test_page_budget_produces_multiple_batches(store, creds, slack):
    for i in range(1, 251):
        slack.add_message(CHANNEL, f"1700000{i:03d}.000100",
                          text=f"msg {i}")
    _acc, inst = _mk(store, creds, extra_config={
        "max_pages_per_stream": 1,
        "max_batches_per_stream": 1,
    })
    # FakeSlackAPI history pages by offset with limit=200 from client —
    # max_pages=1 means one conversations.history call per batch.
    first = sync_connector(store, creds, inst.id,
                           streams=[f"channel:{CHANNEL}"])
    assert first.streams[0].committed
    assert first.streams[0].done is False
    assert first.streams[0].raw <= 200
    ckpt = store.get_connector_checkpoint(inst.id, f"channel:{CHANNEL}")
    assert "progress" in ckpt.cursor
    assert ckpt.cursor.get("watermark") is None

    # finish
    for _ in range(20):
        ckpt = store.get_connector_checkpoint(inst.id, f"channel:{CHANNEL}")
        if ckpt and "progress" not in (ckpt.cursor or {}):
            break
        sync_connector(store, creds, inst.id, streams=[f"channel:{CHANNEL}"])
    assert len(_records_by_type(store, inst.id)["message"]) == 250


def test_slack_source_policy_requires_review(store, cfg, embedder):
    from twin.cognition.pipeline import extract_percept
    from twin.sensory.percept import Percept

    percept = Percept(
        percept_type="connector_message", source_sensor="slack",
        content="We decided to postpone the Friday release.",
        source_trust=0.7,
        metadata={"connector_type": "slack"},
    ).seal()
    store.insert_percept(percept)
    report = extract_percept(store, cfg, embedder, percept)
    assert report.inserted
    mem = store.get_memory(report.inserted[0])
    assert mem.needs_review
    assert mem.type.value == "decision"


def test_list_channels_setup_helper(store, creds, slack):
    from twin.connectors.registry import build_adapter

    _acc, inst = _mk(store, creds)
    account = store.get_source_account(inst.account_id)
    adapter = build_adapter(inst, account, TOKEN)
    channels = adapter.list_channels()
    assert channels[0]["id"] == CHANNEL
    assert channels[0]["name"] == "engineering-architecture"


def test_backfill_preview_never_ingests(store, creds, slack):
    from twin.connectors import backfill_preview

    slack.add_message(CHANNEL, "1700000001.000100", text="one")
    _acc, inst = _mk(store, creds)
    preview = backfill_preview(store, creds, inst.id,
                               principal_id="principal_test")
    assert preview["started"] is False
    assert {s["stream"] for s in preview["streams"]} == {f"channel:{CHANNEL}"}
    assert store.list_connector_records(inst.id) == []
