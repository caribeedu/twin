"""Workspace evaluation tick (twin.cognize.services.workspace)."""

from dataclasses import dataclass, field

import pytest

from twin import ids
from twin.cognize.services import set_interpreter_override
from twin.cognize.services.interpreter.schema import (
    CognitiveAct,
    InterpretationResult,
    InterpretationStatus,
    InterpretedItem,
)
from twin.cognize.services.observer import ObserverReading, ObserverSuggestion
from twin.cognize.services.salience import SalienceScores
from twin.cognize.services.workspace import workspace_tick
from twin.store.models import MemoryItem, MemoryStatus


def _mem(store, embedder, **kw):
    base = dict(
        id=ids.memory_id(), type="decision",
        title="Postgres primary",
        summary="Use Postgres as the primary database for Twin.",
        domain="technical", confidence=0.92, status="confirmed",
        entities=["Postgres", "Twin"],
    )
    base.update(kw)
    mem = MemoryItem(**base)
    store.insert_memory(mem)
    store.store_embedding(
        mem.id, "memory", embedder.name,
        embedder.embed(f"{mem.title}\n{mem.summary}"),
    )
    return mem


def test_workspace_tick_stages_and_silent_default(store, cfg, embedder):
    result = workspace_tick(store, cfg, embedder, "hmm ok", interpret=False)
    assert "reading" in result.stages
    assert "recall" in result.stages
    assert result.stages[-1] == "done"
    assert result.silent is True
    assert result.suggestions == []
    assert result.candidate_memory_ids == []
    assert result.tick_id


def test_workspace_tick_suggests_high_confidence_memory(store, cfg, embedder):
    mem = _mem(store, embedder)
    result = workspace_tick(
        store, cfg, embedder,
        "database architecture deploy postgres primary store",
        target_domain="technical",
        interpret=False,
    )
    ids_out = {s["memory_id"] for s in result.suggestions}
    assert result.silent is False
    assert mem.id in ids_out
    hit = next(s for s in result.suggestions if s["memory_id"] == mem.id)
    assert hit["stage"] == "suggestion"
    assert hit["confidence"] >= 0.55
    assert hit["score"] >= 0.25
    assert result.candidate_memory_ids == []


def test_workspace_recall_uses_retrieval_score_not_memory_confidence(
    store, cfg, embedder, monkeypatch,
):
    @dataclass
    class _Reading:
        domain: str = "technical"
        task_profile: str = "general"
        project_id: str | None = None
        confidences: dict = field(default_factory=lambda: {
            "domain": 1.0, "task_profile": 1.0, "project": 0.0,
        })
        uncertain: bool = False
        mode: str = "fast"

        @property
        def needs_domain_confirmation(self) -> bool:
            return self.domain == "unclassified"

    def fake_observe(*_a, **_k):
        return ObserverSuggestion(
            suggested_context=[
                {
                    "memory_id": "mem_a",
                    "summary": "high conf low score",
                    "why_relevant": "x",
                    "confidence": 0.95,
                    "score": 0.05,
                    "allowed": True,
                },
                {
                    "memory_id": "mem_b",
                    "summary": "ok conf high score",
                    "why_relevant": "y",
                    "confidence": 0.70,
                    "score": 0.90,
                    "allowed": True,
                },
            ],
            blocked_context=[],
            inferred_domain="technical",
        )

    monkeypatch.setattr("twin.cognize.services.workspace.read_context", lambda *_a, **_k: _Reading())
    monkeypatch.setattr("twin.cognize.services.workspace.observe", fake_observe)
    monkeypatch.setattr(
        "twin.cognize.services.workspace.score_memories",
        lambda *_a, **_k: SalienceScores(
            by_memory={"mem_a": 0.9, "mem_b": 0.4},
            novelty={"mem_a": 0.99, "mem_b": 0.1},
            contradiction_ids=[],
        ),
    )

    result = workspace_tick(store, cfg, embedder, "anything", target_domain="technical")
    assert [s["memory_id"] for s in result.suggestions] == ["mem_b"]
    assert result.suggestions[0]["score"] == 0.90
    assert result.suggestions[0]["confidence"] == 0.70


