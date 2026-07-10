from pathlib import Path

from twin.context_pack import build_context_pack
from twin.extract import extract_pending
from twin.firewall import Firewall
from twin.ingest import ingest_paths
from twin.observer import infer_domain, observe
from twin.search import search

EXAMPLES = Path(__file__).parent.parent / "examples"


def _populate(db, cfg, embedder):
    ingest_paths(db, [EXAMPLES])
    extract_pending(db, cfg, embedder)


def test_search_finds_fastapi_decision(db, cfg, embedder):
    _populate(db, cfg, embedder)
    fw = Firewall(cfg.policies_path, db)
    result = search(db, embedder, "qual framework usamos no backend de webhooks FastAPI",
                    target_domain="technical", firewall=fw)
    assert result.hits
    top_texts = " ".join(h.memory.summary for h in result.hits[:3])
    assert "FastAPI" in top_texts


def test_search_blocks_cross_domain(db, cfg, embedder):
    _populate(db, cfg, embedder)
    # plant a relationship-domain memory that matches the query text
    from twin import ids
    from twin.embeddings import to_blob
    from twin.models import MemoryItem

    mem = MemoryItem(id=ids.memory_id(), type="fact", title="jantar de aniversário FastAPI piada",
                     summary="conversa pessoal mencionando FastAPI", domain="relationship",
                     sensitivity="private", confidence=0.9, status="confirmed")
    db.insert_memory(mem)
    db.store_embedding(mem.id, "memory", embedder.name,
                       to_blob(embedder.embed(mem.title + " " + mem.summary)), embedder.dim)

    fw = Firewall(cfg.policies_path, db)
    result = search(db, embedder, "FastAPI backend webhooks",
                    target_domain="work", firewall=fw)
    assert any(b.memory_id == mem.id for b in result.blocked)
    assert all(h.memory.id != mem.id for h in result.hits)


def test_context_pack_respects_budget_and_includes_judgment(db, cfg, embedder):
    _populate(db, cfg, embedder)
    pack = build_context_pack(db, cfg, embedder, "escrever RFC sobre webhooks do Atlas",
                              target_domain="technical", max_tokens=400)
    assert pack.context_pack
    assert len(pack.context_pack) <= 400 * 4 + 200  # small tolerance
    assert "Judgment profile" in pack.context_pack
    assert pack.sources


def test_observer_suggests_and_infers_domain(db, cfg, embedder):
    _populate(db, cfg, embedder)
    assert infer_domain("preciso revisar a arquitetura do deploy") == "technical"
    suggestion = observe(db, cfg, embedder,
                         "vou escrever a RFC de arquitetura dos webhooks do Atlas")
    assert suggestion.inferred_domain == "technical"
    assert suggestion.suggested_context
    for item in suggestion.suggested_context:
        assert item["allowed"] is True
        assert item["memory_id"].startswith("mem_")
