from pathlib import Path

from twin.cognition import extract_pending
from twin.cognition.context_pack import build_context_pack
from twin.cognition.observer import infer_domain, observe
from twin.judgment.firewall import Firewall
from twin.memory.search import search
from twin.sensory import sense_paths

EXAMPLES = Path(__file__).parent.parent / "examples"


def _populate(store, cfg, embedder):
    percepts, _ = sense_paths([EXAMPLES])
    for p in percepts:
        store.insert_percept(p)
    extract_pending(store, cfg, embedder)


def test_search_finds_fastapi_decision(store, cfg, embedder):
    _populate(store, cfg, embedder)
    fw = Firewall(cfg.policies_path, store)
    result = search(store, embedder, "qual framework usamos no backend de webhooks FastAPI",
                    target_domain="technical", firewall=fw)
    assert result.hits
    top_texts = " ".join(h.memory.summary for h in result.hits[:3])
    assert "FastAPI" in top_texts


def test_search_blocks_cross_domain(store, cfg, embedder):
    _populate(store, cfg, embedder)
    # plant a relationship-domain memory that matches the query text
    from twin import ids
    from twin.memory.models import MemoryItem

    mem = MemoryItem(id=ids.memory_id(), type="fact", title="jantar de aniversário FastAPI piada",
                     summary="conversa pessoal mencionando FastAPI", domain="relationship",
                     sensitivity="private", confidence=0.9, status="confirmed")
    store.insert_memory(mem)
    store.store_embedding(mem.id, "memory", embedder.name,
                          embedder.embed(mem.title + " " + mem.summary))

    fw = Firewall(cfg.policies_path, store)
    result = search(store, embedder, "FastAPI backend webhooks",
                    target_domain="work", firewall=fw)
    assert any(b.memory_id == mem.id for b in result.blocked)
    assert all(h.memory.id != mem.id for h in result.hits)


def test_context_pack_respects_budget_and_includes_judgment(store, cfg, embedder):
    _populate(store, cfg, embedder)
    pack = build_context_pack(store, cfg, embedder, "escrever RFC sobre webhooks do Atlas",
                              target_domain="technical", max_tokens=400)
    assert pack.context_pack
    assert len(pack.context_pack) <= 400 * 4 + 200  # small tolerance
    assert "Judgment profile" in pack.context_pack
    assert pack.sources
    assert all("percept_ids" in s for s in pack.sources)


def test_observer_suggests_and_infers_domain(store, cfg, embedder):
    _populate(store, cfg, embedder)
    assert infer_domain("preciso revisar a arquitetura do deploy") == "technical"
    suggestion = observe(store, cfg, embedder,
                         "vou escrever a RFC de arquitetura dos webhooks do Atlas")
    assert suggestion.inferred_domain == "technical"
    assert suggestion.suggested_context
    for item in suggestion.suggested_context:
        assert item["allowed"] is True
        assert item["memory_id"].startswith("mem_")
