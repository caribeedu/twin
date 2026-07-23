"""Golden cognitive work-loop scenario (v0.9.9)."""

from twin.evals.golden import run_golden_work_loop


def test_golden_work_loop(store, cfg, embedder):
    report = run_golden_work_loop(store, cfg, embedder)
    assert report["ok"] is True, report["checks"]
    for key, ok in report["checks"].items():
        assert ok is True, f"check failed: {key}"
