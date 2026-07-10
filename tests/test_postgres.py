"""PostgreSQL + pgvector backend, exercised against a real server.

Set TWIN_TEST_PG_URL to run (e.g. postgresql://twin:twin@localhost:5432/twin);
skipped otherwise. Each run uses a fresh schema.
"""

import os
from pathlib import Path

import pytest

PG_URL = os.environ.get("TWIN_TEST_PG_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="TWIN_TEST_PG_URL not set")

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture()
def pg_store():
    import psycopg

    from twin.memory.store.postgres import PostgresStore

    # isolated schema per test run
    admin = psycopg.connect(PG_URL, autocommit=True)
    admin.execute("DROP SCHEMA IF EXISTS twin_test CASCADE")
    admin.execute("CREATE SCHEMA twin_test")
    admin.close()
    # twin_test first (tables land there), public second (pgvector type lives there)
    url = PG_URL + ("&" if "?" in PG_URL else "?") + "options=-csearch_path%3Dtwin_test,public"
    store = PostgresStore(url)
    yield store
    store.close()


def test_pgvector_available(pg_store):
    assert pg_store.has_pgvector, "pgvector extension should be active in tests"


def test_percept_roundtrip_and_dedup(pg_store):
    from twin.sensory import sense_paths

    percepts, _ = sense_paths([EXAMPLES / "docs"])
    percept = percepts[0]
    assert pg_store.insert_percept(percept) == percept.id
    loaded = pg_store.get_percept(percept.id)
    assert loaded.content == percept.content
    assert loaded.actors == ["Edu"]
    # dedup by content hash
    clone, _ = sense_paths([EXAMPLES / "docs"])
    assert pg_store.insert_percept(clone[0]) is None
    assert len(pg_store.unprocessed_percepts()) == 1


def test_full_pipeline_on_postgres(pg_store, cfg, embedder):
    from twin.cognition import extract_pending
    from twin.judgment.firewall import Firewall
    from twin.memory.search import search
    from twin.sensory import sense_paths

    percepts, _ = sense_paths([EXAMPLES])
    for p in percepts:
        pg_store.insert_percept(p)
    reports = extract_pending(pg_store, cfg, embedder)
    inserted = [mid for r in reports for mid in r.inserted]
    assert inserted

    # hybrid search: PG tsvector FTS + pgvector similarity
    fw = Firewall(cfg.policies_path, pg_store)
    result = search(pg_store, embedder, "FastAPI backend webhooks",
                    target_domain="technical", firewall=fw)
    assert result.hits
    assert "FastAPI" in " ".join(h.memory.summary for h in result.hits[:3])

    # review lifecycle
    from twin.memory.models import MemoryStatus

    pg_store.set_status(inserted[0], MemoryStatus.confirmed)
    assert pg_store.get_memory(inserted[0]).status.value == "confirmed"

    # entities + graph
    entities = pg_store.list_entities()
    assert entities
    memories = pg_store.memories_for_entity(entities[0].id)
    assert isinstance(memories, list)


def test_pgvector_server_side_similarity(pg_store, embedder):
    from twin import ids
    from twin.memory.models import MemoryItem

    for i, text in enumerate(["FastAPI no backend", "jantar em família"]):
        mem = MemoryItem(id=ids.memory_id(), type="fact", title=text, summary=text)
        pg_store.insert_memory(mem)
        pg_store.store_embedding(mem.id, "memory", embedder.name, embedder.embed(text))

    query_vec = embedder.embed("backend FastAPI webhooks")
    scores = pg_store.similar(query_vec, "memory", embedder.name, min_sim=0.01)
    assert scores
    top = max(scores, key=scores.get)
    assert "FastAPI" in pg_store.get_memory(top).title


def test_firewall_log_on_postgres(pg_store, cfg):
    from twin import ids
    from twin.clock import now_iso
    from twin.judgment.firewall import Firewall
    from twin.memory.models import MemoryItem

    mem = MemoryItem(id=ids.memory_id(), type="fact", title="x", summary="x",
                     domain="relationship", status="confirmed", confidence=0.9,
                     created_at=now_iso(), updated_at=now_iso())
    fw = Firewall(cfg.policies_path, pg_store)
    verdict = fw.evaluate(mem, "work")
    assert not verdict.allowed
    rows = pg_store._exec("SELECT * FROM firewall_log")
    assert len(rows) == 1
