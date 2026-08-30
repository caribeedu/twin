"""Pluggable LLM / embed provider wiring."""

from __future__ import annotations

import httpx

from twin.llm import (
    AnthropicChatClient,
    GeminiChatClient,
    OpenAICompatChatClient,
    get_chat_client,
    normalize_provider,
    parse_model_json,
    provider_kind,
    resolve_api_key,
)
from twin.config import Config, load_config
from twin.interfaces.setup_wizard import run_setup_wizard
from twin.store.embeddings import (
    GeminiEmbedder,
    OpenAICompatEmbedder,
    get_embedder_for_config,
)


def test_normalize_provider():
    assert normalize_provider("ollama") == "ollama"
    assert normalize_provider("OpenAI") == "openai"
    assert normalize_provider("claude") == "claude"
    assert normalize_provider("lmstudio") == "lmstudio"
    assert provider_kind("openai") == "openai_compatible"
    assert provider_kind("claude") == "anthropic"
    assert provider_kind("gemini") == "gemini"
    assert provider_kind("groq") == "openai_compatible"


def test_parse_model_json_strips_fences():
    assert parse_model_json("```json\n{\"a\": 1}\n```") == {"a": 1}


def test_config_resolves_openai_defaults(monkeypatch):
    monkeypatch.setenv("TWIN_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("TWIN_LLM_MODEL", "gpt-4o-mini")
    monkeypatch.delenv("TWIN_LLM_BASE_URL", raising=False)
    cfg = Config()
    assert cfg.normalized_llm_provider == "openai_compatible"
    assert cfg.resolved_llm_base_url == "https://api.openai.com/v1"
    assert cfg.resolved_llm_model == "gpt-4o-mini"


def test_config_resolves_anthropic_and_gemini(monkeypatch):
    monkeypatch.setenv("TWIN_LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("TWIN_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("TWIN_LLM_MODEL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("TWIN_LLM_API_KEY", raising=False)
    cfg = Config()
    assert cfg.llm_provider_kind == "anthropic"
    assert cfg.resolved_llm_base_url == "https://api.anthropic.com"
    assert "claude" in cfg.resolved_llm_model
    assert resolve_api_key(cfg) == "sk-ant-test"

    monkeypatch.setenv("TWIN_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "gem-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = Config()
    assert cfg.llm_provider_kind == "gemini"
    assert "generativelanguage" in cfg.resolved_llm_base_url
    assert resolve_api_key(cfg) == "gem-test"


def test_config_groq_preset(monkeypatch):
    monkeypatch.setenv("TWIN_LLM_PROVIDER", "groq")
    monkeypatch.delenv("TWIN_LLM_BASE_URL", raising=False)
    cfg = Config()
    assert cfg.normalized_llm_provider == "groq"
    assert cfg.llm_provider_kind == "openai_compatible"
    assert "groq.com" in cfg.resolved_llm_base_url


def test_config_ollama_still_default(monkeypatch):
    monkeypatch.delenv("TWIN_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("TWIN_LLM_BASE_URL", raising=False)
    cfg = Config()
    assert cfg.normalized_llm_provider == "ollama"
    assert "11434" in cfg.resolved_llm_base_url


def test_config_ollama_url_overrides_preset_localhost(monkeypatch):
    """WSL → Windows Ollama: TWIN_OLLAMA_URL must win over preset 127.0.0.1."""
    monkeypatch.delenv("TWIN_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("TWIN_LLM_BASE_URL", raising=False)
    monkeypatch.setenv("TWIN_OLLAMA_URL", "http://172.25.208.1:11434")
    cfg = Config()
    assert cfg.ollama_url == "http://172.25.208.1:11434"
    assert cfg.resolved_llm_base_url == "http://172.25.208.1:11434"


def test_openai_compat_chat_with_mock_transport():
    responses = [
        httpx.Response(400, json={"error": "no schema"}),
        httpx.Response(200, json={"choices": [{"message": {"content": "{\"ok\": true}"}}]}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    client = OpenAICompatChatClient("https://example.test/v1", "demo", api_key="sk")
    client._client = httpx.Client(
        base_url="https://example.test/v1",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer sk"},
    )
    assert client.complete_json(
        system="s", user="u", schema={"type": "object"},
    ) == {"ok": True}


def test_anthropic_chat_tool_use_mock():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/v1/messages")
        return httpx.Response(200, json={
            "content": [{
                "type": "tool_use",
                "name": "twin_response",
                "input": {"ok": True},
            }],
        })

    client = AnthropicChatClient(
        "https://api.anthropic.com", "claude-test", api_key="sk-ant",
    )
    client._client = httpx.Client(
        base_url="https://api.anthropic.com",
        transport=httpx.MockTransport(handler),
    )
    assert client.complete_json(
        system="s", user="u", schema={"type": "object", "properties": {}},
    ) == {"ok": True}


def test_gemini_chat_mock():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "generateContent" in request.url.path
        return httpx.Response(200, json={
            "candidates": [{
                "content": {"parts": [{"text": "{\"ok\": true}"}]},
            }],
        })

    client = GeminiChatClient(
        "https://generativelanguage.googleapis.com", "gemini-2.0-flash",
        api_key="gem",
    )
    client._client = httpx.Client(
        base_url="https://generativelanguage.googleapis.com",
        transport=httpx.MockTransport(handler),
    )
    assert client.complete_json(
        system="s", user="u", schema={"type": "object"},
    ) == {"ok": True}


def test_openai_compat_embedder():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/embeddings")
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2, 0.3]}]})

    emb = OpenAICompatEmbedder("https://example.test/v1", "emb-1", api_key="sk")
    emb._client = httpx.Client(
        base_url="https://example.test/v1",
        transport=httpx.MockTransport(handler),
    )
    vec = emb.embed("hello")
    assert vec == [0.1, 0.2, 0.3]
    assert emb.dim == 3
    assert emb.name.startswith("openai-")


def test_gemini_embedder():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "embedContent" in request.url.path
        return httpx.Response(200, json={"embedding": {"values": [0.4, 0.5]}})

    emb = GeminiEmbedder(
        "https://generativelanguage.googleapis.com", "text-embedding-004",
        api_key="gem",
    )
    emb._client = httpx.Client(
        base_url="https://generativelanguage.googleapis.com",
        transport=httpx.MockTransport(handler),
    )
    assert emb.embed("hi") == [0.4, 0.5]
    assert emb.name.startswith("gemini-")


def test_get_embedder_for_config_hash(monkeypatch):
    monkeypatch.setenv("TWIN_EMBEDDER", "hash")
    cfg = Config()
    emb = get_embedder_for_config(cfg)
    assert emb.name.startswith("hash-")


def test_get_chat_client_ollama_default(monkeypatch):
    monkeypatch.delenv("TWIN_LLM_PROVIDER", raising=False)
    cfg = Config()
    chat = get_chat_client(cfg)
    assert chat.name.startswith("ollama:")
    chat.close()


def test_get_chat_client_anthropic(monkeypatch):
    monkeypatch.setenv("TWIN_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    cfg = Config()
    chat = get_chat_client(cfg)
    assert chat.name.startswith("anthropic:")
    chat.close()


def test_setup_wizard_noninteractive_openai(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("TWIN_LLM_BASE_URL", "http://127.0.0.1:9/v1")
    cfg = load_config(tmp_path)
    lines = run_setup_wizard(cfg, interactive=False)
    assert any("openai_compatible" in line for line in lines)


def test_setup_wizard_noninteractive_anthropic(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_LLM_PROVIDER", "anthropic")
    cfg = load_config(tmp_path)
    lines = run_setup_wizard(cfg, interactive=False)
    assert any("anthropic" in line for line in lines)


def test_setup_wizard_noninteractive_ollama(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("TWIN_OLLAMA_URL", "http://127.0.0.1:9")
    cfg = load_config(tmp_path)
    lines = run_setup_wizard(cfg, interactive=False)
    assert any("ollama" in line for line in lines)
