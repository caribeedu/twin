"""Removed argv surfaces must not register."""

from __future__ import annotations

import pytest

from twin.interfaces import cli


@pytest.mark.parametrize(
    "argv",
    [
        ("extract",),
        ("meditate",),
        ("correlate",),
        ("judgment", "list"),
        ("claim", "unsupported"),
    ],
)
def test_removed_argv_rejected(tmp_path, argv):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--home", str(tmp_path / "home"), *argv])
    assert exc.value.code != 0
