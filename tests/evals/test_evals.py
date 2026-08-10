"""Evaluation runners (twin.evals) — isolated stores, never production."""

from twin.evals import default_eval_root, run_extraction_eval, run_retrieval_eval


def test_evals_isolated_and_reject_empty_retrieval(store, cfg, embedder, tmp_path):
    before = len(store.list_claims(limit=1000))
    run = run_extraction_eval(store, cfg, embedder, default_eval_root() / "extraction")
    assert len(store.list_claims(limit=1000)) == before
    assert run.summary.get("status") == "implemented"

    bad = tmp_path / "retrieval"
    bad.mkdir()
    (bad / "empty.json").write_text(
        '{"id":"empty","query":"x","expected_claim_ids":[]}', encoding="utf-8",
    )
    run2 = run_retrieval_eval(store, embedder, bad)
    assert run2.cases
    assert run2.cases[0].passed is False

    run3 = run_retrieval_eval(store, embedder, default_eval_root() / "retrieval", cfg=cfg)
    assert len(store.list_claims(limit=1000)) == before
    assert run3.summary.get("status") == "implemented"