def test_observe_score_reaches_recall_item(store, cfg, embedder, monkeypatch):
    monkeypatch.setattr(
        "twin.cognize.services.workspace.read_context",
        lambda *_a, **_k: ObserverReading(
            domain="technical", task_profile="coding",
            confidences={"domain": 1.0, "task_profile": 1.0, "project": 0.0},
        ),
    )
    monkeypatch.setattr(
        "twin.cognize.services.workspace.observe",
        lambda *_a, **_k: ObserverSuggestion(
            suggested_context=[{
                "memory_id": "mem_x",
                "summary": "s",
                "why_relevant": "w",
                "confidence": 0.8,
                "score": 0.42,
                "allowed": True,
            }],
            blocked_context=[],
            inferred_domain="technical",
        ),
    )
    monkeypatch.setattr(
        "twin.cognize.services.workspace.score_memories",
        lambda *_a, **_k: SalienceScores(
            by_memory={"mem_x": 0.5}, novelty={"mem_x": 0.2}, contradiction_ids=[],
        ),
    )
    result = workspace_tick(store, cfg, embedder, "q", target_domain="technical")
    assert result.suggestions[0]["score"] == 0.42


def test_workspace_tick_interpret_creates_candidates_only(store, cfg, embedder):
    cfg.extractor = "auto"
    span = "We decided to use FastAPI for the Twin HTTP API."

    def scripted(percept, text, cfg):
        return InterpretationResult(
            items=[InterpretedItem(
                memory_type="decision",
                title="Use FastAPI",
                summary=span,
                domain="technical",
                cognitive_act=CognitiveAct.decision,
                evidence_span=span,
                attributed_to="user",
            )],
            status=InterpretationStatus.interpreted,
            interpreter="scripted", model="scripted",
            prompt_version="test", schema_version="1",
        )

    set_interpreter_override(scripted)
    result = workspace_tick(
        store, cfg, embedder, span,
        target_domain="technical",
        interpret=True,
        input_mode="delta",
        session_id="ses_test",
        sequence=1,
    )
    assert "parallel_interpretation" in result.stages
    assert result.parallel_interpretation.get("percept_id")
    assert result.candidate_memory_ids
    for mid in result.candidate_memory_ids:
        mem = store.get_memory(mid)
        assert mem is not None
        assert mem.status == MemoryStatus.candidate


def test_repeated_workspace_tick_is_idempotent(store, cfg, embedder):
    cfg.extractor = "auto"
    calls = {"n": 0}
    span = "A session delta fact about Twin."

    def scripted(percept, text, cfg):
        calls["n"] += 1
        return InterpretationResult(
            items=[InterpretedItem(
                memory_type="fact",
                title="Note",
                summary=span,
                domain="technical",
                cognitive_act=CognitiveAct.statement,
                evidence_span=span,
                attributed_to="user",
            )],
            status=InterpretationStatus.interpreted,
            interpreter="scripted", model="scripted",
            prompt_version="test", schema_version="1",
        )

    set_interpreter_override(scripted)
    a = workspace_tick(
        store, cfg, embedder, span,
        target_domain="technical", interpret=True,
        input_mode="delta", session_id="ses_idem", sequence=7,
    )
    b = workspace_tick(
        store, cfg, embedder, span,
        target_domain="technical", interpret=True,
        input_mode="delta", session_id="ses_idem", sequence=7,
    )
    assert a.tick_id == b.tick_id
    assert b.duplicated is True
    assert calls["n"] == 1
    percepts = [p for p in store.list_percepts() if p.percept_type == "session_delta"]
    assert len(percepts) == 1


def test_same_session_sequence_cannot_be_interpreted_twice(store, cfg, embedder):
    cfg.extractor = "auto"
    set_interpreter_override(lambda *_a, **_k: InterpretationResult(
        items=[], status=InterpretationStatus.empty,
        interpreter="scripted", model="scripted",
        prompt_version="t", schema_version="1",
    ))
    a = workspace_tick(
        store, cfg, embedder, "first wording",
        interpret=True, input_mode="delta",
        session_id="ses_seq", sequence=3, target_domain="technical",
    )
    b = workspace_tick(
        store, cfg, embedder, "different wording same sequence",
        interpret=True, input_mode="delta",
        session_id="ses_seq", sequence=3, target_domain="technical",
    )
    assert a.tick_id == b.tick_id
    assert b.duplicated is True


def test_snapshot_interpret_does_not_create_percept(store, cfg, embedder):
    before = len(store.list_percepts())
    result = workspace_tick(
        store, cfg, embedder, "We decided something important about architecture.",
        target_domain="technical", interpret=True, input_mode="snapshot",
    )
    assert result.parallel_interpretation.get("skipped") is True
    assert len(store.list_percepts()) == before


