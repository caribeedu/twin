"""Cognitive session lifecycle + projects (twin.cognition.sessions)."""

from pathlib import Path

import pytest

from twin.cognition.sessions import (
    complete_session,
    ensure_project,
    observe_session,
    record_feedback,
    start_session,
)
from twin.memory.models import SessionStatus

EXAMPLES = Path(__file__).parent.parent / "examples"


def test_ensure_project_creates_and_reuses(store):
    project = ensure_project(store, "Atlas", repos=["atlas-api"], aliases=["atlas"])
    assert project.id.startswith("proj_")
    again = ensure_project(store, "Atlas")
    assert again.id == project.id
    assert len(store.list_projects()) == 1


def test_find_project_resolves_alias_and_repo(store):
    project = ensure_project(store, "Atlas Webhooks", repos=["/home/edu/atlas-api"],
                             aliases=["atlas"])
    assert store.find_project("atlas").id == project.id
    assert store.find_project("atlas-api").id == project.id      # repo basename
    assert store.find_project("Atlas Webhooks").id == project.id
    assert store.find_project("unrelated") is None


def test_start_session_records_supplied_context(store, cfg, embedder):
    started = start_session(store, cfg, embedder,
                            "implementar endpoint de webhooks",
                            client="test", domain="technical")
    session = started.session
    assert session.id.startswith("ses_")
    assert session.status == SessionStatus.active
    assert session.domain == "technical"
    assert session.pack_chars == len(started.pack.context_pack)
    assert session.supplied_memory_ids == [s["memory_id"] for s in started.pack.sources]
    assert started.observer_mode in ("fast", "deep")
    assert set(started.reading_confidences) == {"domain", "task_profile", "project"}
    # persisted
    loaded = store.get_session(session.id)
    assert loaded is not None and loaded.initial_query == session.initial_query


def test_start_session_resolves_project_from_cwd(store, cfg, embedder):
    project = ensure_project(store, "Atlas", repos=["atlas-api"])
    started = start_session(store, cfg, embedder, "fix the flaky test",
                            cwd="/home/edu/code/atlas-api")
    assert started.session.project_id == project.id


def test_start_session_explicit_project_wins(store, cfg, embedder):
    ensure_project(store, "Atlas", repos=["atlas-api"])
    other = ensure_project(store, "Beacon")
    started = start_session(store, cfg, embedder, "trabalhar no atlas",
                            project="Beacon")
    assert started.session.project_id == other.id


def test_start_session_infers_task_profile(store, cfg, embedder):
    started = start_session(store, cfg, embedder,
                            "investigate the bug in the payment stacktrace error")
    assert started.session.task_profile == "debugging"


def test_observe_appends_timestamped_artifacts(store, cfg, embedder):
    session = start_session(store, cfg, embedder, "task", domain="technical").session
    observe_session(store, session.id, {"kind": "file", "ref": "api.py"})
    updated = observe_session(store, session.id, {"kind": "commit", "ref": "abc123"})
    assert len(updated.artifacts) == 2
    assert all(a["at"] for a in updated.artifacts)
    assert store.get_session(session.id).artifacts[1]["ref"] == "abc123"


def test_observe_rejects_unknown_and_closed_sessions(store, cfg, embedder):
    with pytest.raises(ValueError, match="not found"):
        observe_session(store, "ses_missing", {"kind": "file"})
    session = start_session(store, cfg, embedder, "task", domain="technical").session
    complete_session(store, cfg, embedder, session.id, abandoned=True)
    with pytest.raises(ValueError, match="not active"):
        observe_session(store, session.id, {"kind": "file"})


def test_complete_session_turns_work_into_candidate_memories(store, cfg, embedder):
    project = ensure_project(store, "Atlas")
    session = start_session(store, cfg, embedder, "escolher fila de mensagens",
                            domain="technical", project="Atlas").session
    observe_session(store, session.id, {"kind": "doc", "note": "TODO: Edu escrever a RFC"})
    done = complete_session(
        store, cfg, embedder, session.id,
        summary="We decided to use RabbitMQ for the webhook queue.",
    )
    assert done.status == SessionStatus.completed
    assert done.ended_at
    assert done.created_memory_ids  # heuristic extractor catches the decision
    # the summary became a percept…
    percepts = [p for p in store.list_percepts() if p.percept_type == "session_summary"]
    assert len(percepts) == 1
    assert percepts[0].source_trust == 0.9
    assert percepts[0].project_id == project.id
    # …and the extracted memories are project-linked candidates
    for mid in done.created_memory_ids:
        mem = store.get_memory(mid)
        assert mem.status.value == "candidate"
        assert mem.project_id == project.id


def test_abandoned_session_creates_nothing(store, cfg, embedder):
    session = start_session(store, cfg, embedder, "task", domain="technical").session
    done = complete_session(store, cfg, embedder, session.id,
                            summary="ignored", abandoned=True)
    assert done.status == SessionStatus.abandoned
    assert done.created_memory_ids == []
    assert store.list_percepts() == []


def test_complete_is_not_reentrant(store, cfg, embedder):
    session = start_session(store, cfg, embedder, "task", domain="technical").session
    complete_session(store, cfg, embedder, session.id)
    with pytest.raises(ValueError, match="not active"):
        complete_session(store, cfg, embedder, session.id)


def test_record_feedback_validates_verdicts(store, cfg, embedder):
    session = start_session(store, cfg, embedder, "task", domain="technical").session
    record_feedback(store, session.id, "useful", note="pack had the decision")
    updated = record_feedback(store, session.id, "missing_context",
                              note="had to re-explain the queue choice")
    assert [fb["verdict"] for fb in updated.feedback] == ["useful", "missing_context"]
    assert all(fb["at"] for fb in updated.feedback)
    with pytest.raises(ValueError):
        record_feedback(store, session.id, "amazing")


def test_feedback_allowed_after_completion(store, cfg, embedder):
    session = start_session(store, cfg, embedder, "task", domain="technical").session
    complete_session(store, cfg, embedder, session.id)
    updated = record_feedback(store, session.id, "useful")
    assert updated.feedback


def test_list_sessions_filters(store, cfg, embedder):
    project = ensure_project(store, "Atlas")
    s1 = start_session(store, cfg, embedder, "a", domain="technical",
                       project="Atlas").session
    start_session(store, cfg, embedder, "b", domain="technical").session
    complete_session(store, cfg, embedder, s1.id)
    assert len(store.list_sessions()) == 2
    assert [s.id for s in store.list_sessions(status="completed")] == [s1.id]
    assert [s.id for s in store.list_sessions(project_id=project.id)] == [s1.id]
