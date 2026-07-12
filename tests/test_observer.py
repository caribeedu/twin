"""Fast/deep observation (twin.cognition.observer.read_context)."""

import json

import httpx

from twin.cognition.observer import _fast_read, read_context
from twin.cognition.sessions import ensure_project


def test_fast_read_confident_on_clear_text(store):
    reading = _fast_read(store, "revisar a arquitetura do deploy da api no docker")
    assert reading.mode == "fast"
    assert reading.domain == "technical"
    assert not reading.uncertain


def test_fast_read_uncertain_on_vague_text(store):
    reading = _fast_read(store, "hmm ok")
    assert reading.uncertain
    assert reading.confidences["domain"] == 0.0
    # no evidence → no domain assumption; downstream this is default-deny
    assert reading.domain == "unclassified"
    assert reading.needs_domain_confirmation


def test_ambiguous_personal_text_never_becomes_technical(store, cfg):
    """A vague personal message with no recognized keywords and no Ollama
    must NOT be classified into a permissive domain."""
    reading = read_context(store, cfg,
                           "preciso resolver aquilo que conversamos ontem")
    assert reading.domain == "unclassified"
    assert reading.needs_domain_confirmation
    assert reading.mode == "fast"
    assert reading.fallback_reason == "deep_observer_unavailable"


def test_deep_read_invalid_json_falls_back_conservatively(store, cfg):
    def bad_json(request):
        return httpx.Response(200, json={"message": {"content": "not json {"}})

    client = httpx.Client(transport=httpx.MockTransport(bad_json),
                          base_url=cfg.ollama_url)
    reading = read_context(store, cfg, "hmm ok", client=client)
    assert reading.mode == "fast"
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
    assert reading.mode == "deep"
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


def test_fast_read_project_from_cwd_beats_mention(store):
    atlas = ensure_project(store, "Atlas", repos=["atlas-api"])
    beacon = ensure_project(store, "Beacon")
    reading = _fast_read(store, "trabalhando no beacon", cwd="/home/edu/atlas-api")
    assert reading.project_id == atlas.id
    assert reading.confidences["project"] == 0.9
    reading = _fast_read(store, "trabalhando no beacon")
    assert reading.project_id == beacon.id
    assert reading.confidences["project"] == 0.7


def test_read_context_skips_deep_when_fast_is_confident(store, cfg):
    def explode(request):  # any HTTP call would fail the test
        raise AssertionError("deep read should not run")

    client = httpx.Client(transport=httpx.MockTransport(explode),
                          base_url=cfg.ollama_url)
    reading = read_context(store, cfg, "corrigir bug no deploy do backend api",
                           client=client)
    assert reading.mode == "fast"


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
    assert reading.mode == "deep"
    assert reading.domain == "work"
    assert reading.task_profile == "meeting_prep"
    assert reading.project_id == project.id
    assert not reading.uncertain


def test_read_context_deep_failure_falls_back_to_fast(store, cfg):
    def broken(request):
        return httpx.Response(500, text="boom")

    client = httpx.Client(transport=httpx.MockTransport(broken),
                          base_url=cfg.ollama_url)
    reading = read_context(store, cfg, "hmm ok", client=client)
    assert reading.mode == "fast"


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
    assert reading.mode == "deep"
    # unknown labels fall back to the fast (conservative) values — never to
    # a permissive domain the model invented
    assert reading.domain == "unclassified"
    assert reading.task_profile == "general"
