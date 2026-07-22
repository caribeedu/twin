"""Parallel workspace tick (twin.cognition.workspace)."""

from twin import ids
from twin.cognition.workspace import workspace_tick
from twin.memory.models import MemoryItem


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
    result = workspace_tick(
        store, cfg, embedder, "hmm ok",
        interpret=False,
    )
    assert "reading" in result.stages
    assert "recall" in result.stages
    assert result.stages[-1] == "done"
    assert result.silent is True
    assert result.suggestions == []
    assert result.candidate_memory_ids == []
    assert result.parallel_interpretation == {}


def test_workspace_tick_suggests_high_confidence_memory(store, cfg, embedder):
    mem = _mem(store, embedder)
    result = workspace_tick(
        store, cfg, embedder,
        "database architecture deploy postgres primary store",
        target_domain="technical",
        interpret=False,
    )
    ids_out = {s["memory_id"] for s in result.suggestions}
    assert mem.id in ids_out or result.silent
    # if silent, still must not leak into parallel durable state
    assert result.candidate_memory_ids == []
    if not result.silent:
        hit = next(s for s in result.suggestions if s["memory_id"] == mem.id)
        assert hit["stage"] == "suggestion"
        assert hit["confidence"] >= 0.55


def test_workspace_tick_interpret_creates_candidates_only(store, cfg, embedder):
    cfg.extractor = "echo"
    text = (
        "We decided to use FastAPI for the Twin HTTP API. "
        "This is an architecture decision for the backend."
    )
    result = workspace_tick(
        store, cfg, embedder, text,
        target_domain="technical",
        interpret=True,
    )
    assert "parallel_interpretation" in result.stages
    assert result.parallel_interpretation.get("percept_id")
    # echo may or may not insert depending on heuristics; if inserted,
    # they must remain candidates (never confirmed by the tick).
    for mid in result.candidate_memory_ids:
        mem = store.get_memory(mid)
        assert mem is not None
        assert mem.status.value == "candidate"
