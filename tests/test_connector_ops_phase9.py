"""v0.6 Phase 9 — evals and operations glue.

Covers §57 health shape, §58 connector metrics, §77 setup plan (no ingest),
scheduler due/sync-due surfaces, doctor connector checks and the §88 contract
matrix. Behavioural ingest invariants stay in test_connectors / per-adapter
suites.
"""

from __future__ import annotations

import json

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


def test_health_exposes_section_57_fields(store, creds):
    _, inst = _make(store, creds)
    sync_connector(store, creds, inst.id)
    health = connector_health(store, inst.id)
    for key in (
        "lag_seconds", "pending_items", "last_checkpoint_at",
        "rate_limit_remaining", "dead_letters", "health",
        "last_success_at", "checkpoints",
    ):
        assert key in health, key
    assert health["health"] == "healthy"
    assert health["lag_seconds"] == 0
    assert health["last_checkpoint_at"] is not None
    assert isinstance(health["pending_items"], int)
    assert health["dead_letters"] == 0


def test_connector_metrics_aggregate_after_sync(store, creds):
    _, inst = _make(store, creds)
    sync_connector(store, creds, inst.id)
    block = compute_connector_metrics(store)["connectors"]
    assert block["available"] is True
    assert block["instances"] >= 1
    assert block["connector_fetch_total"] >= 3
    assert block["connector_items_normalized"] >= 3
    assert block["connector_memory_candidates"] >= 3
    assert "fake" in block["by_type"]
    row = next(r for r in block["per_connector"] if r["connector_id"] == inst.id)
    assert row["vault_id"] == "vault_work_acme"
    assert row["normalized"] >= 3


def test_stats_includes_connector_block(store, creds):
    _, inst = _make(store, creds)
    sync_connector(store, creds, inst.id)
    metrics = compute_metrics(store)
    assert "connectors" in metrics
    assert metrics["connectors"]["connector_fetch_total"] >= 3


def test_setup_plan_never_ingests(store, creds):
    plan = plan_connector_setup(
        store, connector_type="github", source_owner="employer",
        org_key="acme", display_name="Work GH",
    )
    assert plan["ok"] is True
    assert plan["started"] is False
    assert plan["ingests"] is False
    assert len(plan["steps"]) >= 4
    assert store.list_connector_instances() == []
    assert store.list_percepts() == []


def test_setup_rejects_unknown_type(store):
    plan = plan_connector_setup(store, connector_type="nope", source_owner="personal")
    assert plan["ok"] is False
    assert "unknown" in plan["error"]


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
    # freshly added active connector with no next_run → due
    listed = list_due_connectors(store, tmp_path)
    assert listed["count"] >= 1
    assert any(r["connector_id"] == inst.id for r in listed["due"])

    from twin.connectors import run_sync_due
    rows = run_sync_due(store, creds, tmp_path)
    assert any(r["connector_id"] == inst.id and r["ok"] for r in rows)
    assert len(store.list_connector_records(inst.id)) >= 3


def test_doctor_connector_checks(store, creds, tmp_path):
    _make(store, creds)
    checks = doctor_connector_checks(store, tmp_path)
    names = {c["name"] for c in checks}
    assert "connectors:schedule" in names
    assert "connectors:credentials" in names
    assert "connectors:instances" in names
    assert all(c["status"] in ("ok", "warn", "fail") for c in checks)


def test_contract_matrix_covers_all_adapters():
    matrix = contract_matrix()
    assert matrix["ok"] is True
    registered = set(list_adapters())
    assert {r["connector_type"] for r in matrix["rows"]} == registered
    for name in registered:
        row = check_adapter_contract(name)
        assert row["ok"] is True, (name, row["gaps"], row["items"])
        assert row["protocol_ok"] is True
        assert row["items"]["manifest_complete"] == "pass"


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
    assert matrix["ok"] is True
    assert matrix["adapters"] >= 1
