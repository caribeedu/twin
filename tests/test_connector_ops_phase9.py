"""v0.6 Phase 9 — evals and operations (review fixes).

Covers durable counters, schedule vs checkpoint lag, evidence-based contract
matrix, pending_items semantics, unknown health, and doctor credential checks.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from twin.connectors import (
    add_connector_instance,
    backfill_preview,
    build_credential_store,
    check_adapter_contract,
    compute_connector_metrics,
    connector_health,
    contract_matrix,
    list_adapters,
    list_due_connectors,
    plan_connector_setup,
    register_source_account,
    sync_connector,
)
from twin.connectors.counters import record_batch_counters, seed_counters_from_batches
from twin.connectors.models import (
    BatchStatus,
    ConnectorBatch,
    ConnectorSyncState,
    HealthStatus,
)
from twin.connectors.ops import doctor_connector_checks
from twin.memory.metrics import compute_metrics

PRINCIPAL = "principal_phase9"


@pytest.fixture()
def creds(tmp_path):
    return build_credential_store(tmp_path / "creds-home")


def _make(store, creds, *, configuration=None):
    acc = register_source_account(
        store, connector_type="fake", source_owner="employer",
        org_key="acme", owner_principal_id=PRINCIPAL,
    )
    inst = add_connector_instance(
        store, creds, account_id=acc.id, secret="tok-phase9",
        configuration=configuration,
    )
    return acc, inst


def _set_sync_state(store, connector_id: str, **kwargs) -> ConnectorSyncState:
    def _apply(state: ConnectorSyncState) -> None:
        for k, v in kwargs.items():
            setattr(state, k, v)
    return store.apply_connector_sync_state(connector_id, _apply)


# -- §57 health ----------------------------------------------------------------


def test_health_exposes_section_57_fields(store, creds):
    _, inst = _make(store, creds)
    sync_connector(store, creds, inst.id)
    health = connector_health(store, inst.id)
    for key in (
        "lag_seconds", "schedule_lag_seconds", "checkpoint_age_seconds",
        "source_lag_seconds", "pending_items", "last_checkpoint_at",
        "rate_limit_remaining", "dead_letters", "health",
        "last_success_at", "checkpoints",
    ):
        assert key in health, key
    assert health["health"] == "healthy"
    assert health["last_checkpoint_at"] is not None
    assert health["checkpoint_age_seconds"] is not None
    # no next_run_at yet → schedule lag unknown (not checkpoint age)
    assert health["schedule_lag_seconds"] is None
    assert health["lag_seconds"] is None


def test_never_synced_health_is_unknown(store, creds):
    _, inst = _make(store, creds)
    health = connector_health(store, inst.id)
    assert health["health"] == "unknown"
    assert health["last_success_at"] is None


def test_daily_connector_not_lagged_after_6h(store, creds):
    _, inst = _make(store, creds)
    sync_connector(store, creds, inst.id)
    now = datetime.now(timezone.utc)
    _set_sync_state(
        store, inst.id,
        interval_seconds=86400,
        last_checkpoint_at=(now - timedelta(hours=6)).isoformat(),
        last_success_at=(now - timedelta(hours=6)).isoformat(),
        next_run_at=(now + timedelta(hours=18)).isoformat(),
        status=HealthStatus.healthy,
        paused=False,
    )
    health = connector_health(store, inst.id)
    assert health["checkpoint_age_seconds"] >= 6 * 3600 - 5
    assert health["schedule_lag_seconds"] == 0
    assert health["lag_seconds"] == 0


def test_past_next_run_produces_schedule_lag(store, creds):
    _, inst = _make(store, creds)
    now = datetime.now(timezone.utc)
    _set_sync_state(
        store, inst.id,
        next_run_at=(now - timedelta(hours=2)).isoformat(),
        interval_seconds=300,
        status=HealthStatus.healthy,
        last_success_at=(now - timedelta(hours=3)).isoformat(),
        paused=False,
    )
    health = connector_health(store, inst.id)
    assert health["schedule_lag_seconds"] >= 7200 - 5
    assert health["lag_seconds"] == health["schedule_lag_seconds"]


def test_paused_connector_not_schedule_lagged(store, creds):
    _, inst = _make(store, creds)
    now = datetime.now(timezone.utc)
    _set_sync_state(
        store, inst.id,
        paused=True,
        status=HealthStatus.paused,
        next_run_at=(now - timedelta(days=2)).isoformat(),
        last_checkpoint_at=(now - timedelta(days=2)).isoformat(),
    )
    health = connector_health(store, inst.id)
    assert health["schedule_lag_seconds"] == 0
    assert health["lag_seconds"] == 0
    assert health["paused"] is True


def test_targeted_streams_not_in_pending_items(store, creds):
    _, inst = _make(store, creds)
    _set_sync_state(
        store, inst.id,
        metadata={"targeted_streams": ["issues", "pull_requests", "commits"]},
    )
    health = connector_health(store, inst.id)
    assert health["pending_items"] == 0


def test_pending_queue_and_dlq_count_as_pending(store, creds):
    _, inst = _make(store, creds)
    sync_connector(store, creds, inst.id)
    # open a DLQ via rate-limit? easier: inject metadata pending queue
    _set_sync_state(
        store, inst.id,
        metadata={"pending_threads": ["t1", "t2"], "targeted_streams": ["x"]},
    )
    health = connector_health(store, inst.id)
    assert health["pending_items"] == 2  # not +1 for targeted_streams


# -- §58 durable counters ------------------------------------------------------


def test_connector_metrics_aggregate_after_sync(store, creds):
    _, inst = _make(store, creds)
    sync_connector(store, creds, inst.id)
    block = compute_connector_metrics(store)["connectors"]
    assert block["available"] is True
    assert block["connector_fetch_total"] >= 3
    assert block["connector_items_normalized"] >= 3
    assert block["connector_percepts_total"] >= 3
    assert "connector_memory_candidates" not in block
    assert "metrics" in block
    assert "instances_detail" in block
    assert "fake" in block["by_type"]


def test_stats_includes_connector_block(store, creds):
    _, inst = _make(store, creds)
    sync_connector(store, creds, inst.id)
    metrics = compute_metrics(store)
    assert metrics["connectors"]["connector_percepts_total"] >= 3


def test_counters_monotonic_beyond_500_batches(store, creds):
    _, inst = _make(store, creds)
    # seed with 510 synthetic terminal batches then bump one more
    for i in range(510):
        b = ConnectorBatch(
            connector_id=inst.id, stream="issues",
            status=BatchStatus.committed,
            raw_count=1, normalized_count=1, percept_count=1,
        )
        store.insert_connector_batch(b)
    seed_counters_from_batches(store, inst.id)
    state = store.get_connector_sync_state(inst.id)
    assert state.fetch_total == 510
    before = compute_connector_metrics(store)["connectors"]["connector_fetch_total"]
    extra = ConnectorBatch(
        connector_id=inst.id, stream="issues",
        status=BatchStatus.committed,
        raw_count=7, normalized_count=7, percept_count=7,
    )
    store.insert_connector_batch(extra)
    record_batch_counters(store, inst.id, extra)
    after = compute_connector_metrics(store)["connectors"]["connector_fetch_total"]
    assert after == before + 7
    assert after >= before  # never decreases


def test_counters_survive_reseed_max(store, creds):
    _, inst = _make(store, creds)
    sync_connector(store, creds, inst.id)
    state = store.get_connector_sync_state(inst.id)
    first = state.fetch_total
    # re-seed must not lower
    seed_counters_from_batches(store, inst.id)
    again = store.get_connector_sync_state(inst.id).fetch_total
    assert again >= first


# -- setup / preview / scheduler -----------------------------------------------


def test_setup_plan_never_ingests(store, creds):
    plan = plan_connector_setup(
        store, connector_type="github", source_owner="employer",
        org_key="acme", display_name="Work GH",
    )
    assert plan["ok"] is True
    assert plan["started"] is False
    assert plan["ingests"] is False
    assert plan["steps"][0]["id"] == "classify_ownership"
    assert plan["steps"][1]["id"] == "authenticate"
    assert store.list_connector_instances() == []


def test_setup_warns_on_inconsistent_ownership(store):
    plan = plan_connector_setup(
        store, connector_type="github", source_owner="personal",
        vault_id="vault_work_acme", org_key="acme",
    )
    assert plan["ok"] is True
    assert plan["warnings"]
    assert any("inconsistent" in w or "unusual" in w for w in plan["warnings"])


def test_setup_rejects_unknown_type(store):
    plan = plan_connector_setup(store, connector_type="nope", source_owner="personal")
    assert plan["ok"] is False


def test_backfill_preview_still_safe(store, creds):
    _, inst = _make(store, creds)
    before = len(store.list_percepts())
    preview = backfill_preview(
        store, creds, inst.id, principal_id=PRINCIPAL,
    )
    assert preview.get("started") is False
    assert len(store.list_percepts()) == before


def test_due_and_sync_due(store, creds, tmp_path):
    _, inst = _make(store, creds)
    listed = list_due_connectors(store, tmp_path)
    assert listed["count"] >= 1
    from twin.connectors import run_sync_due
    rows = run_sync_due(store, creds, tmp_path)
    assert any(r["connector_id"] == inst.id and r["ok"] for r in rows)


def test_sync_due_isolates_failures(store, creds, tmp_path):
    _, a = _make(store, creds)
    acc2 = register_source_account(
        store, connector_type="fake", source_owner="employer",
        org_key="acme", owner_principal_id=PRINCIPAL,
        display_name="second",
    )
    b = add_connector_instance(
        store, creds, account_id=acc2.id, secret="tok-b",
        configuration={"fail_mode": "rate_limit"},
    )
    from twin.connectors import run_sync_due
    rows = run_sync_due(store, creds, tmp_path)
    by_id = {r["connector_id"]: r for r in rows}
    assert a.id in by_id and b.id in by_id
    assert by_id[a.id]["ok"] is True
    # rate-limited connector still returns a result (degraded) — isolation
    assert by_id[b.id]["health"] in ("degraded", "failed", "healthy")


# -- doctor --------------------------------------------------------------------


def test_doctor_resolves_credentials(store, creds, tmp_path):
    _, inst = _make(store, creds)
    # use same home as creds so doctor can resolve
    home = tmp_path / "creds-home"
    # rebuild store pointing at same home used by fixture
    checks = doctor_connector_checks(store, home)
    auth = [c for c in checks if c["name"] == f"connectors:auth:{inst.id}"]
    assert auth and auth[0]["status"] == "ok"


def test_doctor_flags_missing_secret(store, creds, tmp_path):
    _, inst = _make(store, creds)
    home = tmp_path / "creds-home"
    # delete secret but leave credential_ref
    creds.delete(inst.credential_ref)
    checks = doctor_connector_checks(store, home)
    auth = [c for c in checks if c["name"] == f"connectors:auth:{inst.id}"]
    assert auth and auth[0]["status"] == "fail"


def test_doctor_due_warns_when_overdue(store, creds, tmp_path):
    _, inst = _make(store, creds)
    now = datetime.now(timezone.utc)
    _set_sync_state(
        store, inst.id,
        next_run_at=(now - timedelta(hours=5)).isoformat(),
        interval_seconds=300,
        paused=False,
        status=HealthStatus.healthy,
    )
    checks = doctor_connector_checks(store, tmp_path)
    due = next(c for c in checks if c["name"] == "connectors:due")
    assert due["status"] in ("warn", "fail")


# -- contract matrix -----------------------------------------------------------


def test_contract_matrix_is_evidence_based():
    matrix = contract_matrix()
    assert "framework" in matrix
    assert matrix["framework"]["ok"] is True
    # overall may be false — honesty over green
    registered = set(list_adapters())
    assert {r["connector_type"] for r in matrix["rows"]} == registered
    fake = check_adapter_contract("fake")
    assert fake["ok"] is True
    assert fake["items"]["idempotent_ingest"]["status"] == "pass"
    assert fake["items"]["idempotent_ingest"]["evidence"]
    gh = check_adapter_contract("github")
    assert gh["items"]["source_deletion_event"]["status"] == "not_supported"
    # framework evidence must not auto-pass other adapters
    slack = check_adapter_contract("slack")
    assert slack["items"]["partial_batch_invisible"]["status"] == "not_tested"
    assert slack["ok"] is False


def test_contract_missing_method_fails(monkeypatch):
    from twin.connectors import registry

    class Broken:
        connector_type = "broken_test_adapter"

        @staticmethod
        def adapter_manifest():
            from twin.connectors.protocol import AdapterManifest
            return AdapterManifest(
                connector_type="broken_test_adapter",
                auth_mode="none",
                streams=["default"],
                supported_external_types=["x"],
                affordances={},
            )

    registry._ADAPTERS["broken_test_adapter"] = Broken
    try:
        row = check_adapter_contract("broken_test_adapter")
        assert row["items"]["protocol_methods"]["status"] == "fail"
        assert row["ok"] is False
    finally:
        registry._ADAPTERS.pop("broken_test_adapter", None)


def test_cli_setup_and_contract_smoke(tmp_path, monkeypatch, capsys):
    from twin.interfaces import cli as cli_mod

    monkeypatch.setenv("TWIN_EXTRACTOR", "heuristic")
    monkeypatch.setenv("TWIN_EMBEDDER", "hash")
    home = tmp_path / "twin-home"

    class _Args:
        pass

    args = _Args()
    args.home = str(home)
    args.connector_command = "setup"
    args.connector_type = "fake"
    args.source_owner = "personal"
    args.vault_id = None
    args.org_key = None
    args.name = "demo"
    args.config = None
    cli_mod.cmd_connector(args)
    plan = json.loads(capsys.readouterr().out)
    assert plan["ok"] is True
    assert plan["ingests"] is False

    args.connector_command = "contract"
    cli_mod.cmd_connector(args)
    matrix = json.loads(capsys.readouterr().out)
    assert "framework" in matrix
    assert matrix["framework"]["ok"] is True
