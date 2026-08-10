"""Cognitive session lifecycle + projects (twin.cognition.sessions)."""

from pathlib import Path

from tests.paths import EXAMPLES

import pytest

from twin.cognition.sessions import (
    abandon_stale_sessions,
    complete_session,
    ensure_project,
    observe_session,
    record_feedback,
    stale_sessions,
    start_session,
)
from twin.store.models import ConsolidationStatus, SessionStatus

def test_ensure_project_creates_and_reuses(store):
    project = ensure_project(store, "Atlas", repos=["atlas-api"], aliases=["atlas"])
    assert project.id.startswith("proj_")
    again = ensure_project(store, "Atlas")
    assert again.id == project.id
    assert len(store.list_projects()) == 1


def test_ensure_project_merges_new_signals(store):
    """Re-declaring a project with more repos/aliases enriches it — new
    signals are never silently discarded."""
    project = ensure_project(store, "Atlas", repos=["atlas-api"])
    merged = ensure_project(store, "Atlas", repos=["atlas-web", "ATLAS-API"],
                            aliases=["atl", "Atlas"])
    assert merged.id == project.id
    assert merged.repos == ["atlas-api", "atlas-web"]  # case-insensitive dedup
    assert merged.aliases == ["atl"]  # alias equal to the name is redundant
    # persisted, and the new repo resolves the project
    assert store.find_project("atlas-web").id == project.id


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
                            client="cli", domain="technical")
    session = started.session
    assert session.id.startswith("ses_")
    assert session.status == SessionStatus.active
    assert session.domain == "technical"
    assert session.consolidation_status == ConsolidationStatus.none
    assert session.pack_chars == len(started.pack.context_pack)
    assert session.supplied_memory_ids == [s["memory_id"] for s in started.pack.sources]
    assert started.observer_mode in (
        "fast", "deep", "unresolved", "explicit", "search", "frozen",
    )
    assert not started.needs_domain_confirmation
    assert set(started.reading_confidences) == {"domain", "task_profile", "project"}
    # persisted
    loaded = store.get_session(session.id)
    assert loaded is not None and loaded.initial_query == session.initial_query
    assert loaded.last_activity_at


def test_start_session_unclassified_is_default_deny(store, cfg, embedder):
    """No domain evidence + no explicit domain → the session opens
    unclassified with an EMPTY pack: no memories, no judgment profile."""
    from twin import ids
    from twin.store.models import MemoryItem

    mem = MemoryItem(id=ids.memory_id(), type="fact", title="Webhook stack",
                     summary="Webhooks run on FastAPI.", domain="technical",
                     confidence=0.9, status="confirmed")
    store.insert_memory(mem)
    store.store_embedding(mem.id, "memory", embedder.name,
                          embedder.embed("Webhook stack\nWebhooks run on FastAPI."))

    started = start_session(store, cfg, embedder,
                            "aquilo de ontem, resolve pra mim", client="cli")
    assert started.session.domain == "unclassified"
    assert started.needs_domain_confirmation
    assert started.pack.sources == []
    # Scope header may appear; memories and judgment stay out until domain freezes.
    assert "webhook" not in (started.pack.context_pack or "").lower()
    assert "## Judgment" not in (started.pack.context_pack or "")
    # explicit domain resolves it
    confirmed = start_session(store, cfg, embedder,
                              "aquilo de ontem, resolve pra mim",
                              domain="technical", client="cli")
    assert not confirmed.needs_domain_confirmation


def test_start_session_resolves_project_from_cwd(store, cfg, embedder):
    """cwd basename matching a known project binds it without LLM."""
    project = ensure_project(store, "Atlas", repos=["atlas-api"])
    started = start_session(store, cfg, embedder, "fix the flaky test",
                            cwd="/home/edu/code/atlas-api", client="cli")
    assert started.session.project_id == project.id
    # Domain may still be unclassified (search vote needs confirmed memories);
    # project binding is independent of that.
    assert started.session.domain == "unclassified" or started.session.domain == "technical"



def test_start_session_explicit_project_wins(store, cfg, embedder):
    ensure_project(store, "Atlas", repos=["atlas-api"])
    other = ensure_project(store, "Beacon")
    started = start_session(store, cfg, embedder, "trabalhar no atlas",
                            project="Beacon", cwd="/repos/atlas-api", client="cli")
    assert started.session.project_id == other.id