def test_unclassified_domain_not_coerced_to_technical(store, cfg, embedder, monkeypatch):
    monkeypatch.setattr(
        "twin.cognize.services.workspace.read_context",
        lambda *_a, **_k: ObserverReading(
            domain="unclassified",
            confidences={"domain": 0.0, "task_profile": 0.0, "project": 0.0},
            uncertain=True,
        ),
    )
    monkeypatch.setattr(
        "twin.cognize.services.workspace.observe",
        lambda *_a, **_k: ObserverSuggestion(inferred_domain="unclassified"),
    )
    monkeypatch.setattr(
        "twin.cognize.services.workspace.score_memories",
        lambda *_a, **_k: SalienceScores({}, {}, []),
    )
    result = workspace_tick(
        store, cfg, embedder, "vague",
        interpret=True, input_mode="delta", session_id="ses_u", sequence=1,
    )
    assert result.parallel_interpretation.get("skipped") is True
    assert result.parallel_interpretation.get("reason") == "needs_domain_confirmation"


def test_running_workspace_tick_is_not_executed_twice(store, cfg, embedder):
    from twin.cognize.services.workspace import text_content_hash
    from twin.store.store.workspace_ops_mixin import WorkspaceTickRecord

    cfg.extractor = "auto"
    calls = {"n": 0}
    text = "concurrent ownership must not double interpret"

    def scripted(*_a, **_k):
        calls["n"] += 1
        return InterpretationResult(
            items=[], status=InterpretationStatus.empty,
            interpreter="scripted", model="scripted",
            prompt_version="t", schema_version="1",
        )

    set_interpreter_override(scripted)
    before = len([p for p in store.list_percepts() if p.percept_type == "session_delta"])
    existing = WorkspaceTickRecord(
        session_id="ses_concurrent",
        sequence=1,
        input_mode="delta",
        content_hash=text_content_hash(text),
        interpret=True,
        status="running",
    )
    store.try_begin_workspace_tick(existing)

    result = workspace_tick(
        store, cfg, embedder, text,
        target_domain="technical",
        interpret=True,
        input_mode="delta",
        session_id="ses_concurrent",
        sequence=1,
    )
    assert result.duplicated is True
    assert result.stages == ["blocked_concurrent"]
    assert calls["n"] == 0
    after = len([p for p in store.list_percepts() if p.percept_type == "session_delta"])
    assert after == before


def test_workspace_tick_error_persists_and_blocks_until_retry(store, cfg, embedder, monkeypatch):
    monkeypatch.setattr(
        "twin.cognize.services.workspace.read_context",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom observe path")),
    )
    with pytest.raises(RuntimeError):
        workspace_tick(
            store, cfg, embedder, "fail me",
            session_id="ses_err", sequence=9, target_domain="technical",
        )
    row = store.get_workspace_tick_by_session_sequence("ses_err", 9)
    assert row is not None
    assert row.status == "error"
    assert row.error_stage == "reading"
    assert "RuntimeError" in row.error

    blocked = workspace_tick(
        store, cfg, embedder, "fail me",
        session_id="ses_err", sequence=9, target_domain="technical",
    )
    assert blocked.status == "error"
    assert blocked.duplicated is True

    # retry reclaims; still fails but proves reclaim path
    with pytest.raises(RuntimeError):
        workspace_tick(
            store, cfg, embedder, "fail me",
            session_id="ses_err", sequence=9, target_domain="technical",
            retry=True,
        )
    row2 = store.get_workspace_tick_by_session_sequence("ses_err", 9)
    assert row2.status == "error"
    assert row2.id == row.id


def test_second_retry_claim_is_blocked_concurrent(store, cfg, embedder):
    """After one atomic reclaim, a second retry must not execute."""
    from twin.store.store.workspace_ops_mixin import WorkspaceTickRecord

    text = "retry race"
    tick = WorkspaceTickRecord(
        session_id="ses_retry_race",
        sequence=1,
        content_hash=__import__(
            "twin.cognize.services.workspace", fromlist=["text_content_hash"]
        ).text_content_hash(text),
        input_mode="delta",
        interpret=True,
        status="error",
        error="RuntimeError: prior",
        error_stage="observe",
    )
    store.insert_workspace_tick(tick)
    assert store.try_claim_workspace_tick_retry(tick.id) is True

    result = workspace_tick(
        store, cfg, embedder, text,
        target_domain="technical",
        interpret=True,
        input_mode="delta",
        session_id="ses_retry_race",
        sequence=1,
        retry=True,
    )
    assert result.duplicated is True
    assert result.stages == ["blocked_concurrent"]


