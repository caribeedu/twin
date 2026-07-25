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
        (("judgment", "list", "--json"), ("items", "count")),
        (("memory", "unsupported", "--json"), ("unsupported", "count")),
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
