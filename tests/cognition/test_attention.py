"""Continuous attention — silence default, cooldown, delta enqueue."""

from twin.cognize.services.attention import (
    AttentionKind,
    AttentionPolicy,
    evaluate_attention,
    expected_value,
    feedback_attention,
    working_memory_text,
)
from twin.cognize.services.session_lifecycle import append_session_delta, checkpoint_session
from twin.cognize.services.sessions import start_session
from twin.interfaces.runtime.models import JobKind


def test_expected_value_prefers_silence_on_low_signal():
    ev = expected_value(
        relevance=0.2, confidence=0.5, timeliness=0.5, actionability=0.5,
        interruption_cost=0.2, privacy_risk=0.0, repetition_penalty=0.0,
    )
    assert ev < 0.45


def test_working_memory_from_checkpoint_and_deltas(store, cfg, embedder):
    started = start_session(store, cfg, embedder, "ship attention", client="cli")
    sid = started.session.id
    append_session_delta(store, sid, text="first delta about SQLite")
    checkpoint_session(store, sid, summary="midway", active_goal="ship")
    append_session_delta(store, sid, text="second delta about workers")
    text = working_memory_text(store, sid)
    assert "midway" in text
    assert "second delta" in text


def test_evaluate_attention_can_be_silent(store, cfg, embedder):
    started = start_session(store, cfg, embedder, "quiet work", client="cli")
    sid = started.session.id
    append_session_delta(store, sid, text="typing boilerplate")
    # Force low threshold gates via empty memory store → silence
    outcomes = evaluate_attention(
        store, cfg, embedder, sid,
        policy=AttentionPolicy(interrupt_threshold=0.99, cooldown_seconds=0),
    )
    assert outcomes
    assert outcomes[0].kind == AttentionKind.silence


def test_delta_enqueues_attention_job(store, cfg, embedder):
    started = start_session(store, cfg, embedder, "enqueue path", client="cli")
    sid = started.session.id
    append_session_delta(store, sid, text="decision: use durable queue")
    jobs = store.list_runtime_jobs(kind=JobKind.attention_evaluate.value, limit=10)
    assert jobs
    assert jobs[0].payload.get("session_id") == sid


def test_feedback_suppresses_emission(store, cfg, embedder):
    from twin.cognize.services.attention import AttentionOutcome

    started = start_session(store, cfg, embedder, "feedback path", client="cli")
    sid = started.session.id
    em = AttentionOutcome(
        session_id=sid,
        kind=AttentionKind.suggestion,
        memory_id="mem_x",
        summary="hint",
        expected_value=0.8,
        status="open",
    )
    store.insert_attention_emission(em)
    out = feedback_attention(store, em.id, verdict="irrelevant")
    assert out is not None
    assert out.status == "suppressed"
    assert store.is_attention_suppressed(sid, kind="suggestion", memory_id="mem_x")
