"""Embedding helpers — URL sanitization and reachability probes."""

import httpx

from twin.store.embeddings import ollama_reachable, sanitize_base_url


def test_sanitize_base_url_strips_surrogates_and_junk():
    # WSL / mis-decoded .env often injects surrogateescape bytes (e.g. 0xC3 → \udcc3)
    dirty = "http://172.25.210.170:11434" + "\udcc3"
    assert sanitize_base_url(dirty) == "http://172.25.210.170:11434"
    assert sanitize_base_url("  http://127.0.0.1:11434/\n") == "http://127.0.0.1:11434/"
    assert sanitize_base_url("") == ""


def test_ollama_reachable_sanitizes_dirty_url_before_get(monkeypatch):
    """twin init must not traceback when the typed URL carries surrogate junk."""
    seen: list[str] = []

    def fake_get(url, timeout=1.5):
        seen.append(url)

        class _R:
            status_code = 200

        return _R()

    monkeypatch.setattr(httpx, "get", fake_get)
    assert ollama_reachable("http://172.25.210.170:11434\udcc3") is True
    assert seen == ["http://172.25.210.170:11434/api/tags"]


def test_ollama_reachable_returns_false_on_unicode_error(monkeypatch):
    def boom(*_a, **_k):
        raise UnicodeEncodeError("utf-8", "\udcc3", 0, 1, "surrogates not allowed")

    monkeypatch.setattr(httpx, "get", boom)
    assert ollama_reachable("http://127.0.0.1:11434") is False
