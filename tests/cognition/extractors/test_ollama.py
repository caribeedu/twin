"""Ollama integration — tested against a fake HTTP transport (no server)."""

import json

import httpx
import pytest

from twin.cognize.services.extractors import ollama as ollama_extractor
from twin.store.embeddings import OllamaEmbedder, get_embedder
from twin.sense.sensory.percept import Percept

FAKE_EXTRACTION = {
    "memories": [
        {
            "type": "decision",
            "title": "Usar FastAPI no serviço de webhooks",
            "summary": "O time decidiu usar FastAPI no backend do serviço de webhooks do Atlas.",
            "domain": "technical",
            "sensitivity": "internal",
            "confidence": 0.9,
            "valid_from": None,
            "entities": ["Atlas", "FastAPI"],
            "relations": [{"subject": "Atlas", "predicate": "uses", "object": "FastAPI"}],
            "evidence_quote": "vamos usar FastAPI no backend do serviço de webhooks",
        }
    ]
}


def _fake_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler),
                        base_url="http://fake-ollama")


def test_ollama_extractor_parses_structured_output():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "message": {"role": "assistant", "content": json.dumps(FAKE_EXTRACTION)}
        })

    percept = Percept(percept_type="meeting_transcript", source_sensor="meeting",
                      content="Marina: vamos usar FastAPI no backend do serviço de webhooks",
                      actors=["Marina"]).seal()
    result = ollama_extractor.extract(percept, percept.content,
                                      model="qwen3:8b", client=_fake_client(handler))
    assert result.extractor == "ollama:qwen3:8b"
    assert len(result.memories) == 1
    mem = result.memories[0]
    assert mem.type == "decision"
    assert mem.entities == ["Atlas", "FastAPI"]
    # request used structured outputs (json schema in `format`) and the model
    body = captured["body"]
    assert body["model"] == "qwen3:8b"
    assert body["format"]["type"] == "object"
    assert body["stream"] is False


def test_ollama_embedder_and_model_tagging():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/embed"
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3, 0.4]]})

    emb = OllamaEmbedder(model="nomic-embed-text", client=_fake_client(handler))
    vec = emb.embed("qualquer texto")
    assert vec == [0.1, 0.2, 0.3, 0.4]
    assert emb.dim == 4
    assert emb.name == "ollama-nomic-embed-text"


def test_get_embedder_falls_back_to_hash_when_ollama_unreachable(monkeypatch):
    emb = get_embedder("auto", 128, ollama_url="http://127.0.0.1:1")  # closed port
    assert emb.name.startswith("hash-")


def test_embeddings_from_different_models_never_mix(store):
    store.store_embedding("mem_a", "memory", "hash-v1-512", [1.0, 0.0])
    store.store_embedding("mem_b", "memory", "ollama-nomic-embed-text", [1.0, 0.0])
    ids_hash = [rid for rid, _ in store.iter_embeddings("memory", "hash-v1-512")]
    ids_ollama = [rid for rid, _ in store.iter_embeddings("memory", "ollama-nomic-embed-text")]
    assert ids_hash == ["mem_a"]
    assert ids_ollama == ["mem_b"]


def test_pipeline_defers_when_interpreter_unavailable(store, cfg, embedder):
    """v0.7: extractor='ollama' routes through the cognitive interpreter; when
    the model is unreachable the Percept is DEFERRED (retryable), never
    silently handed to lexical rules to fabricate conclusions."""
    from twin.cognize.services.pipeline import extract_percept

    cfg.extractor = "ollama"
    cfg.ollama_url = "http://127.0.0.1:1"  # unreachable → defer, not fall back
    percept = Percept(percept_type="meeting_transcript", source_sensor="meeting",
                      content="Marina: decidimos usar FastAPI no backend.",
                      actors=["Marina"]).seal()
    store.insert_percept(percept)
    report = extract_percept(store, cfg, embedder, percept)
    assert report.deferred is True
    assert report.interpretation_status == "deferred"
    assert report.inserted == []
    assert store.list_memories() == []
    # deferred means retryable — the Percept is still pending
    assert store.get_interpretation(percept.id).status == "deferred"
    assert store.percepts_pending_interpretation(max_attempts=6) != []
