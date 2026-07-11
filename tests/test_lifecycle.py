"""Explicit memory lifecycle: supersedence and contradiction."""

import pytest

from twin import ids
from twin.memory.lifecycle import contradict, supersede
from twin.memory.models import MemoryItem


def _mem(store, embedder, **kw):
    base = dict(id=ids.memory_id(), type="fact", title="t", summary="s",
                domain="technical", confidence=0.9, status="confirmed")
    base.update(kw)
    mem = MemoryItem(**base)
    store.insert_memory(mem)
    store.store_embedding(mem.id, "memory", embedder.name,
                          embedder.embed(f"{mem.title}\n{mem.summary}"))
    return mem


def test_supersede_closes_old_memory(store, embedder):
    old = _mem(store, embedder, type="belief", title="microservices",
               summary="Prefere microservices.", valid_from="2023-01-01")
    new = _mem(store, embedder, type="belief", title="modular monolith",
               summary="Prefere modular monolith.", valid_from="2026-07-01")
    result = supersede(store, new.id, old.id)
    reloaded = store.get_memory(old.id)
    assert reloaded.status.value == "deprecated"
    assert reloaded.valid_until == "2026-07-01"
    rels = store.relations_for(new.id)
    assert any(r.predicate == "supersedes" and r.object_id == old.id for r in rels)
    assert result.action == "supersede"


def test_contradict_flags_both_for_review(store, embedder):
    a = _mem(store, embedder, title="usa tabs", summary="Prefere tabs.")
    b = _mem(store, embedder, title="usa espaços", summary="Prefere espaços.")
    contradict(store, a.id, b.id)
    assert store.get_memory(b.id).status.value == "contradicted"
    assert store.get_memory(a.id).needs_review
    assert store.get_memory(b.id).needs_review
    rels = store.relations_for(a.id)
    assert any(r.predicate == "contradicts" for r in rels)


def test_lifecycle_rejects_self_reference(store, embedder):
    mem = _mem(store, embedder)
    with pytest.raises(ValueError):
        supersede(store, mem.id, mem.id)
    with pytest.raises(ValueError):
        contradict(store, mem.id, mem.id)


def test_lifecycle_requires_existing_memories(store, embedder):
    mem = _mem(store, embedder)
    with pytest.raises(ValueError):
        supersede(store, mem.id, "mem_inexistente")
    with pytest.raises(ValueError):
        contradict(store, "mem_inexistente", mem.id)