def test_start_session_unknown_explicit_project_raises(store, cfg, embedder):
    """A misspelled explicit project must fail loudly — never fall back to
    the project inferred from cwd or mentions."""
    ensure_project(store, "Atlas", repos=["atlas-api"])
    with pytest.raises(ValueError, match="'payments' not found"):
        start_session(store, cfg, embedder, "task no atlas",
                      project="payments", cwd="/repos/atlas-api", client="cli")
    # nothing was persisted for the failed start
    assert store.list_sessions() == []


def test_start_session_explicit_alias_resolves(store, cfg, embedder):
    project = ensure_project(store, "Atlas Webhooks", aliases=["atlas"])
    started = start_session(store, cfg, embedder, "task", project="atlas",
                            domain="technical", client="cli")
    assert started.session.project_id == project.id


def test_start_session_infers_task_profile(store, cfg, embedder, monkeypatch):
    from twin.cognition.observer import ObserverReading

    monkeypatch.setattr(
        "twin.cognition.sessions.resolve_context_domain",
        lambda *_a, **_k: ObserverReading(
            domain="technical", task_profile="debugging",
            confidences={"domain": 0.9, "task_profile": 0.9, "project": 0.0},
            mode="deep",
        ),
    )
    started = start_session(store, cfg, embedder,
                            "investigate the bug in the payment stacktrace error", client="cli")
    assert started.session.task_profile == "debugging"


def test_observe_appends_timestamped_artifacts(store, cfg, embedder):
    session = start_session(store, cfg, embedder, "task", domain="technical", client="cli").session
    observe_session(store, session.id, {"kind": "file", "ref": "api.py"})
    updated = observe_session(store, session.id, {"kind": "commit", "ref": "abc123"})
    assert len(updated.artifacts) == 2
    assert all(a["at"] for a in updated.artifacts)
    assert store.get_session(session.id).artifacts[1]["ref"] == "abc123"


def test_observe_is_append_only_no_lost_updates(store, cfg, embedder):
    """Two clients holding stale copies of the session cannot erase each
    other's artifacts — the classic read-modify-write race is structurally
    impossible because artifacts are appended rows, not a rewritten array."""
    session = start_session(store, cfg, embedder, "task", domain="technical", client="cli").session
    # both "clients" read the session before either writes
    stale_a = store.get_session(session.id)
    stale_b = store.get_session(session.id)
    assert stale_a.artifacts == [] and stale_b.artifacts == []
    observe_session(store, stale_a.id, {"kind": "file", "ref": "a.py"})
    observe_session(store, stale_b.id, {"kind": "file", "ref": "b.py"})
    # a scalar update from a stale copy doesn't touch artifacts either
    store.update_session(stale_b)
    refs = {a["ref"] for a in store.get_session(session.id).artifacts}
    assert refs == {"a.py", "b.py"}


def test_feedback_is_append_only_no_lost_updates(store, cfg, embedder):
    session = start_session(store, cfg, embedder, "task", domain="technical", client="cli").session
    stale_a = store.get_session(session.id)
    stale_b = store.get_session(session.id)
    record_feedback(store, stale_a.id, "useful")
    record_feedback(store, stale_b.id, "missing_context")
    verdicts = [fb["verdict"] for fb in store.get_session(session.id).feedback]
    assert sorted(verdicts) == ["missing_context", "useful"]


def test_observe_rejects_unknown_and_closed_sessions(store, cfg, embedder):
    with pytest.raises(ValueError, match="not found"):
        observe_session(store, "ses_missing", {"kind": "file"})
    session = start_session(store, cfg, embedder, "task", domain="technical", client="cli").session
    complete_session(store, cfg, embedder, session.id, abandoned=True)
    with pytest.raises(ValueError, match="not active"):
        observe_session(store, session.id, {"kind": "file"})
    with pytest.raises(ValueError, match="kind"):
        observe_session(store, session.id, {"ref": "x"})


