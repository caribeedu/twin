"""Confidence-aware spontaneous recall (twin.cognition.recall)."""

from twin.cognition.recall import RecallPolicy, apply_recall_policy


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
        policy=RecallPolicy(min_confidence=0.55, min_score=0.25, min_salience=0.35),
        salience_by_id={"mem_strong": 0.7},
        novelty_by_id={"mem_strong": 0.5},
    )
    assert result.silent is False
    assert len(result.suggestions) == 1
    assert result.suggestions[0].memory_id == "mem_strong"
    assert result.suggestions[0].stage == "suggestion"


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
