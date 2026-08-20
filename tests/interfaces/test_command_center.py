"""Command Center launch rules."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import twin.interfaces.center as center


def test_non_tty_does_not_launch(monkeypatch):
    monkeypatch.setattr(center, "is_tty", lambda: False)
    assert center.should_launch_center([]) is False
    assert center.should_launch_center(["doctor"]) is False


def test_tty_bare_launches(monkeypatch):
    monkeypatch.setattr(center, "is_tty", lambda: True)
    assert center.should_launch_center([]) is True
    assert center.should_launch_center(["--home", "/tmp/x"]) is True
    assert center.should_launch_center(["doctor"]) is False


def test_cli_non_tty_bare_exits_help(monkeypatch, capsys):
    from twin.interfaces import cli

    monkeypatch.setattr("twin.interfaces.center.is_tty", lambda: False)
    monkeypatch.setattr("twin.interfaces.center.should_launch_center", lambda argv: False)
    try:
        cli.main([])
        assert False, "expected SystemExit"
    except SystemExit as exc:
        assert exc.code == 2
    err = capsys.readouterr().err
    assert "Command Center" in err or "Usage" in err


def test_looks_like_runtime_cmd():
    assert center._looks_like_runtime_cmd(
        'python -c "from twin.interfaces.cli import main; main()" runtime start --no-live'
    )
    assert center._looks_like_runtime_cmd("/usr/bin/twin runtime start")
    assert not center._looks_like_runtime_cmd("python myscript.py start")
    assert not center._looks_like_runtime_cmd("twin serve --port 8765")


def test_ensure_serve_skips_when_port_listening(monkeypatch, tmp_path):
    state = center.CenterState(home=Path(tmp_path))
    monkeypatch.setattr(center, "pids_listening_on", lambda port: [4242])
    started = {"n": 0}

    def boom(*_a, **_k):
        started["n"] += 1
        return "http://should-not"

    monkeypatch.setattr(center, "start_serve", boom)
    url = center.ensure_serve(state, port=8765)
    assert url == "http://127.0.0.1:8765"
    assert started["n"] == 0
    assert state.serve.url == url


def test_ensure_serve_starts_when_down(monkeypatch, tmp_path):
    state = center.CenterState(home=Path(tmp_path))
    monkeypatch.setattr(center, "pids_listening_on", lambda port: [])
    monkeypatch.setattr(
        center, "start_serve", lambda s, port=8765: "http://127.0.0.1:8765"
    )
    assert center.ensure_serve(state) == "http://127.0.0.1:8765"


def test_ensure_runtime_skips_when_external(monkeypatch, tmp_path):
    state = center.CenterState(home=Path(tmp_path))
    monkeypatch.setattr(center, "runtime_pids", lambda: [99])
    started = {"n": 0}

    def boom(*_a, **_k):
        started["n"] += 1
        return "started"

    monkeypatch.setattr(center, "start_runtime", boom)
    assert center.ensure_runtime(state) == "already"
    assert started["n"] == 0


def test_ensure_runtime_starts_when_down(monkeypatch, tmp_path):
    state = center.CenterState(home=Path(tmp_path))
    monkeypatch.setattr(center, "runtime_pids", lambda: [])
    monkeypatch.setattr(center, "start_runtime", lambda s: "started")
    assert center.ensure_runtime(state) == "started"


def test_launch_ensures_services(monkeypatch, tmp_path):
    calls: list[object] = []

    class FakeApp:
        def __init__(self, ws=None, state=None, **_k):
            self.state = state

        def run(self):
            calls.append("run")

    class FakeWs:
        def __init__(self, home=None):
            self.cfg = MagicMock()
            self.cfg.home = str(tmp_path)

    monkeypatch.setattr("twin.workspace.Workspace", FakeWs)
    monkeypatch.setattr(
        "twin.interfaces.center.app.TwinCenterApp", FakeApp
    )

    def ensure(state, port=8765):
        calls.append(("ensure", str(state.home)))
        return {"serve": "ok", "runtime": "ok"}

    monkeypatch.setattr(center, "ensure_all_supervised", ensure)
    code = center.launch_command_center(str(tmp_path))
    assert code == 0
    assert calls[0][0] == "ensure"
    assert "run" in calls