def test_complete_session_turns_work_into_candidate_memories(store, cfg, embedder):
    project = ensure_project(store, "Atlas")
    session = start_session(store, cfg, embedder, "escolher fila de mensagens",
                            domain="technical", project="Atlas", client="cli").session
    observe_session(store, session.id, {
        "kind": "user_message",
        "note": "TODO: Edu escrever a RFC",
    })
    done = complete_session(
        store, cfg, embedder, session.id,
        summary="We decided to use RabbitMQ for the webhook queue.",
        summary_origin="user",
    )
    assert done.status == SessionStatus.completed
    assert done.consolidation_status == ConsolidationStatus.completed
    assert done.ended_at
    assert done.created_memory_ids  # heuristic extractor catches the decision
    # the summary became a percept…
    percepts = [p for p in store.list_percepts() if p.percept_type == "session_summary"]
    assert len(percepts) == 1
    assert percepts[0].source_trust == 0.9  # user-authored summary
    assert percepts[0].project_id == project.id
    assert done.summary_percept_id == percepts[0].id
    # …and the extracted memories are project-linked candidates
    for mid in done.created_memory_ids:
        mem = store.get_memory(mid)
        assert mem.status.value == "candidate"
        assert mem.project_id == project.id


def test_session_summary_excludes_tool_io(store, cfg, embedder):
    """Tool I/O stays on the session; percept is user/assistant dialogue only."""
    session = start_session(
        store, cfg, embedder, "task", domain="technical", client="cli",
    ).session
    observe_session(store, session.id, {
        "kind": "user_message", "note": "i finished watching dexter",
    })
    observe_session(store, session.id, {
        "kind": "tool_requested",
        "note": 'Bash: {"command": "grep -ril atlas /tmp"}',
    })
    observe_session(store, session.id, {
        "kind": "tool_completed",
        "note": 'Bash: {"stdout": "huge atlas dump..."}',
    })
    observe_session(store, session.id, {
        "kind": "assistant_result",
        "note": "Nice — how'd Dexter's ending land for you?",
    })
    observe_session(store, session.id, {
        "kind": "session_start", "note": "native host session",
    })
    done = complete_session(
        store, cfg, embedder, session.id, summary="prompt_input_exit",
    )
    assert done.consolidation_status == ConsolidationStatus.completed
    percept = store.get_percept(done.summary_percept_id)
    assert percept is not None
    assert "dexter" in percept.content.lower()
    assert "Dexter's ending" in percept.content
    # human speaker labels — not machine kind tags that leak into evidence
    assert "[user_message]" not in percept.content
    assert "[assistant_result]" not in percept.content
    assert "User:" in percept.content
    assert "Assistant:" in percept.content
    assert "tool_requested" not in percept.content
    assert "tool_completed" not in percept.content
    assert "grep -ril" not in percept.content
    assert "native host session" not in percept.content
    assert "prompt_input_exit" not in percept.content
    # tools still on the session for replay
    kinds = {a.get("kind") for a in store.get_session(session.id).artifacts}
    assert "tool_requested" in kinds and "tool_completed" in kinds


def test_session_summary_folds_cli_observations(store, cfg, embedder):
    """Deliberate human/CLI observations (twin session observe) belong in the
    summary — only tool I/O and session boilerplate are held back."""
    session = start_session(
        store, cfg, embedder, "task", domain="technical", client="cli",
    ).session
    observe_session(store, session.id, {
        "kind": "note", "note": "Decided to use RabbitMQ for the queue.",
    })
    observe_session(store, session.id, {
        "kind": "commit", "ref": "abc123", "note": "wire up the consumer",
    })
    observe_session(store, session.id, {
        "kind": "tool_completed", "note": 'Bash: {"stdout": "noise"}',
    })
    done = complete_session(store, cfg, embedder, session.id)
    assert done.consolidation_status == ConsolidationStatus.completed
    percept = store.get_percept(done.summary_percept_id)
    assert percept is not None
    assert "RabbitMQ" in percept.content
    assert "wire up the consumer" in percept.content
    assert "noise" not in percept.content


def test_summary_trust_depends_on_origin(store, cfg, embedder):
    """An LLM's unconfirmed account of its own work is NOT a high-trust
    first-person record."""
    def complete_with(origin, confirmed=False):
        ses = start_session(store, cfg, embedder, "task", domain="technical", client="cli").session
        complete_session(store, cfg, embedder, ses.id,
                         summary=f"We decided to use RabbitMQ ({origin}).",
                         summary_origin=origin, user_confirmed=confirmed)
        [p] = [p for p in store.list_percepts()
               if p.percept_type == "session_summary"
               and p.content_refs[0]["session_id"] == ses.id]
        return p

    assert complete_with("user").source_trust == 0.9
    assert complete_with("derived").source_trust == 0.85
    assert complete_with("client").source_trust == 0.7
    assistant = complete_with("assistant")
    assert assistant.source_trust == 0.6
    assert assistant.metadata["summary_origin"] == "assistant"
    # explicit human confirmation upgrades any origin
    assert complete_with("assistant", confirmed=True).source_trust == 0.9

    ses = start_session(store, cfg, embedder, "task", domain="technical", client="cli").session
    with pytest.raises(ValueError, match="summary_origin"):
        complete_session(store, cfg, embedder, ses.id, summary="x",
                         summary_origin="oracle")


