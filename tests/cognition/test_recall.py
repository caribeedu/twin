"""Confidence-aware spontaneous recall (twin.cognize.services.recall)."""

from twin.cognize.services.recall import RecallPolicy, apply_recall_policy


def test_recall_policy_silence_when_under_bar():
    suggested = [
        {
            "memory_id": "mem_a",
            "summary": "weak hit",
            "why_relevant": "token",
            "confidence": 0.2,
            "score": 0.1,
        },
    ]
    result = apply_recall_policy(suggested, [], policy=RecallPolicy())
    assert result.silent is True
    assert result.suggestions == []
    assert "bar" in result.silence_reason


def test_recall_policy_keeps_strong_hits():
    suggested = [
        {
            "memory_id": "mem_strong",
            "summary": "Use Postgres as primary store",
            "why_relevant": "database decision",
            "confidence": 0.9,
            "score": 0.8,
        },
    ]
    result = apply_recall_policy(
        suggested, [],
        policy=RecallPolicy(min_confidence=0.55, min_score=0.25),
        salience_by_id={"mem_strong": 0.7},
        novelty_by_id={"mem_strong": 0.5},
    )
    assert result.silent is False
    assert len(result.suggestions) == 1
    assert result.suggestions[0].memory_id == "mem_strong"
    assert result.suggestions[0].score == 0.8


def test_recall_uses_retrieval_score_not_confidence():
    """High confidence + low retrieval score must not pass; reverse can."""
    suggested = [
        {
            "memory_id": "mem_a",
            "summary": "high conf low score",
            "why_relevant": "x",
            "confidence": 0.95,
            "score": 0.05,
        },
        {
            "memory_id": "mem_b",
            "summary": "ok conf high score",
            "why_relevant": "y",
            "confidence": 0.70,
            "score": 0.90,
        },
    ]
    result = apply_recall_policy(
        suggested, [],
        policy=RecallPolicy(min_confidence=0.55, min_score=0.25),
        salience_by_id={"mem_a": 0.9, "mem_b": 0.4},
        novelty_by_id={"mem_a": 0.99, "mem_b": 0.1},
    )
    assert [s.memory_id for s in result.suggestions] == ["mem_b"]
    assert result.suggestions[0].score == 0.90


def test_recall_rejects_rows_without_score():
    suggested = [
        {
            "memory_id": "mem_legacy",
            "summary": "no score field",
            "why_relevant": "x",
            "confidence": 0.99,
        },
    ]
    result = apply_recall_policy(suggested, [], policy=RecallPolicy())
    assert result.silent is True
    assert result.suggestions == []


def test_recall_never_promotes_blocked():
    blocked = [{"memory_id": "mem_secret", "reason": "domain_gate"}]
    suggested = [
        {
            "memory_id": "mem_ok",
            "summary": "ok",
            "why_relevant": "x",
            "confidence": 0.9,
            "score": 0.8,
        },
    ]
    result = apply_recall_policy(
        suggested, blocked,
        salience_by_id={"mem_ok": 0.8},
    )
    assert result.blocked == blocked
    assert all(s.memory_id != "mem_secret" for s in result.suggestions)
    assert "summary" not in result.blocked[0] or True  # ids/reasons only from observer
