"""Runtime drains BackfillJob partitions via JobKind.backfill_partition."""
from __future__ import annotations

import httpx
import pytest

from twin.sense.connectors import (
    add_connector_instance,
    build_credential_store,
    create_backfill_job,
    register_source_account,
)
from twin.interfaces.runtime.backfill_sched import enqueue_backfill_partition_jobs
from twin.interfaces.runtime.models import JobKind, JobStatus
from twin.interfaces.runtime.queue import RuntimeQueue
from twin.interfaces.runtime.scheduler import RuntimeScheduler
from twin.interfaces.runtime.worker import RuntimeWorker

from tests.connectors.gmail.gmail_mock import FakeGmailAPI

TOKEN = "ya29.test-token"
LABEL = "INBOX"


@pytest.fixture()
def creds(tmp_path, monkeypatch):
    home = tmp_path / "creds-home"
    # Handlers build credentials from cfg.home — point Config there.
    return home, build_credential_store(home)


@pytest.fixture()
def gmail(monkeypatch):
    api = FakeGmailAPI()
    from twin.sense.connectors.gmail import client as gclient
    real_build = gclient._build_http

    def fake_build(base_url, token):
        original = real_build(base_url, token)
        headers = dict(original.headers)
        original.close()
        return httpx.Client(
            transport=api.transport(),
            base_url="https://gmail.googleapis.com/gmail/v1/",
            headers=headers,
        )

    monkeypatch.setattr(gclient, "_build_http", fake_build)
    return api


def _mk(store, creds_store, *, extra=None):
    acc = register_source_account(
        store, connector_type="gmail", source_owner="employer", org_key="acme",
        owner_principal_id="principal_test",
        external_account_id="edu@acme.com",
    )
    inst = add_connector_instance(
        store, creds_store, account_id=acc.id, secret=TOKEN,
        configuration={"labels": [LABEL], **(extra or {})},
    )
    return inst


def test_scheduler_enqueues_backfill_partition(store, creds, gmail, cfg, monkeypatch):
    home, creds_store = creds
    monkeypatch.setattr(cfg, "home", home)
    gmail.add_message(
        "m1", thread_id="t1", subject="old", body="body",
        internal_date_ms=1577836801000, record_history=False,
    )
    inst = _mk(store, creds_store, extra={
        "backfill_since": "2020-01-01",
        "backfill_until": "2020-01-31",
    })
    bf = create_backfill_job(store, creds_store, inst.id)
    q = RuntimeQueue(store)
    sched = RuntimeScheduler(q, vault_id="vault_work_acme", store=store)
    ids = sched.tick()
    kinds = {store.get_runtime_job(i).kind for i in ids}
    assert JobKind.backfill_partition in kinds
    pending = [
        j for j in store.list_runtime_jobs(kind=JobKind.backfill_partition.value)
        if j.status == JobStatus.pending
    ]
    assert len(pending) == 1
    assert pending[0].payload["backfill_job_id"] == bf.id

    # Idempotent for the same BackfillJob.version
    again = enqueue_backfill_partition_jobs(
        q, store, vault_id="vault_work_acme", backfill_job_id=bf.id,
    )
    assert again == [pending[0].id]


def test_worker_drains_backfill_job(store, creds, gmail, cfg, embedder, monkeypatch):
    home, creds_store = creds
    monkeypatch.setattr(cfg, "home", home)
    gmail.add_message(
        "m1", thread_id="t1", subject="old", body="body",
        internal_date_ms=1577836801000, record_history=False,
    )
    inst = _mk(store, creds_store, extra={
        "backfill_since": "2020-01-01",
        "backfill_until": "2020-01-31",
    })
    bf = create_backfill_job(store, creds_store, inst.id)
    q = RuntimeQueue(store)
    enqueue_backfill_partition_jobs(
        q, store, vault_id="vault_work_acme", backfill_job_id=bf.id,
    )
    w = RuntimeWorker(store, cfg, embedder, worker_id="bf-w")
    for _ in range(20):
        if not w.run_once():
            # Re-enqueue if handler couldn't (shouldn't), or wait for chain.
            enqueue_backfill_partition_jobs(
                q, store, vault_id="vault_work_acme", backfill_job_id=bf.id,
            )
            if not w.run_once():
                break
        job = store.get_backfill_job(bf.id)
        if job and job.status.value == "completed":
            break
    done = store.get_backfill_job(bf.id)
    assert done is not None
    assert done.status.value == "completed"
    assert done.progress.get("completed_partitions") == 1
    assert store.list_connector_records(inst.id)


def test_watch_backfill_already_terminal(store, creds, gmail, cfg, monkeypatch):
    from twin.sense.connectors.models import BackfillJobStatus
    from twin.interfaces import ux

    home, creds_store = creds
    monkeypatch.setattr(cfg, "home", home)
    inst = _mk(store, creds_store, extra={
        "backfill_since": "2020-01-01",
        "backfill_until": "2020-01-31",
    })
    bf = create_backfill_job(store, creds_store, inst.id)
    bf.status = BackfillJobStatus.completed
    bf.progress = {
        **(bf.progress or {}),
        "completed_partitions": 1,
    }
    store.update_backfill_job(bf)
    out = ux.watch_backfill_job(store, bf.id, stall_warn_seconds=0.1)
    assert out["done"] is True
    assert out["status"] == "completed"
