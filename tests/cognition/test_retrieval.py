"""Multi-stage retrieval pipeline (twin.cognize.services.retrieval)."""

from twin import ids
from twin.cognize.services.retrieval import retrieve
from twin.store.models import Evidence, StoreClaim
from twin.sense.sensory.percept import Percept


def _mem(store, embedder, title, summary, **kw):
    base = dict(id=ids.claim_id(), type="fact", title=title, summary=summary,
                domain="technical", confidence=0.9, status="confirmed")
    base.update(kw)
    mem = StoreClaim(**base)
    store.insert_claim(mem)  # also links mem.entities in the graph
    store.store_embedding(mem.id, "claim", embedder.name,
                          embedder.embed(f"{title}\n{summary}"))
    return mem


def test_reduces_to_baseline_search(store, embedder):
    _mem(store, embedder, "Webhooks use FastAPI", "FastAPI serves the webhook backend.")
    result = retrieve(store, embedder, "FastAPI webhooks")
    assert result.hits
    assert result.stages["candidates"] >= 1
    assert result.stages["final"] == len(result.hits)


def test_project_boost_reorders(store, embedder):
    # same text relevance; only the project link differs
    plain = _mem(store, embedder, "Webhook retries", "Webhook retries use backoff.")
    linked = _mem(store, embedder, "Webhook retries", "Webhook retries use backoff.",
                  project_id="proj_atlas")
    result = retrieve(store, embedder, "webhook retries backoff",
                      project_id="proj_atlas")
    scores = {h.claim.id: h.score for h in result.hits}
    assert scores[linked.id] > scores[plain.id]
    assert result.hits[0].claim.id == linked.id
    assert "project match" in result.hits[0].why


def test_graph_expansion_pulls_adjacent_memories(store, embedder):
    # the entity name never appears in the query — only the graph connects them
    _mem(store, embedder, "Webhooks decision",
         "Webhooks run on FastAPI.", entities=["Zephyr"])
    adjacent = _mem(store, embedder, "Provisioning quirk",
                    "Provisioning needs the eu-west bucket.", entities=["Zephyr"])
    result = retrieve(store, embedder, "FastAPI webhooks")
    ids_found = {h.claim.id for h in result.hits}
    assert adjacent.id in ids_found
    graph_hit = next(h for h in result.hits if h.claim.id == adjacent.id)
    assert "graph expansion" in graph_hit.why
    assert result.stages["after_graph"] >= result.stages["candidates"]


def test_temporal_filter_drops_expired(store, embedder):
    _mem(store, embedder, "Old webhook stack", "Webhooks ran on Flask.",
         valid_until="2020-01-01T00:00:00+00:00")
    current = _mem(store, embedder, "Webhook stack", "Webhooks run on FastAPI.")
    result = retrieve(store, embedder, "webhook stack")
    assert {h.claim.id for h in result.hits} == {current.id}


def test_source_trust_weights_scores(store, embedder):
    def mem_with_trust(trust):
        percept = Percept(percept_type="note", source_sensor="test",
                          content=f"deploy note trust {trust}",
                          source_trust=trust).seal()
        store.insert_percept(percept)
        mem = _mem(store, embedder, "Deploy cadence", "Deploys happen on Tuesdays.")
        store.insert_evidence(Evidence(id=ids.evidence_id(), claim_id=mem.id,
                                       percept_id=percept.id, quote="deploys on Tuesdays"))
        return mem

    trusted = mem_with_trust(1.0)
    dubious = mem_with_trust(0.1)
    result = retrieve(store, embedder, "deploy cadence Tuesdays")
    scores = {h.claim.id: h.score for h in result.hits}
    assert scores[trusted.id] > scores[dubious.id]


def test_reranker_is_applied_and_best_effort(store, embedder):
    a = _mem(store, embedder, "Webhook retries", "Retries use backoff.")
    b = _mem(store, embedder, "Webhook auth", "Webhooks sign with HMAC.")

    def reversed_order(query, hits):
        return list(reversed(hits))

    baseline = retrieve(store, embedder, "webhooks")
    reranked = retrieve(store, embedder, "webhooks", reranker=reversed_order)
    assert [h.claim.id for h in reranked.hits] == \
        [h.claim.id for h in reversed(baseline.hits)]

    def broken(query, hits):
        raise RuntimeError("model gone")

    survived = retrieve(store, embedder, "webhooks", reranker=broken)
    assert {h.claim.id for h in survived.hits} == {a.id, b.id}


def test_reranker_failure_is_observable(store, embedder, caplog):
    _mem(store, embedder, "Webhook retries", "Retries use backoff.")

    def broken(query, hits):
        raise RuntimeError("model gone")

    with caplog.at_level("WARNING", logger="twin.cognize.services.retrieval"):
        result = retrieve(store, embedder, "webhooks", reranker=broken)
    assert result.diagnostics["reranker"] == {
        "attempted": True, "succeeded": False, "error_type": "RuntimeError",
    }
    assert any("reranker failed" in r.message for r in caplog.records)
    # the query never reaches the log
    assert all("webhooks" not in r.getMessage() for r in caplog.records)

    ok = retrieve(store, embedder, "webhooks", reranker=lambda q, h: h)
    assert ok.diagnostics["reranker"] == {"attempted": True, "succeeded": True}
    assert retrieve(store, embedder, "webhooks").diagnostics == {}


def test_graph_expansion_damps_broad_entities(store, embedder):
    """An entity attached to many memories is weak evidence: its expansions
    score below those carried by a specific entity, and hyper-broad ones are
    dropped."""
    _mem(store, embedder, "Webhooks decision", "Webhooks run on FastAPI.",
         entities=["Zephyr", "Python"])
    specific = _mem(store, embedder, "Zephyr quirk",
                    "Zephyr needs the eu-west bucket.", entities=["Zephyr"])
    # make "Python" a broad entity: attached to many unrelated memories
    broad_members = [
        _mem(store, embedder, f"Python note {i}", f"Unrelated python fact {i}.",
             entities=["Python"])
        for i in range(12)
    ]
    result = retrieve(store, embedder, "FastAPI webhooks", limit=30)
    scores = {h.claim.id: h.score for h in result.hits}
    whys = {h.claim.id: h.why for h in result.hits}
    assert specific.id in scores
    assert "via Zephyr" in whys[specific.id]
    for mem in broad_members:
        if mem.id in scores and "graph expansion" in whys[mem.id]:
            assert scores[mem.id] < scores[specific.id]


def test_candidates_excluded_unless_requested(store, embedder):
    cand = _mem(store, embedder, "Maybe switch to Kafka", "Considering Kafka.",
                status="candidate")
    strict = retrieve(store, embedder, "Kafka switch")
    assert all(h.claim.id != cand.id for h in strict.hits)
    loose = retrieve(store, embedder, "Kafka switch", include_candidates=True)
    assert any(h.claim.id == cand.id for h in loose.hits)
