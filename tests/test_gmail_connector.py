"""v0.6 Phase 4 — Gmail connector against the offline API double."""

from __future__ import annotations

import httpx
import pytest

from twin.connectors import (
    add_connector_instance,
    backfill_preview,
    build_credential_store,
    create_backfill_job,
    register_source_account,
    run_backfill_partition,
    sync_connector,
)

from gmail_mock import FakeGmailAPI

TOKEN = "ya29.test-token"
LABEL = "INBOX"


@pytest.fixture()
def creds(tmp_path):
    return build_credential_store(tmp_path / "creds-home")


@pytest.fixture()
def gmail(monkeypatch):
    api = FakeGmailAPI()
    from twin.connectors.gmail import client as gclient
    real_build = gclient._build_http

    def fake_build(base_url, token):
        original = real_build(base_url, token)
        headers = dict(original.headers)
        original.close()
        return httpx.Client(transport=api.transport(),
                            base_url="https://gmail.googleapis.com/gmail/v1/",
                            headers=headers)

    monkeypatch.setattr(gclient, "_build_http", fake_build)
    return api


def _mk(store, creds, *, labels=(LABEL,), secret=TOKEN, extra=None):
    acc = register_source_account(
        store, connector_type="gmail", source_owner="employer", org_key="acme",
        owner_principal_id="principal_test",
        external_account_id="edu@acme.com",
    )
    inst = add_connector_instance(
        store, creds, account_id=acc.id, secret=secret,
        configuration={"labels": list(labels), **(extra or {})},
    )
    return acc, inst


def test_empty_labels_await_configuration(store, creds, gmail):
    _acc, inst = _mk(store, creds, labels=())
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "awaiting_configuration"


def test_sync_ingests_message_with_thread_and_classification(store, creds, gmail):
    gmail.add_message(
        "m1", thread_id="t1", subject="We decided on PostgreSQL",
        body="Use Postgres advisory locks instead of Redis.",
        from_addr="alice@acme.com",
    )
    _acc, inst = _mk(store, creds)
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "healthy"
    assert result.percepts == 1
    recs = store.list_connector_records(inst.id)
    assert len(recs) == 1
    rec = recs[0]
    assert rec.thread_key.startswith("mail:gmail:")
    assert rec.source_metadata["classification"] == "human_authored"
    assert rec.actor_ids[0] == "mail:alice@acme.com"
    assert "mail:edu@acme.com" in rec.actor_ids
    assert store.get_connector_checkpoint(inst.id, f"label:{LABEL}") is not None


def test_github_notification_is_derived(store, creds, gmail):
    gmail.add_message(
        "m2", thread_id="t2", subject="[GitHub] PR #8 merged",
        body="caribeedu merged pull request #8",
        from_addr="notifications@github.com",
    )
    _acc, inst = _mk(store, creds)
    sync_connector(store, creds, inst.id)
    rec = store.list_connector_records(inst.id)[0]
    assert rec.source_metadata["derived"] == "likely_notification"
    assert rec.confidentiality["source_trust"] == 0.40


def test_reply_shares_thread_key(store, creds, gmail):
    gmail.add_message(
        "m_root", thread_id="t99", subject="Architecture",
        body="Should we use Redis?", from_addr="alice@acme.com",
        internal_date_ms=1700000001000,
    )
    gmail.add_message(
        "m_reply", thread_id="t99", subject="Re: Architecture",
        body="No — prefer Postgres.", from_addr="edu@acme.com",
        internal_date_ms=1700000002000,
        in_reply_to="<m_root@mail.acme.com>",
    )
    _acc, inst = _mk(store, creds)
    sync_connector(store, creds, inst.id)
    recs = store.list_connector_records(inst.id)
    keys = {r.thread_key for r in recs}
    assert len(keys) == 1
    assert any(r.external_type == "thread_message" for r in recs)


def test_idempotent_resync(store, creds, gmail):
    gmail.add_message("m1", thread_id="t1", subject="one", body="one")
    _acc, inst = _mk(store, creds)
    assert sync_connector(store, creds, inst.id).percepts == 1
    assert sync_connector(store, creds, inst.id).percepts == 0


def test_rate_limit_degrades(store, creds, gmail):
    gmail.add_message("m1", thread_id="t1", subject="one", body="one")
    _acc, inst = _mk(store, creds)
    gmail.rate_limited = True
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "degraded"
    assert store.list_percepts() == []


def test_backfill_preview_lists_partitions(store, creds, gmail):
    gmail.add_message("m1", thread_id="t1", subject="one", body="one")
    _acc, inst = _mk(store, creds, extra={
        "backfill_since": "2026-01-01",
        "backfill_until": "2026-03-15",
    })
    preview = backfill_preview(store, creds, inst.id,
                               principal_id="principal_test")
    assert preview["started"] is False
    assert preview["partition_strategy"] == "year_month"
    keys = [p["partition_key"] for p in preview["partitions"]]
    assert keys == ["2026-01", "2026-02", "2026-03"]
    assert store.list_connector_records(inst.id) == []


def test_backfill_job_partition_advances(store, creds, gmail):
    gmail.add_message(
        "m1", thread_id="t1", subject="jan mail", body="hello",
        internal_date_ms=1736200000000,  # 2025-01-07-ish
    )
    _acc, inst = _mk(store, creds, extra={
        "backfill_since": "2025-01-01",
        "backfill_until": "2025-01-31",
    })
    job = create_backfill_job(store, creds, inst.id)
    assert job.progress["total_partitions"] == 1
    out = run_backfill_partition(store, creds, job.id)
    assert out["partition_status"] == "completed"
    assert out["done"] is True
    job2 = store.get_backfill_job(job.id)
    assert job2.status.value == "completed"
    assert store.list_connector_records(inst.id)


def test_gmail_source_policy_requires_review(store, cfg, embedder):
    from twin.cognition.pipeline import extract_percept
    from twin.sensory.percept import Percept

    percept = Percept(
        percept_type="connector_message", source_sensor="gmail",
        content="We decided to postpone the Friday release.",
        source_trust=0.65,
        metadata={"connector_type": "gmail"},
    ).seal()
    store.insert_percept(percept)
    report = extract_percept(store, cfg, embedder, percept)
    assert report.inserted
    mem = store.get_memory(report.inserted[0])
    assert mem.needs_review
    assert mem.type.value == "decision"


def test_list_labels_helper(store, creds, gmail):
    from twin.connectors.registry import build_adapter
    _acc, inst = _mk(store, creds)
    account = store.get_source_account(inst.account_id)
    adapter = build_adapter(inst, account, TOKEN)
    labels = adapter.list_labels()
    assert any(l["id"] == "INBOX" for l in labels)
