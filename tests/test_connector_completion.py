"""Behavioural tests for twin.connectors.completion."""

from __future__ import annotations

import pytest

from twin.connectors.completion import (
    check_criterion,
    completion_matrix,
)


def test_pass_cells_require_evidence_pointer():
    matrix = completion_matrix()
    assert "criteria" in matrix
    for row in matrix["criteria"]:
        assert row["status"] in (
            "pass", "fail", "not_tested", "partial", "not_applicable",
        )
        if row["status"] == "pass":
            assert row["evidence"] or row["eval"], row


def test_pass_without_evidence_demoted_to_not_tested(monkeypatch):
    from twin.connectors import completion as mod

    broken = [dict(c) for c in mod.CRITERIA]
    broken[0] = {
        **broken[0],
        "status": "pass",
        "evidence": None,
        "eval": None,
    }
    monkeypatch.setattr(mod, "CRITERIA", broken)
    matrix = mod.completion_matrix()
    assert matrix["criteria"][0]["status"] == "not_tested"
    assert matrix["ok"] is False


def test_check_criterion_unknown_id_raises():
    with pytest.raises(ValueError, match="unknown criterion"):
        check_criterion(9999)


def test_failed_or_not_tested_makes_matrix_not_ok(monkeypatch):
    from twin.connectors import completion as mod

    broken = [dict(c) for c in mod.CRITERIA]
    broken[0] = {**broken[0], "status": "fail", "evidence": "x"}
    monkeypatch.setattr(mod, "CRITERIA", broken)
    assert mod.completion_matrix()["ok"] is False
