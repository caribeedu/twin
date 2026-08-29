"""PostgreSQL + pgvector backend, exercised against a real server.

Set TWIN_TEST_PG_URL to run (e.g. postgresql://twin:twin@localhost:5432/twin);
skipped otherwise. Each run uses a fresh schema.
"""

import os
from pathlib import Path

from tests.paths import EXAMPLES

import pytest

PG_URL = os.environ.get("TWIN_TEST_PG_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="TWIN_TEST_PG_URL not set")

@pytest.fixture()
def pg_store():
    import psycopg

    from twin.store.store.postgres import PostgresStore

    # isolated schema per test run
    admin = psycopg.connect(PG_URL, autocommit=True)
    admin.execute("DROP SCHEMA IF EXISTS twin_test CASCADE")
    admin.execute("CREATE SCHEMA twin_test")
    admin.close()
    # twin_test first (tables land there), public second (pgvector type lives there)
    url = PG_URL + ("&" if "?" in PG_URL else "?") + "options=-csearch_path%3Dtwin_test,public"
    store = PostgresStore(url)
    yield store
    store.close()


def test_pgvector_available(pg_store):
    assert pg_store.has_pgvector, "pgvector extension should be active in tests"


def test_percept_roundtrip_and_dedup(pg_store):
    from twin.sense.sensory import sense_paths

    percepts, _ = sense_paths([EXAMPLES / "docs"])
    percept = percepts[0]
    assert pg_store.insert_percept(percept) == percept.id
    loaded = pg_store.get_percept(percept.id)
    assert loaded.content == percept.content
    assert loaded.actors == ["Edu"]
    # dedup by content hash
    clone, _ = sense_paths([EXAMPLES / "docs"])
    assert pg_store.insert_percept(clone[0]) is None
    assert len(pg_store.unprocessed_percepts()) == 1


def test_full_pipeline_on_postgres(pg_store, cfg, embedder):
    from twin.cognize.services import extract_pending
    from twin.privacy.firewall import Firewall
    from twin.store.search import search
    from twin.sense.sensory import sense_paths

    percepts, _ = sense_paths([EXAMPLES])
    for p in percepts:
        pg_store.insert_percept(p)
    reports = extract_pending(pg_store, cfg, embedder)
    inserted = [mid for r in reports for mid in r.inserted]
    assert inserted

    # hybrid search: PG tsvector FTS + pgvector similarity
    fw = Firewall(cfg.policies_path, pg_store)
    result = search(pg_store, embedder, "FastAPI backend webhooks",
                    target_domain="technical", firewall=fw)
    assert result.hits
    assert "FastAPI" in " ".join(h.claim.summary for h in result.hits[:3])

    # review lifecycle
    from twin.store.models import ClaimStatus

    pg_store.set_status(inserted[0], ClaimStatus.confirmed)
    assert pg_store.get_claim(inserted[0]).status.value == "confirmed"

    # entities + graph — entity resolution is the cognitive interpreter's job;
    # the offline mock extracts none, so the graph is simply exercised as empty
    entities = pg_store.list_entities()
    assert isinstance(entities, list)
    if entities:
        assert isinstance(pg_store.claims_for_entity(entities[0].id), list)


def test_pgvector_server_side_similarity(pg_store, embedder):
    from twin import ids
    from twin.store.models import StoreClaim

    for i, text in enumerate(["FastAPI no backend", "jantar em família"]):
        mem = StoreClaim(id=ids.claim_id(), type="fact", title=text, summary=text)
        pg_store.insert_claim(mem)
        pg_store.store_embedding(mem.id, "claim", embedder.name, embedder.embed(text))

    query_vec = embedder.embed("backend FastAPI webhooks")
    scores = pg_store.similar(query_vec, "claim", embedder.name, min_sim=0.01)
    assert scores
    top = max(scores, key=scores.get)
    assert "FastAPI" in pg_store.get_claim(top).title


def test_projects_and_sessions_on_postgres(pg_store, cfg, embedder):
    from twin.cognize.services.sessions import (
        complete_session,
        ensure_project,
        observe_session,
        record_feedback,
        start_session,
    )

    project = ensure_project(pg_store, "Atlas", repos=["atlas-api"], aliases=["atlas"])
    assert pg_store.find_project("atlas-api").id == project.id
    assert pg_store.get_project(project.id).repos == ["atlas-api"]

    started = start_session(pg_store, cfg, embedder,
                            "implement the webhook retry code",
                            client="pg-test", cwd="/home/edu/atlas-api")
    session = started.session
    assert session.project_id == project.id

    # append-only artifacts: stale copies cannot lose each other's writes
    stale_a = pg_store.get_session(session.id)
    stale_b = pg_store.get_session(session.id)
    observe_session(pg_store, stale_a.id, {"kind": "commit", "ref": "abc"})
    observe_session(pg_store, stale_b.id, {"kind": "file", "ref": "api.py"})
    pg_store.update_session(stale_b)  # scalar update from stale copy
    assert {a["ref"] for a in pg_store.get_session(session.id).artifacts} == \
        {"abc", "api.py"}

    done = complete_session(
        pg_store, cfg, embedder, session.id,
        summary="We decided to use exponential backoff for retries.",
        summary_origin="user",
    )
    assert done.status.value == "completed"
    assert done.consolidation_status.value == "completed"
    assert done.summary_percept_id
    assert done.created_claim_ids
    assert pg_store.get_claim(done.created_claim_ids[0]).project_id == project.id
    # compare-and-set: a second complete is rejected
    with pytest.raises(ValueError, match="not completable"):
        complete_session(pg_store, cfg, embedder, session.id, summary="again")
    # observing a completed session is rejected atomically
    with pytest.raises(ValueError, match="not active"):
        observe_session(pg_store, session.id, {"kind": "file"})

    record_feedback(pg_store, session.id, "useful",
                    claim_id=done.created_claim_ids[0])
    loaded = pg_store.get_session(session.id)
    assert loaded.artifacts and loaded.feedback
    assert loaded.feedback[0]["scope"] == "claim"
    assert [s.id for s in pg_store.list_sessions(status="completed")] == [session.id]
    assert [s.id for s in pg_store.list_sessions(project_id=project.id)] == [session.id]


def test_firewall_log_on_postgres(pg_store, cfg):
    from twin import ids
    from twin.clock import now_iso
    from twin.privacy.firewall import Firewall
    from twin.store.models import StoreClaim

    mem = StoreClaim(id=ids.claim_id(), type="fact", title="x", summary="x",
                     domain="relationship", status="confirmed", confidence=0.9,
                     created_at=now_iso(), updated_at=now_iso())
    fw = Firewall(cfg.policies_path, pg_store)
    verdict = fw.evaluate(mem, "work")
    assert not verdict.allowed
    rows = pg_store._exec("SELECT * FROM firewall_log")
    assert len(rows) == 1


def test_merge_transaction_rollback_on_postgres(pg_store, embedder):
    """Same fault-injection as SQLite — Postgres must roll back structural merge."""
    from twin import ids
    from twin.store.lifecycle import merge_claims
    from twin.store.models import StoreClaim, ClaimStatus

    def _mem(**kw):
        base = dict(
            id=ids.claim_id(), type="fact", title="t", summary="s",
            domain="technical", confidence=0.9, status="confirmed",
            entities=["Twin"],
        )
        base.update(kw)
        mem = StoreClaim(**base)
        pg_store.insert_claim(mem)
        pg_store.store_embedding(
            mem.id, "claim", embedder.name,
            embedder.embed(f"{mem.title}\n{mem.summary}"),
        )
        return mem

    a = _mem(title="A", summary="alpha fact about Twin")
    b = _mem(title="B", summary="beta fact about Twin")
    a_id, b_id = a.id, b.id
    before_ids = {m.id for m in pg_store.list_claims(limit=1000)}

    real_update = pg_store.update_claim
    calls = {"n": 0}

    def boom(mid, **kwargs):
        calls["n"] += 1
        if kwargs.get("status") == ClaimStatus.merged.value and calls["n"] >= 2:
            raise RuntimeError("injected failure")
        return real_update(mid, **kwargs)

    pg_store.update_claim = boom  # type: ignore[method-assign]
    try:
        with pytest.raises(RuntimeError, match="injected"):
            merge_claims(pg_store, [a_id, b_id], embedder=embedder)
    finally:
        pg_store.update_claim = real_update  # type: ignore[method-assign]

    assert pg_store.get_claim(a_id).status != ClaimStatus.merged
    assert pg_store.get_claim(b_id).status != ClaimStatus.merged
    after_ids = {m.id for m in pg_store.list_claims(limit=1000)}
    assert after_ids == before_ids


def test_connector_framework_on_postgres(pg_store, tmp_path):
    """The connector spine holds the same invariants on Postgres: atomic
    finalize, lease exclusion, CAS checkpoints, collision handling and
    partial batches that expose nothing cognitive."""
    from twin.sense.connectors import (
        add_connector_instance,
        build_credential_store,
        register_source_account,
        sync_connector,
    )
    from twin.sense.connectors.models import ConnectorCheckpoint

    creds = build_credential_store(tmp_path / "pg-creds")
    acc = register_source_account(
        pg_store, connector_type="fake", source_owner="employer",
        org_key="acme", owner_principal_id="principal_pg_test",
    )
    inst = add_connector_instance(pg_store, creds, account_id=acc.id,
                                  secret="tok-pg")

    # commit + checkpoint in one transaction
    result = sync_connector(pg_store, creds, inst.id)
    assert result.health.value == "healthy"
    assert result.percepts == 3
    ckpt = pg_store.get_connector_checkpoint(inst.id, "issues")
    assert ckpt is not None and ckpt.version == 1
    assert len(pg_store.list_connector_records(inst.id)) == 3

    # idempotent replay
    assert sync_connector(pg_store, creds, inst.id).percepts == 0

    # CAS refuses a stale version
    stale = ConnectorCheckpoint(connector_id=inst.id, stream="issues",
                                cursor={"seq": 0})
    assert pg_store.cas_connector_checkpoint(stale, expected_version=0) is False

    # lease exclusion
    token_w1 = pg_store.acquire_stream_lease(inst.id, "issues", "w1")
    assert token_w1 is not None
    assert pg_store.acquire_stream_lease(inst.id, "issues", "w2") is None
    # fencing: w1 renews under its token; a stale/foreign token cannot
    assert pg_store.renew_stream_lease(inst.id, "issues", "w1", token_w1) is True
    assert pg_store.renew_stream_lease(inst.id, "issues", "w2", token_w1) is False
    # fenced release: a stale token cannot expire the lease; the current can
    pg_store.release_stream_lease(inst.id, "issues", "w1", token_w1 - 1)
    assert pg_store.acquire_stream_lease(inst.id, "issues", "w2") is None
    pg_store.release_stream_lease(inst.id, "issues", "w1", token_w1)
    token_w2 = pg_store.acquire_stream_lease(inst.id, "issues", "w2")
    assert token_w2 is not None and token_w2 > token_w1  # monotonic fencing
    pg_store.release_stream_lease(inst.id, "issues", "w2", token_w2)

    # partial failure persists nothing cognitive and keeps the checkpoint
    fx = {"issues": [
        {"external_id": "50", "external_revision": "1", "seq": 50,
         "content": "good item"},
        {"external_id": "51", "external_revision": "1", "seq": 51,
         "content": "bad item"},
    ], "pull_requests": []}
    pg_store.update_connector_instance(
        inst.id, configuration={"fixtures": fx, "normalize_fail_ids": ["51"],
                                "incremental": True})
    before = len(pg_store.list_percepts())
    version_before = pg_store.get_connector_checkpoint(inst.id, "issues").version
    partial = sync_connector(pg_store, creds, inst.id)
    issues = next(s for s in partial.streams if s.stream == "issues")
    assert issues.committed is False
    assert len(pg_store.list_percepts()) == before
    assert pg_store.get_connector_checkpoint(inst.id, "issues").version == version_before
    assert pg_store.list_connector_dead_letters(inst.id)

    # tombstone → deletion event with prior lineage
    fx2 = {"issues": [
        {"external_id": "1", "external_revision": "2", "seq": 60,
         "content": "", "deleted": True},
    ], "pull_requests": []}
    pg_store.update_connector_instance(
        inst.id, configuration={"fixtures": fx2, "incremental": True})
    sync_connector(pg_store, creds, inst.id)
    events = pg_store.list_connector_deletion_events(inst.id)
    assert events and events[0].external_id == "1"
    assert events[0].affected_percept_ids


def test_github_connector_on_postgres(pg_store, tmp_path, monkeypatch):
    """The real GitHub adapter path (dynamic streams, watermark cursor,
    lifecycle trust, idempotent replay) holds on Postgres too."""
    import httpx

    from tests.connectors.github.github_mock import FakeGitHubAPI
    from twin.sense.connectors import (
        add_connector_instance,
        build_credential_store,
        register_source_account,
        sync_connector,
    )
    from twin.sense.connectors.github import client as ghclient

    api = FakeGitHubAPI()
    repo = "acme/atlas"
    api.add_repo(repo)
    real_build = ghclient._build_http

    def fake_build(base_url, token):
        original = real_build(base_url, token)
        headers = dict(original.headers)
        original.close()
        return httpx.Client(transport=api.transport(),
                            base_url="https://api.github.com", headers=headers)

    monkeypatch.setattr(ghclient, "_build_http", fake_build)

    api.add_issue(repo, 1, title="Choose the queue",
                  body="We must pick a message queue.",
                  updated_at="2026-01-01T10:00:00Z")
    pr = api.add_pull(repo, 2, title="Use PostgreSQL queue",
                      body="We decided to use PostgreSQL for the queue.",
                      updated_at="2026-01-02T10:00:00Z", merged=True,
                      head_sha="abc123")
    api.add_review(repo, 2, 500, state="APPROVED", body="Ship it")

    creds = build_credential_store(tmp_path / "pg-gh-creds")
    acc = register_source_account(
        pg_store, connector_type="github", source_owner="employer",
        org_key="acme", owner_principal_id="principal_pg_test",
    )
    inst = add_connector_instance(
        pg_store, creds, account_id=acc.id, secret="gh-test-token",
        configuration={"repositories": [repo]},
    )

    result = sync_connector(pg_store, creds, inst.id)
    assert result.health.value == "healthy"
    ckpt = pg_store.get_connector_checkpoint(inst.id, f"repo:{repo}:issues")
    assert ckpt is not None and ckpt.cursor["watermark"] == "2026-01-01T10:00:00Z"

    records = pg_store.list_connector_records(inst.id)
    prs = [r for r in records if r.external_type == "pull_request"]
    assert prs and prs[0].confidentiality["source_trust"] == 0.95
    assert prs[0].thread_key == f"github:{repo}#2"
    reviews = [r for r in records if r.external_type == "review"]
    assert reviews and reviews[0].confidentiality["source_trust"] == 0.90

    percepts = pg_store.list_percepts()
    assert percepts and all(p.metadata["vault_id"] == "vault_work_acme"
                            for p in percepts)

    # idempotent replay, then a new revision lands without erasing the old
    assert sync_connector(pg_store, creds, inst.id).percepts == 0
    pr["body"] = "We decided to use PostgreSQL advisory locks for the queue."
    pr["updated_at"] = "2026-01-03T10:00:00Z"
    sync_connector(pg_store, creds, inst.id)
    prs = [r for r in pg_store.list_connector_records(inst.id)
           if r.external_type == "pull_request"]
    assert len(prs) == 2
    assert {r.external_revision for r in prs} == {
        "2026-01-02T10:00:00Z", "2026-01-03T10:00:00Z"}


def test_connector_counter_claim_bump_atomic_on_postgres(pg_store, tmp_path):
    """Claim + bump share one Postgres transaction — crash rolls the ledger back."""
    from twin.sense.connectors import (
        add_connector_instance,
        build_credential_store,
        record_batch_counters,
        register_source_account,
    )
    from twin.sense.connectors.counters import batch_contribution
    from twin.sense.connectors.models import BatchStatus, ConnectorBatch

    class _Crash(Exception):
        pass

    creds = build_credential_store(tmp_path / "pg-counter-creds")
    acc = register_source_account(
        pg_store, connector_type="fake", source_owner="employer",
        org_key="acme", owner_principal_id="principal_pg_counter",
    )
    inst = add_connector_instance(
        pg_store, creds, account_id=acc.id, secret="tok-pg-counter",
    )
    batch = ConnectorBatch(
        connector_id=inst.id, stream="issues",
        status=BatchStatus.committed,
        raw_count=9, normalized_count=9, percept_count=9,
    )
    pg_store.insert_connector_batch(batch)
    contrib = batch_contribution(batch)

    with pytest.raises(_Crash):
        with pg_store.transaction():
            assert pg_store.claim_connector_counter_batch(
                inst.id, batch.id, contrib,
            ) is True
            raise _Crash("after claim")

    assert not pg_store.connector_counter_batch_claimed(inst.id, batch.id)

    record_batch_counters(pg_store, inst.id, batch)
    record_batch_counters(pg_store, inst.id, batch)
    state = pg_store.get_connector_sync_state(inst.id)
    assert state is not None and state.fetch_total == 9


def test_interpretation_state_and_deferral_on_postgres(pg_store, cfg, embedder):
    """The v0.7 interpretation spine holds on Postgres: an unavailable
    interpreter defers (nothing catalogued, retryable), and a later run
    interprets the same percept and marks it terminal."""
    from twin.cognize.services import (
        extract_percept,
        set_interpreter_override,
    )
    from twin.cognize.services.interpreter.schema import (
        CognitiveAct,
        InterpretationResult,
        InterpretationStatus,
        InterpretedItem,
    )
    from twin.sense.sensory.percept import Percept

    cfg.extractor = "auto"
    cfg.ollama_url = "http://127.0.0.1:1"  # unreachable → defer
    p = Percept(percept_type="document", source_sensor="document",
                content="We decided to use PostgreSQL advisory locks.",
                source_trust=0.95).seal()
    pg_store.insert_percept(p)

    try:
        report = extract_percept(pg_store, cfg, embedder, p)
        assert report.deferred is True
        assert pg_store.list_claims() == []
        state = pg_store.get_interpretation(p.id)
        assert state.status == "deferred" and state.failure_class == "unavailable"
        assert state.terminal is False and state.interpretation_attempted is True
        # outage never consumes the budget: still eligible after many defers
        for _ in range(8):
            extract_percept(pg_store, cfg, embedder, p)
        pending = pg_store.percepts_pending_interpretation(max_attempts=6)
        assert p.id in [x.id for x in pending]

        set_interpreter_override(lambda percept, text, c: InterpretationResult(
            items=[InterpretedItem(
                claim_type="decision", cognitive_act=CognitiveAct.decision,
                title="Use PostgreSQL advisory locks",
                summary="The team decided to use PostgreSQL advisory locks.",
                domain="technical", confidence=0.9,
                evidence_span="We decided to use PostgreSQL advisory locks.")],
            status=InterpretationStatus.interpreted, interpreter="ollama:test",
            model="test", prompt_version="interpret-v1", schema_version="1"))
        report = extract_percept(pg_store, cfg, embedder, p)
        assert report.inserted and report.deferred is False
        state = pg_store.get_interpretation(p.id)
        assert state.status == "interpreted"
        assert pg_store.percepts_pending_interpretation(max_attempts=6) == []
    finally:
        set_interpreter_override(None)


def test_detection_signals_on_postgres(pg_store, cfg, embedder):
    """Heuristic mode records DetectionSignals (never memories) on Postgres."""
    from twin.cognize.services import extract_percept
    from twin.sense.sensory.percept import Percept

    cfg.extractor = "heuristic"
    p = Percept(percept_type="document", source_sensor="document",
                content="We decided to use PostgreSQL for the queue.",
                source_trust=0.9).seal()
    pg_store.insert_percept(p)
    report = extract_percept(pg_store, cfg, embedder, p)
    assert report.interpretation_status == "heuristic_detection"
    assert pg_store.list_claims() == []
    signals = pg_store.list_detection_signals(p.id)
    assert signals and all(s.span for s in signals)
    state = pg_store.get_interpretation(p.id)
    assert state.status == "heuristic_detection" and state.terminal is True
    assert state.interpretation_attempted is False


def test_workspace_tick_running_blocks_on_postgres(pg_store, cfg, embedder):
    from twin.cognize.services.workspace import text_content_hash, workspace_tick
    from twin.store.store.workspace_ops_mixin import WorkspaceTickRecord

    text = "postgres concurrent tick must not double-run"
    existing = WorkspaceTickRecord(
        session_id="ses_pg_race",
        sequence=1,
        input_mode="delta",
        content_hash=text_content_hash(text),
        interpret=True,
        status="running",
    )
    pg_store.try_begin_workspace_tick(existing)
    result = workspace_tick(
        pg_store, cfg, embedder, text,
        target_domain="technical",
        interpret=True,
        input_mode="delta",
        session_id="ses_pg_race",
        sequence=1,
    )
    assert result.duplicated is True
    assert result.stages == ["blocked_concurrent"]


def test_consolidation_window_unique_on_postgres(pg_store, cfg, embedder):
    from datetime import datetime, timezone

    from twin.cognize.services.consolidation_cycle import run_consolidation_cycle

    as_of = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    first = run_consolidation_cycle(
        pg_store, cfg, embedder, kind="daily", dry_run=False, as_of=as_of,
    )
    second = run_consolidation_cycle(
        pg_store, cfg, embedder, kind="daily", dry_run=False, as_of=as_of,
    )
    assert first.run_id
    assert second.duplicated is True
    assert second.run_id == first.run_id


def test_retry_cas_on_postgres(pg_store):
    from twin.clock import now_iso
    from twin.store.store.workspace_ops_mixin import (
        ConsolidationRunRecord,
        WorkspaceTickRecord,
    )

    tick = WorkspaceTickRecord(
        session_id="ses_pg_cas", sequence=1, content_hash="h",
        input_mode="delta", interpret=True, status="error",
        error="RuntimeError: x", error_stage="observe",
        started_at=now_iso(), completed_at=now_iso(),
    )
    pg_store.insert_workspace_tick(tick)
    assert pg_store.try_claim_workspace_tick_retry(tick.id) is True
    assert pg_store.try_claim_workspace_tick_retry(tick.id) is False

    run = ConsolidationRunRecord(
        kind="weekly", window_start="2026-01-01", window_end="2026-01-07",
        dry_run=False, status="error", error="RuntimeError: y",
        error_stage="analyze", started_at=now_iso(), completed_at=now_iso(),
    )
    pg_store.insert_consolidation_run(run)
    assert pg_store.try_claim_consolidation_retry(run.id) is True
    assert pg_store.try_claim_consolidation_retry(run.id) is False
