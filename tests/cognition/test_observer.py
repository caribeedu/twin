"""Context observation: search vote → local LLM fallback."""

import json

import httpx

from twin import ids
from twin.cognition.observer import (
    infer_domain_from_search,
    read_context,
    resolve_context_domain,
)
from twin.cognition.sessions import ensure_project
from twin.memory.models import MemoryItem, MemoryStatus, MemoryType


def test_ambiguous_personal_text_stays_unclassified_without_llm(store, cfg):
    """No LLM → unclassified (never keyword-guess a permissive domain)."""
    reading = read_context(store, cfg,
                           "preciso resolver aquilo que conversamos ontem")
    assert reading.domain == "unclassified"
    assert reading.needs_domain_confirmation
    assert reading.mode == "unresolved"
    assert reading.fallback_reason == "deep_observer_unavailable"


def test_deep_read_invalid_json_stays_unclassified(store, cfg):
    def bad_json(request):
        return httpx.Response(200, json={"message": {"content": "not json {"}})

    client = httpx.Client(transport=httpx.MockTransport(bad_json),
                          base_url=cfg.ollama_url)
    reading = read_context(store, cfg, "hmm ok", client=client)
    assert reading.mode == "unresolved"
    assert reading.domain == "unclassified"
    assert reading.fallback_reason.startswith("deep_observer_failed:")


def test_deep_read_low_confidence_stays_unclassified(store, cfg):
    def unsure(request):
        return httpx.Response(200, json={"message": {"content": json.dumps({
            "domain": "technical", "task_profile": "coding", "project": None,
            "domain_confidence": 0.2, "task_confidence": 0.9,
        })}})

    client = httpx.Client(transport=httpx.MockTransport(unsure),
                          base_url=cfg.ollama_url)
    reading = read_context(store, cfg, "hmm ok", client=client)
    assert reading.mode == "llm"
    assert reading.domain == "unclassified"  # the model itself was not sure


def test_deep_fallback_is_logged(store, cfg, caplog):
    def broken(request):
        return httpx.Response(500, text="boom")

    client = httpx.Client(transport=httpx.MockTransport(broken),
                          base_url=cfg.ollama_url)
    with caplog.at_level("WARNING", logger="twin.cognition.observer"):
        read_context(store, cfg, "hmm ok", client=client)
    assert any("deep observer failed" in r.message for r in caplog.records)
    # the text being classified never reaches the log
    assert all("hmm ok" not in r.getMessage() for r in caplog.records)


def test_read_context_always_calls_llm_when_client_given(store, cfg):
    calls = {"n": 0}

    def ollama(request):
        calls["n"] += 1
        return httpx.Response(200, json={"message": {"content": json.dumps({
            "domain": "technical",
            "task_profile": "coding",
            "project": None,
            "domain_confidence": 0.9,
            "task_confidence": 0.8,
        })}})

    client = httpx.Client(transport=httpx.MockTransport(ollama),
                          base_url=cfg.ollama_url)
    # Clear technical wording — the LLM still runs (no keyword short-circuit).
    reading = read_context(
        store, cfg, "corrigir bug no deploy do backend api", client=client,
    )
    assert calls["n"] == 1
    assert reading.mode == "llm"
    assert reading.domain == "technical"


def test_read_context_deep_resolves_ambiguity(store, cfg):
    project = ensure_project(store, "Atlas")

    def ollama(request):
        assert request.url.path == "/api/chat"
        body = json.loads(request.content)
        assert body["format"]["type"] == "object"  # structured output requested
        return httpx.Response(200, json={"message": {"content": json.dumps({
            "domain": "work",
            "task_profile": "meeting_prep",
            "project": "Atlas",
            "domain_confidence": 0.8,
            "task_confidence": 0.7,
        })}})

    client = httpx.Client(transport=httpx.MockTransport(ollama),
                          base_url=cfg.ollama_url)
    reading = read_context(store, cfg, "get ready for tomorrow", client=client)
    assert reading.mode == "llm"
    assert reading.domain == "work"
    assert reading.task_profile == "meeting_prep"
    assert reading.project_id == project.id
    assert not reading.uncertain


def test_read_context_deep_failure_stays_unclassified(store, cfg):
    def broken(request):
        return httpx.Response(500, text="boom")

    client = httpx.Client(transport=httpx.MockTransport(broken),
                          base_url=cfg.ollama_url)
    reading = read_context(store, cfg, "hmm ok", client=client)
    assert reading.mode == "unresolved"
    assert reading.domain == "unclassified"


def test_deep_read_rejects_unknown_labels(store, cfg):
    def weird(request):
        return httpx.Response(200, json={"message": {"content": json.dumps({
            "domain": "astrology",
            "task_profile": "divination",
            "project": None,
            "domain_confidence": 0.9,
            "task_confidence": 0.9,
        })}})

    client = httpx.Client(transport=httpx.MockTransport(weird),
                          base_url=cfg.ollama_url)
    reading = read_context(store, cfg, "hmm ok", client=client)
    assert reading.mode == "llm"
    assert reading.domain == "unclassified"
    assert reading.task_profile == "general"


def _mem(store, embedder, *, title, summary, domain="technical"):
    mem = MemoryItem(
        id=ids.memory_id(), type=MemoryType.decision, domain=domain,
        title=title, summary=summary, status=MemoryStatus.confirmed,
        confidence=0.9,
    )
    store.insert_memory(mem)
    store.store_embedding(
        mem.id, "memory", embedder.name, embedder.embed(f"{title}\n{summary}"),
    )
    return mem


def test_infer_domain_from_search_votes_clear_winner(store, cfg, embedder):
    _mem(store, embedder, title="Atlas webhook stack",
         summary="Atlas webhooks run on FastAPI with schema_version.")
    reading = infer_domain_from_search(
        store, embedder, "What retry strategy for Atlas webhooks?",
    )
    assert reading is not None
    assert reading.mode == "search"
    assert reading.domain == "technical"


def test_infer_domain_from_search_none_without_hits(store, cfg, embedder):
    assert infer_domain_from_search(store, embedder, "hey there") is None


def test_resolve_skips_when_domain_already_frozen(store, cfg, embedder):
    reading = resolve_context_domain(
        store, cfg, embedder, "Atlas webhooks",
        existing_domain="technical",
    )
    assert reading.mode == "frozen"
    assert reading.domain == "technical"


def test_resolve_uses_search_before_llm(store, cfg, embedder, monkeypatch):
    _mem(store, embedder, title="Atlas webhook stack",
         summary="Atlas webhooks run on FastAPI.")

    def explode(*_a, **_k):
        raise AssertionError("LLM must not run when search votes")

    monkeypatch.setattr("twin.cognition.observer.read_context", explode)
    reading = resolve_context_domain(
        store, cfg, embedder, "Atlas webhook retry strategy",
    )
    assert reading.mode == "search"
    assert reading.domain == "technical"


def test_resolve_falls_back_to_llm_when_search_empty(store, cfg, embedder, monkeypatch):
    from twin.cognition.observer import ObserverReading

    monkeypatch.setattr(
        "twin.cognition.observer.infer_domain_from_search",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "twin.cognition.observer.read_context",
        lambda *_a, **_k: ObserverReading(
            domain="work", task_profile="meeting_prep", mode="llm",
            confidences={"domain": 0.8, "task_profile": 0.7, "project": 0.0},
        ),
    )
    reading = resolve_context_domain(store, cfg, embedder, "get ready for tomorrow")
    assert reading.mode == "llm"
    assert reading.domain == "work"
