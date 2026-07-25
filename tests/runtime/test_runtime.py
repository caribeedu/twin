"""Durable cognitive runtime — claim CAS, idempotency, lease recovery, DLQ."""

from datetime import datetime, timedelta, timezone

from twin.runtime.handlers import HandlerError, dispatch
from twin.runtime.models import ErrorClass, JobKind, JobStatus, RuntimeJob
from twin.runtime.queue import RuntimeQueue
from twin.runtime.scheduler import RuntimeScheduler
from twin.runtime.worker import RuntimeWorker


def test_enqueue_idempotent(store):
    q = RuntimeQueue(store)
    a = q.enqueue(
        JobKind.integrity_check,
        payload={"n": 1},
        idempotency_key="idem-1",
    )
    b = q.enqueue(
        JobKind.integrity_check,
        payload={"n": 2},
        idempotency_key="idem-1",
    )
    assert a.id == b.id
    assert store.runtime_queue_depth().get("pending") == 1


def test_claim_exclusive_between_workers(store):
    q = RuntimeQueue(store)
    q.enqueue(JobKind.integrity_check, idempotency_key="only-one")
    first = q.claim("w1", lease_seconds=30)
    second = q.claim("w2", lease_seconds=30)
    assert first is not None
    assert second is None
    assert first.worker_id == "w1"
    assert first.status == JobStatus.running
    assert first.attempts == 1


def test_expired_lease_reclaimed_by_other_worker(store):
    q = RuntimeQueue(store)
    job = q.enqueue(JobKind.integrity_check, idempotency_key="lease-rec")
    claimed = q.claim("dead-worker", lease_seconds=1)
    assert claimed is not None
    # Force lease expiry in the past
    past = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat(
        timespec="seconds",
    )
    claimed.lease_expires_at = past
    claimed.updated_at = past
    store.update_runtime_job(claimed)

    recovered = q.claim("alive-worker", lease_seconds=30)
    assert recovered is not None
    assert recovered.id == job.id
    assert recovered.worker_id == "alive-worker"
    assert recovered.attempts == 2


def test_complete_is_lease_gated(store):
    q = RuntimeQueue(store)
    q.enqueue(JobKind.integrity_check)
    job = q.claim("w1")
    assert job is not None
    # Wrong token cannot complete
    forged = job.model_copy(update={"lease_token": "nope"})
    assert q.complete(forged, {"ok": False}) is False
    assert q.complete(job, {"ok": True}) is True
    done = store.get_runtime_job(job.id)
    assert done.status == JobStatus.completed
    assert done.result["ok"] is True


def test_permanent_failure_goes_to_dlq(store):
    q = RuntimeQueue(store)
    q.enqueue(JobKind.integrity_check, max_attempts=3)
    job = q.claim("w1")
    assert job is not None
    ok = q.fail(
        job, "boom", stage="validate", error_class=ErrorClass.permanent,
    )
    assert ok is True
    dead = store.get_runtime_job(job.id)
    assert dead.status == JobStatus.dead_letter
    dlq = store.list_runtime_dead_letters()
    assert len(dlq) == 1
    assert dlq[0].job_id == job.id


def test_transient_failure_backoff_not_dlq(store):
    q = RuntimeQueue(store)
    q.enqueue(JobKind.integrity_check, max_attempts=5)
    job = q.claim("w1")
    q.fail(job, "flaky", stage="dispatch", error_class=ErrorClass.transient)
    failed = store.get_runtime_job(job.id)
    assert failed.status == JobStatus.failed
    assert failed.not_before != ""
    assert store.list_runtime_dead_letters() == []


def test_model_unavailable_never_dead_letters(store):
    q = RuntimeQueue(store)
    q.enqueue(
        JobKind.interpret_percept,
        payload={"percept_id": "missing"},
        max_attempts=2,
    )
    # Burn attempts past max — model outage still must not DLQ
    for i in range(3):
        job = q.claim(f"w{i}", lease_seconds=30)
        if job is None:
            # still in backoff — force runnable
            cur = store.get_runtime_job(
                store.list_runtime_jobs(kind="interpret_percept")[0].id,
            )
            cur.not_before = ""
            store.update_runtime_job(cur)
            job = q.claim(f"w{i}", lease_seconds=30)
        assert job is not None
        q.fail(
            job, "model down", stage="interpret",
            error_class=ErrorClass.model_unavailable,
        )
    final = store.list_runtime_jobs(kind="interpret_percept")[0]
    assert final.status == JobStatus.failed
    assert final.error_class == ErrorClass.model_unavailable.value
    assert store.list_runtime_dead_letters() == []


def test_vault_isolation_on_claim(store):
    q = RuntimeQueue(store)
    q.enqueue(JobKind.integrity_check, vault_id="vault_a", idempotency_key="a")
    q.enqueue(JobKind.integrity_check, vault_id="vault_b", idempotency_key="b")
    a = q.claim("w", vault_id="vault_a")
    assert a is not None
    assert a.vault_id == "vault_a"
    # Worker scoped to vault_a must not see vault_b
    none = q.claim("w", vault_id="vault_a")
    assert none is None
    b = q.claim("w", vault_id="vault_b")
    assert b is not None
    assert b.vault_id == "vault_b"


def test_worker_runs_integrity_check(store, cfg, embedder):
    q = RuntimeQueue(store)
    job = q.enqueue(JobKind.integrity_check, idempotency_key="run-once")
    events = []
    w = RuntimeWorker(
        store, cfg, embedder, worker_id="test-w",
        on_job_event=events.append,
    )
    assert w.current is None
    assert w.run_once() is True
    done = store.get_runtime_job(job.id)
    assert done.status == JobStatus.completed
    assert done.result.get("ok") is True
    assert w.jobs_completed == 1
    assert w.current is None
    assert [e["status"] for e in events] == ["started", "completed"]
    assert events[-1]["kind"] == "integrity_check"


