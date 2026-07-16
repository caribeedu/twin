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
from twin.connectors.mail.streams import format_backfill_stream

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
    rec = store.list_connector_records(inst.id)[0]
    assert rec.thread_key.startswith("mail:gmail:")
    assert rec.source_metadata["classification"] == "human_authored"
    assert rec.actor_ids == ["mail:alice@acme.com"]
    assert "mail:edu@acme.com" in rec.participant_ids
    ckpt = store.get_connector_checkpoint(inst.id, f"label:{LABEL}")
    assert ckpt is not None
    assert ckpt.cursor.get("history_id")


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
    # second pass uses history feed — empty history → no new percepts
    assert sync_connector(store, creds, inst.id).percepts == 0


def test_rate_limit_degrades(store, creds, gmail):
    gmail.add_message("m1", thread_id="t1", subject="one", body="one")
    _acc, inst = _mk(store, creds)
    gmail.rate_limited = True
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "degraded"
    assert store.list_percepts() == []


def test_history_picks_up_old_message_label_add(store, creds, gmail):
    gmail.add_message(
        "old", thread_id="t_old", subject="old mail",
        body="from 2022", label_ids=["INBOX"],
        internal_date_ms=1640995200000,  # 2022-01-01
    )
    _acc, inst = _mk(store, creds, labels=["Label_Work"])
    # bootstrap empty work label
    sync_connector(store, creds, inst.id)
    ckpt = store.get_connector_checkpoint(inst.id, "label:Label_Work")
    assert ckpt.cursor.get("history_id")
    # later: old message receives Work label
    gmail.add_label("old", "Label_Work")
    sync_connector(store, creds, inst.id)
    ids = {r.external_id for r in store.list_connector_records(inst.id)}
    assert "old" in ids


def test_history_deletion_emits_event(store, creds, gmail):
    gmail.add_message("m1", thread_id="t1", subject="bye", body="bye")
    _acc, inst = _mk(store, creds)
    sync_connector(store, creds, inst.id)
    gmail.delete_message("m1")
    result = sync_connector(store, creds, inst.id)
    assert result.streams[0].deletion_events >= 1
    events = store.list_connector_deletion_events(inst.id)
    assert events
    assert events[0].external_id == "m1"


def test_backfill_does_not_regress_continuous_checkpoint(store, creds, gmail):
    # Continuous sync first — watermark in 2026
    gmail.add_message(
        "recent", thread_id="t_r", subject="recent", body="hi",
        internal_date_ms=1750000000000,  # ~2025-06
    )
    _acc, inst = _mk(store, creds, extra={
        "backfill_since": "2020-01-01",
        "backfill_until": "2020-01-31",
    })
    sync_connector(store, creds, inst.id)
    cont = store.get_connector_checkpoint(inst.id, f"label:{LABEL}")
    cont_wm = cont.cursor.get("watermark")
    cont_ver = cont.version
    assert cont_wm

    # Historical message in Jan 2020
    gmail.add_message(
        "old2020", thread_id="t_old", subject="jan 2020", body="archive",
        internal_date_ms=1577836801000,  # 2020-01-01 approx
        record_history=False,
    )
    cfg_before = dict(inst.configuration)
    job = create_backfill_job(store, creds, inst.id)
    out = run_backfill_partition(store, creds, job.id)
    assert out["partition_status"] in ("completed", "continuation_pending")

    # Continuous checkpoint untouched
    cont2 = store.get_connector_checkpoint(inst.id, f"label:{LABEL}")
    assert cont2.cursor.get("watermark") == cont_wm
    assert cont2.version == cont_ver

    # Backfill stream has its own checkpoint
    bf_stream = format_backfill_stream(
        job.id, "2020-01", f"label:{LABEL}")
    bf_ckpt = store.get_connector_checkpoint(inst.id, bf_stream)
    assert bf_ckpt is not None

    # Config not mutated
    inst2 = store.get_connector_instance(inst.id)
    assert inst2.configuration == cfg_before

    # Idempotent with continuous records
    ids = {r.external_id for r in store.list_connector_records(inst.id)}
    assert "old2020" in ids
    assert "recent" in ids


def test_backfill_continuation_not_marked_completed(store, creds, gmail):
    # Many messages in one month; page size 50; max_batches=1
    for i in range(120):
        gmail.add_message(
            f"m{i:03d}", thread_id="t_b", subject=f"msg {i}", body=f"b{i}",
            internal_date_ms=1577836801000 + i * 1000,
            record_history=False,
        )
    _acc, inst = _mk(store, creds, extra={
        "backfill_since": "2020-01-01",
        "backfill_until": "2020-01-31",
        "max_batches_per_stream": 1,
        "max_pages_per_stream": 1,
    })
    job = create_backfill_job(store, creds, inst.id)
    first = run_backfill_partition(store, creds, job.id)
    assert first["partition_status"] == "continuation_pending"
    assert first["continuation_pending"] is True
    job1 = store.get_backfill_job(job.id)
    part = job1.progress["partitions"][0]
    assert part["status"] == "continuation_pending"

    # Drive to completion
    for _ in range(20):
        out = run_backfill_partition(store, creds, job.id)
        if out.get("partition_status") == "completed" or out.get("done"):
            break
    job2 = store.get_backfill_job(job.id)
    assert job2.progress["partitions"][0]["status"] == "completed"
    assert len(store.list_connector_records(inst.id)) == 120


def test_backfill_claim_rejects_second_worker(store, creds, gmail):
    gmail.add_message(
        "m1", thread_id="t1", subject="x", body="y",
        internal_date_ms=1577836801000, record_history=False,
    )
    _acc, inst = _mk(store, creds, extra={
        "backfill_since": "2020-01-01",
        "backfill_until": "2020-01-31",
    })
    job = create_backfill_job(store, creds, inst.id)
    # Manually claim as worker A with fresh CAS
    from twin.connectors.mail.backfill import apply_partition_claim
    expected = job.version
    job.progress = apply_partition_claim(
        job.progress, "2020-01", worker_id="worker_a", claim_token=1,
    )
    job.status = job.status  # noqa — keep planned→running via claim helper path
    from twin.connectors.models import BackfillJobStatus
    job.status = BackfillJobStatus.running
    assert store.cas_backfill_job(job, expected)

    with pytest.raises(ValueError, match="already claimed"):
        run_backfill_partition(store, creds, job.id, worker_id="worker_b")


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