def test_retry_after_interpreter_failure_reuses_existing_percept(store, cfg, embedder, monkeypatch):
    from twin.cognize.services.interpreter.schema import (
        CognitiveAct,
        InterpretationResult,
        InterpretationStatus,
        InterpretedItem,
    )
    from twin.cognize.services.pipeline import extract_percept as real_extract

    cfg.extractor = "auto"
    span = "We decided to use FastAPI for the Twin HTTP API."
    calls = {"n": 0}

    def flaky_extract(store, cfg, embedder, percept, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient extract failure")
        return real_extract(store, cfg, embedder, percept, **kw)

    def scripted(percept, text, cfg):
        return InterpretationResult(
            items=[InterpretedItem(
                memory_type="decision",
                title="Use FastAPI",
                summary=span,
                domain="technical",
                cognitive_act=CognitiveAct.decision,
                evidence_span=span,
                attributed_to="user",
            )],
            status=InterpretationStatus.interpreted,
            interpreter="scripted", model="scripted",
            prompt_version="test", schema_version="1",
        )

    set_interpreter_override(scripted)
    monkeypatch.setattr("twin.cognize.services.workspace.extract_percept", flaky_extract)

    with pytest.raises(RuntimeError):
        workspace_tick(
            store, cfg, embedder, span,
            target_domain="technical",
            interpret=True,
            input_mode="delta",
            session_id="ses_retry_pct",
            sequence=1,
        )
    row = store.get_workspace_tick_by_session_sequence("ses_retry_pct", 1)
    assert row is not None
    assert row.status == "error"
    assert row.error_stage == "parallel_interpretation"
    assert row.percept_id  # persisted before extract failed
    before = [
        p for p in store.list_percepts()
        if (p.metadata or {}).get("tick_id") == row.id
    ]
    assert len(before) == 1

    ok = workspace_tick(
        store, cfg, embedder, span,
        target_domain="technical",
        interpret=True,
        input_mode="delta",
        session_id="ses_retry_pct",
        sequence=1,
        retry=True,
    )
    assert ok.status == "completed"
    assert ok.error == ""
    assert ok.parallel_interpretation.get("reused_percept") is True
    assert ok.candidate_memory_ids
    after = [
        p for p in store.list_percepts()
        if (p.metadata or {}).get("tick_id") == row.id
    ]
    assert len(after) == 1
    assert after[0].id == before[0].id
    done = store.get_workspace_tick(row.id)
    assert done.status == "completed"
    assert done.percept_id == before[0].id


def test_workspace_retry_can_complete_after_transient_failure(store, cfg, embedder, monkeypatch):
    from twin.cognize.services.observer import ObserverReading, ObserverSuggestion
    from twin.cognize.services.salience import SalienceScores

    blows = {"n": 0}

    def flaky_read(*_a, **_k):
        blows["n"] += 1
        if blows["n"] == 1:
            raise RuntimeError("transient read failure")
        return ObserverReading(
            domain="technical",
            confidences={"domain": 1.0, "task_profile": 1.0, "project": 0.0},
        )

    monkeypatch.setattr("twin.cognize.services.workspace.read_context", flaky_read)
    monkeypatch.setattr(
        "twin.cognize.services.workspace.observe",
        lambda *_a, **_k: ObserverSuggestion(inferred_domain="technical"),
    )
    monkeypatch.setattr(
        "twin.cognize.services.workspace.score_memories",
        lambda *_a, **_k: SalienceScores({}, {}, []),
    )

    with pytest.raises(RuntimeError):
        workspace_tick(
            store, cfg, embedder, "retry ok",
            session_id="ses_ok_retry", sequence=2, target_domain="technical",
        )
    ok = workspace_tick(
        store, cfg, embedder, "retry ok",
        session_id="ses_ok_retry", sequence=2, target_domain="technical",
        retry=True,
    )
    assert ok.status == "completed"
    assert ok.error == ""
    assert ok.stages[-1] == "done"
    row = store.get_workspace_tick_by_session_sequence("ses_ok_retry", 2)
    assert row.status == "completed"
    assert row.error == ""
    assert row.error_stage == ""
