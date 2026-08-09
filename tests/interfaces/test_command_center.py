"""Command Center launch rules."""

from __future__ import annotations

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


def test_fuzzy_palette_prefers_v2_verbs():
    hits = center.fuzzy_palette("cognize")
    assert any("cognize" in h for h in hits)
    legacy = center.fuzzy_palette("meditate")
    assert any("legacy" in h for h in legacy)


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
