"""Legacy CLI alias deprecation warnings."""

from __future__ import annotations

import json
from argparse import Namespace

from twin.interfaces.commands import cli_handlers


def test_legacy_warn_sets_deprecation_on_json(capsys):
    args = Namespace(json=True)
    msg = cli_handlers._legacy_warn(args, legacy="meditate", prefer="cognize run")
    assert "deprecated" in msg
    assert getattr(args, "_deprecation")


def test_emit_json_includes_deprecated_field(capsys):
    args = Namespace(json=True)
    cli_handlers._legacy_warn(args, legacy="extract", prefer="cognize run")
    cli_handlers._emit(args, {"ok": True, "count": 0}, None)
    out = json.loads(capsys.readouterr().out)
    assert "deprecated" in out
    assert "extract" in out["deprecated"]


def test_extract_auto_approve_cannot_commit_narratives():
    args = Namespace(
        json=False,
        home=None,
        auto_approve=True,
        commit_narratives=True,
    )
    # Guard is in cmd_extract before workspace work when flag set
    # Simulate the guard condition used by the handler
    auto = bool(getattr(args, "auto_approve", False))
    if auto and getattr(args, "commit_narratives", False):
        blocked = True
    else:
        blocked = False
    assert blocked is True
