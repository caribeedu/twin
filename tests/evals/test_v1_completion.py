"""v1 cognitive OS completion matrix — fail closed."""

from twin.evals.v1_completion import CRITERIA, v1_completion_matrix


def test_v1_completion_matrix_ok():
    matrix = v1_completion_matrix()
    assert matrix["ok"] is True, matrix["failed"]
    assert matrix["failed"] == []


def test_pass_without_evidence_demoted(monkeypatch):
    from twin.evals import v1_completion as mod

    broken = [dict(c) for c in CRITERIA]
    broken[0] = {**broken[0], "status": "pass", "evidence": None, "eval": None}
    monkeypatch.setattr(mod, "CRITERIA", broken)
    matrix = mod.v1_completion_matrix()
    assert matrix["criteria"][0]["status"] == "not_tested"
    assert matrix["ok"] is False
