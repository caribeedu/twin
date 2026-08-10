"""Closed cognitive sessions — deltas, checkpoints, closure, pause/reopen."""

from twin.cognize.services.session_lifecycle import (
    append_session_delta,
    archive_session,
    checkpoint_session,
    close_session_structured,
    pause_session,
    reopen_session,
    resume_session,
)
from twin.cognize.services.sessions import start_session
from twin.store.models import SessionStatus


def test_append_delta_ordered_and_gap(store, cfg, embedder):
    started = start_session(store, cfg, embedder, "build runtime", client="cli")
    sid = started.session.id
    e1 = append_session_delta(store, sid, text="step one", sequence=1)
    e3 = append_session_delta(store, sid, text="step three", sequence=3)
    assert e1.sequence == 1
    assert e3.sequence == 3
    events = store.list_session_events(sid)
    kinds = [e.kind for e in events]
    assert "gap" in kinds
    assert any(e.sequence == 3 and e.kind == "delta" for e in events)


def test_checkpoint_and_pause_resume(store, cfg, embedder):
    started = start_session(store, cfg, embedder, "pause me", client="cli")
    sid = started.session.id
    append_session_delta(store, sid, text="a")
    cp = checkpoint_session(store, sid, summary="midway", active_goal="ship")
    assert cp.summary == "midway"
    assert cp.active_goal == "ship"
    paused = pause_session(store, sid)
    assert paused.status == SessionStatus.paused
    # deltas still accepted while paused
    append_session_delta(store, sid, text="while paused")
    resumed = resume_session(store, sid)
    assert resumed.status == SessionStatus.active


def test_structured_close_no_auto_confirm(store, cfg, embedder):
    started = start_session(store, cfg, embedder, "decide API", client="cli")
    sid = started.session.id
    append_session_delta(store, sid, text="chose REST over GraphQL")
    session, closure = close_session_structured(
        store, cfg, embedder, sid,
        summary="picked REST",
        closure={
            "decisions_observed": ["use REST"],
            "rejected_alternatives": ["GraphQL"],
            "open_questions": ["auth scheme?"],
        },
    )
    assert session.status == SessionStatus.completed
    assert closure.provenance["confirms_memory"] is False
    assert closure.provenance["confirms_judgment"] is False
    assert "use REST" in closure.decisions_observed
    assert store.get_session_closure(sid) is not None


def test_reopen_and_archive(store, cfg, embedder):
    started = start_session(store, cfg, embedder, "reopen path", client="cli")
    sid = started.session.id
    close_session_structured(store, cfg, embedder, sid, summary="done")
    reopened = reopen_session(store, sid)
    assert reopened.status == SessionStatus.active
    assert reopened.ended_at in (None, "")
    close_session_structured(store, cfg, embedder, sid, summary="done again")
    archived = archive_session(store, sid)
    assert archived.status == SessionStatus.archived


def test_cross_tool_external_session_ids(store, cfg, embedder):
    started = start_session(store, cfg, embedder, "multi tool", client="cli")
    sid = started.session.id
    append_session_delta(
        store, sid, text="from cursor", external_session_id="cursor-1",
        client="cursor",
    )
    append_session_delta(
        store, sid, text="from claude", external_session_id="claude-1",
        client="claude-code",
    )
    events = store.list_session_events(sid)
    ext = {e.external_session_id for e in events if e.external_session_id}
    assert ext == {"cursor-1", "claude-1"}
