"""Memory quality analysis and review priority (twin.cognition.quality)."""

from twin import ids
from twin.cognition.quality import (
    _looks_conflict,
    analyze_memory,
    review_priority,
    review_queue,
)
from twin.memory.models import MemoryItem


def _mem(store, embedder, **kw):
    base = dict(
        id=ids.memory_id(), type="fact", title="t", summary="s",
        domain="technical", confidence=0.9, status="confirmed",
        entities=["Twin"],
    )
    base.update(kw)
    mem = MemoryItem(**base)
    store.insert_memory(mem)
    store.store_embedding(
        mem.id, "memory", embedder.name,
        embedder.embed(f"{mem.title}\n{mem.summary}"),
    )
    return mem


def test_quality_detects_near_duplicate(store, embedder):
    _mem(store, embedder, title="Twin uses FastAPI",
         summary="Twin HTTP API uses FastAPI.", status="candidate", needs_review=True)
    b = _mem(store, embedder, title="Twin uses FastAPI",
             summary="Twin HTTP API uses FastAPI.", status="candidate", needs_review=True)
    report = analyze_memory(store, embedder, b.id)
    assert report.review_priority > 0
    flags = set(report.quality_flags)
    assert flags & {"exact_duplicate", "near_duplicate", "possible_merge"}


def test_quality_scope_difference_not_conflict(store, embedder):
    _mem(store, embedder, type="decision", title="Postgres primary",
         summary="PostgreSQL is primary in production.",
         entities=["Twin", "PostgreSQL"], status="confirmed")
    b = _mem(store, embedder, type="decision", title="SQLite dev",
             summary="SQLite is used for development.",
             entities=["Twin", "SQLite"], status="candidate", needs_review=True)
    report = analyze_memory(store, embedder, b.id)
    assert report.memory_id == b.id
    assert "possible_conflict" not in report.quality_flags or "scope_difference" in report.quality_flags


def test_review_queue_priority_order(store, embedder):
    low = _mem(store, embedder, title="low", summary="minor note",
               status="candidate", needs_review=True, confidence=0.9, impact="low",
               sensitivity="public")
    high = _mem(store, embedder, type="decision", title="high", summary="strategic choice",
                status="candidate", needs_review=True, confidence=0.4, impact="high",
                sensitivity="private")
    analyze_memory(store, embedder, low.id)
    analyze_memory(store, embedder, high.id)
    queue = review_queue(store, limit=10)
    assert queue
    assert queue[0].review_priority >= queue[-1].review_priority


def test_different_decisions_not_conflict():
    a = MemoryItem(
        id="a", type="decision", title="Postgres",
        summary="Twin uses PostgreSQL as primary storage.",
        domain="technical", entities=["Twin", "PostgreSQL"], project_id="p",
    )
    b = MemoryItem(
        id="b", type="decision", title="FastAPI",
        summary="Twin uses FastAPI for its HTTP API.",
        domain="technical", entities=["Twin", "FastAPI"], project_id="p",
    )
    kind = _looks_conflict(a, b, sim=0.7, claim_match=0.82)
    assert kind in (None, "possibly_related", "scope_difference")
    assert kind != "possible_conflict"


def test_priority_floors_for_high_confidence_conflict():
    mem = MemoryItem(
        id="x", type="decision", title="db", summary="uses postgres",
        domain="technical", confidence=0.95, impact="high", sensitivity="public",
    )
    low = review_priority(mem, contradiction_risk=0.0)
    high = review_priority(mem, contradiction_risk=0.95)
    assert high >= 0.9
    assert high > low
