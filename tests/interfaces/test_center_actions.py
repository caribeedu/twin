"""Command Center actions use shared handlers."""

from __future__ import annotations

from types import SimpleNamespace

from twin.cognize.commit import commit_narrative
from twin.interfaces.center import actions


def test_jobs_enqueue_cognize_batch_not_consolidate(store, cfg, embedder, tmp_path):
    ws = SimpleNamespace(store=store, cfg=cfg, embedder=embedder, home=tmp_path)
    out = actions.enqueue_job(ws, "cognize_batch")
    assert out["ok"] is True
    assert out["kind"] == "cognize_batch"


def test_narrative_list_and_cognize_status(store, cfg, embedder, tmp_path):
    ws = SimpleNamespace(store=store, cfg=cfg, embedder=embedder, home=tmp_path)
    commit_narrative(
        store,
        account="Center lists me",
        vault_id="default",
        evidence_ids=["ev_c1"],
        committed_by="t",
        domain="technical",
    )
    rows = actions.narrative_list(ws)
    assert any(r["account"] == "Center lists me" for r in rows)
    st = actions.cognize_status(ws)
    assert "halted" in st
