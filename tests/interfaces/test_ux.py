"""CLI UX helpers."""

from __future__ import annotations

import io
import os
from pathlib import Path

from twin.cognize.services import extract_pending
from twin.interfaces import ux
from twin.interfaces.setup_wizard import run_setup_wizard
from twin.sense.sensory import sense_paths
from tests.paths import EXAMPLES


def test_write_and_apply_env_file(tmp_path, monkeypatch):
    path = tmp_path / "env"
    ux.write_env_file(path, {"TWIN_OLLAMA_URL": "http://example:11434", "TWIN_OLLAMA_MODEL": "m"})
    monkeypatch.delenv("TWIN_OLLAMA_URL", raising=False)
    monkeypatch.setenv("TWIN_OLLAMA_MODEL", "already-set")
    ux.apply_env_file(path)
    assert os.environ["TWIN_OLLAMA_URL"] == "http://example:11434"
    assert os.environ["TWIN_OLLAMA_MODEL"] == "already-set"  # not overridden


def test_load_config_reads_home_env(tmp_path, monkeypatch):
    from twin.config import load_config

    ux.write_env_file(tmp_path / "env", {"TWIN_OLLAMA_URL": "http://wizard:11434"})
    monkeypatch.delenv("TWIN_OLLAMA_URL", raising=False)
    cfg = load_config(tmp_path)
    assert cfg.ollama_url == "http://wizard:11434"


def test_read_key_non_tty(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("a\n"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert ux.read_key(allowed="arsq") == "a"


def test_extract_pending_progress_callback(store, cfg, embedder):
    percepts, _ = sense_paths([EXAMPLES])
    assert len(percepts) >= 2
    for p in percepts[:2]:
        store.insert_percept(p)
    seen: list[tuple[int, int]] = []

    def on_progress(done, total, percept, report):
        seen.append((done, total))

    reports = extract_pending(store, cfg, embedder, on_progress=on_progress)
    assert len(reports) == len(seen) == 2
    assert seen[0] == (1, 2)
    assert seen[1] == (2, 2)


def test_setup_wizard_noninteractive(tmp_path, monkeypatch):
    from twin.config import load_config

    monkeypatch.setenv("TWIN_OLLAMA_URL", "http://127.0.0.1:9")
    cfg = load_config(tmp_path)
    lines = run_setup_wizard(cfg, interactive=False)
    assert any("home=" in line for line in lines)
    assert cfg.home.exists()


def test_brand_and_legend_helpers(capsys):
    assert ux.BRAND == "magenta"
    ux.print_legend([("a", "approve"), ("q", "quit")], title="legend")
    out = capsys.readouterr().out
    assert "approve" in out
    assert "quit" in out
    assert "0.500" in ux.score_bar(0.5)


def test_print_table_renders_headers_and_rows(capsys):
    ux.print_table(["id", "status"], [["c1", "healthy"], ["c2", "paused"]])
    out = capsys.readouterr().out
    assert "id" in out and "status" in out
    assert "c1" in out and "healthy" in out
    assert "c2" in out and "paused" in out


def test_print_table_empty_prints_nothing(capsys):
    ux.print_table(["id"], [])
    assert capsys.readouterr().out == ""


def test_print_next_uses_next_title(capsys):
    ux.print_next([("→", "twin cognize run")])
    out = capsys.readouterr().out
    assert "next" in out
    assert "twin cognize run" in out