def test_consolidation_failure_is_diagnosable_and_retryable(store, cfg, embedder, monkeypatch):
    """Extraction failure must not lose the session or hide the error; the
    retry consolidates without duplicating percepts or memories."""
    session = start_session(store, cfg, embedder, "task", domain="technical", client="cli").session

    import twin.cognition.sessions as sessions_mod

    def boom(*args, **kwargs):
        raise RuntimeError("extractor exploded")

    monkeypatch.setattr(sessions_mod, "extract_percept", boom)
    done = complete_session(store, cfg, embedder, session.id,
                            summary="We decided to use RabbitMQ for the queue.")
    assert done.status == SessionStatus.completed          # the work DID end
    assert done.consolidation_status == ConsolidationStatus.failed
    assert "RuntimeError" in done.consolidation_error
    assert done.created_memory_ids == []

    # retry with the extractor healthy again
    monkeypatch.undo()
    retried = complete_session(store, cfg, embedder, session.id,
                               summary="We decided to use RabbitMQ for the queue.")
    assert retried.consolidation_status == ConsolidationStatus.completed
    assert retried.consolidation_error is None
    assert retried.created_memory_ids
    # exactly one summary percept exists despite two attempts
    summaries = [p for p in store.list_percepts() if p.percept_type == "session_summary"]
    assert len(summaries) == 1

    # a consolidated session cannot be completed again
    with pytest.raises(ValueError, match="not completable"):
        complete_session(store, cfg, embedder, session.id, summary="again")


def test_completed_consolidation_is_idempotent_on_memories(store, cfg, embedder, monkeypatch):
    """Even if consolidation runs twice (retry after a late failure), the
    dedup key prevents duplicate memories."""
    session = start_session(store, cfg, embedder, "task", domain="technical", client="cli").session

    import twin.cognition.sessions as sessions_mod
    real_extract = sessions_mod.extract_percept
    calls = {"n": 0}

    def fail_after_extract(*args, **kwargs):
        report = real_extract(*args, **kwargs)
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("crashed after extraction")
        return report

    monkeypatch.setattr(sessions_mod, "extract_percept", fail_after_extract)
    done = complete_session(store, cfg, embedder, session.id,
                            summary="We decided to use RabbitMQ for the queue.")
    assert done.consolidation_status == ConsolidationStatus.failed

    retried = complete_session(store, cfg, embedder, session.id,
                               summary="We decided to use RabbitMQ for the queue.")
    assert retried.consolidation_status == ConsolidationStatus.completed
    # extraction dedupe: the same percept content yields no second memory
    titles = [store.get_memory(m).title for m in retried.created_memory_ids]
    assert len(titles) == len(set(titles))
    summaries = [p for p in store.list_percepts() if p.percept_type == "session_summary"]
    assert len(summaries) == 1


def test_abandoned_session_creates_nothing(store, cfg, embedder):
    session = start_session(store, cfg, embedder, "task", domain="technical", client="cli").session
    done = complete_session(store, cfg, embedder, session.id,
                            summary="ignored", abandoned=True)
    assert done.status == SessionStatus.abandoned
    assert done.consolidation_status == ConsolidationStatus.skipped
    assert done.created_memory_ids == []
    assert store.list_percepts() == []


def test_complete_without_material_skips_consolidation(store, cfg, embedder):
    session = start_session(store, cfg, embedder, "task", domain="technical", client="cli").session
    done = complete_session(store, cfg, embedder, session.id)
    assert done.status == SessionStatus.completed
    assert done.consolidation_status == ConsolidationStatus.skipped
    assert store.list_percepts() == []


def test_percept_backed_artifacts_are_not_duplicated_as_text(store, cfg, embedder):
    """An artifact that references an ingested percept must not have its
    note re-extracted — the percept is the source of truth."""
    session = start_session(store, cfg, embedder, "task", domain="technical", client="cli").session
    observe_session(store, session.id, {
        "kind": "commit", "ref": "abc123", "percept_id": "pct_existing",
        "note": "We decided to use RabbitMQ for the queue.",
    })
    done = complete_session(store, cfg, embedder, session.id)
    # only the percept-backed artifact existed → nothing to consolidate
    assert done.consolidation_status == ConsolidationStatus.skipped
    assert [p for p in store.list_percepts()
            if p.percept_type == "session_summary"] == []


