"""Excerpt + divergence helpers for episode briefs."""

from twin.cognition.correlation.text import (
    normalize_for_compare,
    rich_excerpt,
    texts_diverge,
)


def test_rich_excerpt_keeps_body_drops_boilerplate():
    raw = (
        "GitHub pull request caribeedu/twin#22: Implement v0.8 parallel memory.\n"
        "state: MERGED · merged at 2026-07-23\n"
        "This is the FINAL, merged state of the change.\n"
        "Add workspace ticks with confidence-aware recall."
    )
    out = rich_excerpt(raw)
    assert "workspace ticks" in out
    assert "Implement v0.8" in out
    assert "MERGED" not in out
    assert "FINAL, merged state" not in out


def test_texts_diverge_near_duplicate_false():
    assert not texts_diverge("Implement the queue", "Implement the queue")
    assert not texts_diverge(
        "Implement parallel memory spine",
        "Implement parallel memory spine for twin",
    )


def test_texts_diverge_intent_shift_true():
    a = "Implement v0.8 parallel memory and consolidation spine with workspace ticks"
    b = "Address PR blockers: retrieval score and operational idempotency"
    assert texts_diverge(a, b)


def test_normalize_strips_commit_prefix():
    raw = "Commit abcdef12 in caribeedu/twin by Edu: Ship the thing"
    assert "ship the thing" in normalize_for_compare(raw)
    assert "commit" not in normalize_for_compare(raw)