def test_runtime_snapshot_tracks_inflight_and_recent(store, cfg, embedder):
    from twin.runtime.service import TwinRuntime

    rt = TwinRuntime(store, cfg, embedder, workers=1, schedule_interval=3600)
    q = RuntimeQueue(store)
    job = q.enqueue(JobKind.integrity_check, idempotency_key="snap-1")

    claimed = []

    class SlowWorker(RuntimeWorker):
        def run_once(self):
            j = self.queue.claim(self.worker_id, lease_seconds=30)
            if j is None:
                return False
            self.current = {
                "job_id": j.id,
                "kind": j.kind.value,
                "stage": "dispatch",
                "started_at": j.started_at or "2020-01-01T00:00:00+00:00",
                "label": f"{j.kind.value}",
            }
            claimed.append(j)
            return True

    w = SlowWorker(store, cfg, embedder, worker_id="snap-w")
    rt._pool = [w]
    assert w.run_once() is True
    snap = rt.snapshot()
    assert snap["workers"][0]["current"]["job_id"] == job.id
    assert snap["queue"].get("running", 0) >= 1 or snap["workers"][0]["current"]

    rt.note_job_event({
        "status": "completed", "kind": "integrity_check",
        "job_id": job.id, "worker_id": "snap-w", "label": "integrity_check",
    })
    snap2 = rt.snapshot()
    assert snap2["recent"][0]["job_id"] == job.id
    assert snap2["recent"][0]["status"] == "completed"

    from twin.interfaces.ux import format_runtime_dashboard_plain

    line = format_runtime_dashboard_plain(snap2)
    assert "integrity_check" in line
    assert "runtime" in line


def test_scheduler_idempotent_daily_keys(store):
    q = RuntimeQueue(store)
    sched = RuntimeScheduler(q, vault_id="vault_general")
    first = sched.tick()
    second = sched.tick()
    assert first == second
    # three kinds: daily, weekly, integrity
    assert len(set(first)) == 3
    assert store.runtime_queue_depth().get("pending") == 3


def test_cancel_pending(store):
    q = RuntimeQueue(store)
    job = q.enqueue(JobKind.integrity_check)
    assert q.cancel(job.id) is True
    assert store.get_runtime_job(job.id).status == JobStatus.cancelled
    assert q.cancel(job.id) is False


def test_retry_dead_letter(store):
    q = RuntimeQueue(store)
    q.enqueue(JobKind.integrity_check, max_attempts=1)
    job = q.claim("w")
    q.fail(job, "nope", stage="x", error_class=ErrorClass.permanent)
    retried = q.retry(job.id)
    assert retried.status == JobStatus.pending
    assert retried.error == ""


def test_dispatch_missing_handler_payload(store, cfg, embedder):
    job = RuntimeJob(kind=JobKind.workspace_tick, payload={})
    try:
        dispatch(store, cfg, embedder, job)
        assert False, "expected HandlerError"
    except HandlerError as exc:
        assert exc.error_class == ErrorClass.permanent


def test_session_complete_job_consolidates(store, cfg, embedder):
    from twin.cognition.sessions import observe_session, start_session
    from twin.memory.models import ConsolidationStatus

    ses = start_session(
        store, cfg, embedder, "task", domain="technical", client="cli",
    ).session
    observe_session(store, ses.id, {
        "kind": "user_message", "note": "i finished watching dexter",
    })
    q = RuntimeQueue(store)
    job = q.enqueue(
        JobKind.session_complete,
        payload={
            "session_id": ses.id,
            "summary": "",
            "abandoned": False,
            "summary_origin": "assistant",
        },
        idempotency_key=f"session_complete:{ses.id}",
    )
    claimed = q.claim("w-complete")
    assert claimed is not None and claimed.id == job.id
    result = dispatch(store, cfg, embedder, claimed)
    assert q.complete(claimed, result)
    done = store.get_session(ses.id)
    assert done.consolidation_status == ConsolidationStatus.completed
    assert done.summary_percept_id
    assert "dexter" in store.get_percept(done.summary_percept_id).content.lower()


def test_session_domain_resolve_job_freezes_from_dialogue(store, cfg, embedder, monkeypatch):
    from twin.cognition.host_session import bind_and_start
    from twin.cognition.observer import ObserverReading
    from twin.cognition.sessions import observe_session

    started = bind_and_start(
        store, cfg, embedder,
        host_type="claude-code",
        external_session_id="bg-domain-1",
        query="native host session",
    )
    binding = started.binding
    assert binding.domain == "unclassified"
    observe_session(store, binding.cognitive_session_id, {
        "kind": "user_message",
        "note": "get ready for the Atlas stakeholder sync tomorrow",
    })

    monkeypatch.setattr(
        "twin.cognition.observer.read_context",
        lambda *_a, **_k: ObserverReading(
            domain="work", task_profile="meeting_prep", mode="llm",
            confidences={"domain": 0.9, "task_profile": 0.8, "project": 0.0},
        ),
    )

    q = RuntimeQueue(store)
    job = q.enqueue(
        JobKind.session_domain_resolve,
        payload={"binding_id": binding.id, "session_id": binding.cognitive_session_id},
        idempotency_key=f"session_domain_resolve:{binding.id}",
    )
    claimed = q.claim("w-domain")
    assert claimed.id == job.id
    result = dispatch(store, cfg, embedder, claimed)
    assert result["ok"] is True
    assert result["domain"] == "work"
    assert q.complete(claimed, result)
    updated = store.get_host_session_binding(binding.id)
    assert updated.domain == "work"
    assert updated.metadata.get("domain_resolved_background") is True