def test_complete_is_not_reentrant(store, cfg, embedder):
    session = start_session(store, cfg, embedder, "task", domain="technical", client="cli").session
    complete_session(store, cfg, embedder, session.id)
    with pytest.raises(ValueError, match="not completable"):
        complete_session(store, cfg, embedder, session.id)


def test_record_feedback_validates_verdicts_and_scopes(store, cfg, embedder):
    session = start_session(store, cfg, embedder, "task", domain="technical", client="cli").session
    record_feedback(store, session.id, "useful", note="pack had the decision")
    updated = record_feedback(store, session.id, "missing_context",
                              note="had to re-explain the queue choice",
                              scope="pack")
    assert [fb["verdict"] for fb in updated.feedback] == ["useful", "missing_context"]
    assert [fb["scope"] for fb in updated.feedback] == ["session", "pack"]
    assert all(fb["at"] for fb in updated.feedback)
    with pytest.raises(ValueError):
        record_feedback(store, session.id, "amazing")
    with pytest.raises(ValueError, match="scope"):
        record_feedback(store, session.id, "useful", scope="universe")
    with pytest.raises(ValueError, match="memory_id"):
        record_feedback(store, session.id, "useful", scope="memory")


def test_feedback_memory_must_belong_to_the_session(store, cfg, embedder):
    from twin import ids
    from twin.store.models import MemoryItem

    supplied = MemoryItem(id=ids.memory_id(), type="decision",
                          title="Use FastAPI", summary="Decision: FastAPI.",
                          domain="technical", confidence=0.9, status="confirmed")
    store.insert_memory(supplied)
    store.store_embedding(supplied.id, "memory", embedder.name,
                          embedder.embed("Use FastAPI Decision FastAPI webhooks"))
    foreign = MemoryItem(id=ids.memory_id(), type="fact", title="Unrelated",
                         summary="Not in this session.", domain="technical",
                         confidence=0.9, status="confirmed")
    store.insert_memory(foreign)

    session = start_session(store, cfg, embedder, "FastAPI webhooks decision",
                            domain="technical", client="cli").session
    assert supplied.id in session.supplied_memory_ids

    updated = record_feedback(store, session.id, "useful", memory_id=supplied.id)
    assert updated.feedback[0]["scope"] == "memory"
    with pytest.raises(ValueError, match="not found"):
        record_feedback(store, session.id, "useful", memory_id="mem_ghost")
    with pytest.raises(ValueError, match="was not supplied"):
        record_feedback(store, session.id, "useful", memory_id=foreign.id)


def test_feedback_allowed_after_completion(store, cfg, embedder):
    session = start_session(store, cfg, embedder, "task", domain="technical", client="cli").session
    complete_session(store, cfg, embedder, session.id)
    updated = record_feedback(store, session.id, "useful")
    assert updated.feedback


def test_list_sessions_filters(store, cfg, embedder):
    project = ensure_project(store, "Atlas")
    s1 = start_session(store, cfg, embedder, "a", domain="technical",
                       project="Atlas", client="cli").session
    start_session(store, cfg, embedder, "b", domain="technical", client="cli").session
    complete_session(store, cfg, embedder, s1.id)
    assert len(store.list_sessions()) == 2
    assert [s.id for s in store.list_sessions(status="completed")] == [s1.id]
    assert [s.id for s in store.list_sessions(project_id=project.id)] == [s1.id]


def test_stale_sessions_cleanup(store, cfg, embedder):
    fresh = start_session(store, cfg, embedder, "a", domain="technical", client="cli").session
    old = start_session(store, cfg, embedder, "b", domain="technical", client="cli").session
    # simulate a session idle since long ago
    stored = store.get_session(old.id)
    stored.last_activity_at = "2020-01-01T00:00:00+00:00"
    store.update_session(stored)

    assert [s.id for s in stale_sessions(store, max_idle_hours=1.0)] == [old.id]
    abandoned = abandon_stale_sessions(store, max_idle_hours=1.0)
    assert abandoned == [old.id]
    assert store.get_session(old.id).status == SessionStatus.abandoned
    assert store.get_session(fresh.id).status == SessionStatus.active
    # idempotent
    assert abandon_stale_sessions(store, max_idle_hours=1.0) == []
