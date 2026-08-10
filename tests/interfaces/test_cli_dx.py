"""Branded CLI DX: human output by default, --json escape hatch for scripts.

These are smoke tests — they assert the command runs (no crash / clean exit)
and that ``--json`` yields parseable JSON on stdout, rather than pinning exact
Rich markup (which differs between TTY and CI).
"""

from __future__ import annotations

import json

import pytest

from twin.interfaces import cli


def _run(home, capsys, *argv) -> str:
    cli.main(["--home", str(home), *argv])
    return capsys.readouterr().out


@pytest.fixture(autouse=True)
def _offline_embedder(monkeypatch):
    monkeypatch.setenv("TWIN_EMBEDDER", "hash")
    monkeypatch.setenv("TWIN_EXTRACTOR", "echo")


@pytest.mark.parametrize(
    "argv, keys",
    [
        (("connector", "adapters", "--json"), ("adapters",)),
        (("connector", "list", "--json"), ("connectors", "count")),
        (("interpret", "status", "--json"), ("never_interpreted", "interpreted")),
        (("stats", "--json"), ("percepts", "memories")),
        (("stance", "list", "--json"), ("stances", "count")),
        (("narrative", "unsupported", "--json"), ("unsupported", "count")),
        (("cognize", "status", "--json"), ("pending_percepts", "gate_ok")),
    ],
)
def test_json_flag_emits_parseable_json(tmp_path, capsys, argv, keys):
    out = _run(tmp_path / "home", capsys, *argv)
    data = json.loads(out)
    for key in keys:
        assert key in data


def test_connector_adapters_human_is_branded(tmp_path, capsys):
    out = _run(tmp_path / "home", capsys, "connector", "adapters")
    # branded rule title + table header, not a raw JSON dump
    assert "connector adapters" in out
    assert not out.lstrip().startswith("{")


def test_connector_list_empty_state_guides_next_step(tmp_path, capsys):
    out = _run(tmp_path / "home", capsys, "connector", "list")
    assert "no connectors yet" in out
    assert "twin connector setup" in out


def test_cognize_status_human(tmp_path, capsys):
    out = _run(tmp_path / "home", capsys, "cognize", "status")
    assert "cognize" in out
    assert not out.lstrip().startswith("{")


def test_github_repositories_select_writes_scope(tmp_path, capsys, monkeypatch):
    """`twin connector github repositories <id> --select …` picks the sync
    scope: it writes the `repositories` config key, preserves other config,
    and never crashes on a repo the credential cannot see."""
    import types

    from twin.connectors.models import (
        ConnectorInstance, ConnectorStatus, OwnershipClass, SourceAccount,
    )
    from twin.interfaces import cli
    from twin.interfaces.commands import cli_handlers
    from twin.memory.store.sqlite import SqliteStore

    store = SqliteStore(str(tmp_path / "twin.db"))
    acc = SourceAccount(connector_type="github", source_owner=OwnershipClass.personal,
                        owner_principal_id="p", vault_id="vault_personal")
    store.insert_source_account(acc)
    inst = ConnectorInstance(connector_type="github", account_id=acc.id,
                             status=ConnectorStatus.active, credential_ref="cred_x",
                             configuration={"lookback_seconds": 3600})
    store.insert_connector_instance(inst)

    fake = types.SimpleNamespace(list_repositories=lambda: [
        {"full_name": "caribeedu/twin", "private": True,
         "open_issues": 3, "pushed_at": "x"},
    ])
    monkeypatch.setattr(cli_handlers, "_connector_adapter", lambda ws, creds, cid: fake)

    args = types.SimpleNamespace(
        connector_id=inst.id, connector_command="repositories",
        select=["caribeedu/twin", "ghost/missing"], json=False)
    ws = types.SimpleNamespace(store=store)
    cli_handlers._connector_discovery(
        args, ws, None, method="list_repositories",
        headers=["repository"], row=lambda r: [r["full_name"]],
        scope_key="repositories", id_of=lambda r: r.get("full_name"))

    updated = store.get_connector_instance(inst.id)
    assert updated.configuration["repositories"] == ["caribeedu/twin", "ghost/missing"]
    assert updated.configuration["lookback_seconds"] == 3600   # preserved
    out = capsys.readouterr().out
    assert "repositories set to 2" in out
    assert "not visible to this credential" in out             # ghost/missing warned
    store.close()


def test_connector_setup_plan_is_stepped_and_never_ingests(tmp_path, capsys):
    out = _run(
        tmp_path / "home", capsys,
        "connector", "setup", "github", "--source-owner", "personal",
    )
    assert "connector setup" in out
    assert "plan only" in out


def test_interpret_status_human_shows_counts(tmp_path, capsys):
    out = _run(tmp_path / "home", capsys, "interpret", "status")
    assert "interpret" in out
    assert "never interpreted" in out
