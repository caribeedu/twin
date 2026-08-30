"""Pluggable chat LLM clients for interpreter + deep observer.

Mainstream providers (Ollama remains the encouraged local default):

- ``ollama`` — local open models
- ``openai_compatible`` — OpenAI, Azure OpenAI, Groq, Together, Fireworks,
  OpenRouter, DeepSeek, Mistral, xAI, LM Studio, vLLM, …
- ``anthropic`` — Claude via Anthropic Messages API
- ``gemini`` — Google Gemini generateContent API

Aliases like ``claude``, ``openai``, ``groq``, ``openrouter`` normalize to
the right adapter + default base URL.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from ..config import Config

# Presets: kind is the adapter; base is the default HTTP origin.
PROVIDER_PRESETS: dict[str, dict[str, Any]] = {
    "ollama": {
        "kind": "ollama",
        "base": "http://127.0.0.1:11434",
        "default_model": "qwen3.6:latest",
        "key_envs": (),
    },
    "openai": {
        "kind": "openai_compatible",
        "base": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "key_envs": ("OPENAI_API_KEY", "TWIN_LLM_API_KEY"),
    },
    "openai_compatible": {
        "kind": "openai_compatible",
        "base": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "key_envs": ("OPENAI_API_KEY", "TWIN_LLM_API_KEY"),
    },
    "azure_openai": {
        "kind": "openai_compatible",
        "base": "",  # must be set by user (resource URL)
        "default_model": "gpt-4o-mini",
        "key_envs": ("AZURE_OPENAI_API_KEY", "OPENAI_API_KEY", "TWIN_LLM_API_KEY"),
        "auth": "api_key",
    },
    "anthropic": {
        "kind": "anthropic",
        "base": "https://api.anthropic.com",
        "default_model": "claude-sonnet-4-20250514",
        "key_envs": ("ANTHROPIC_API_KEY", "TWIN_LLM_API_KEY"),
    },
    "claude": {
        "kind": "anthropic",
        "base": "https://api.anthropic.com",
        "default_model": "claude-sonnet-4-20250514",
        "key_envs": ("ANTHROPIC_API_KEY", "TWIN_LLM_API_KEY"),
    },
    "gemini": {
        "kind": "gemini",
        "base": "https://generativelanguage.googleapis.com",
        "default_model": "gemini-2.0-flash",
        "key_envs": ("GEMINI_API_KEY", "GOOGLE_API_KEY", "TWIN_LLM_API_KEY"),
    },
    "google": {
        "kind": "gemini",
        "base": "https://generativelanguage.googleapis.com",
        "default_model": "gemini-2.0-flash",
        "key_envs": ("GEMINI_API_KEY", "GOOGLE_API_KEY", "TWIN_LLM_API_KEY"),
    },
    "groq": {
        "kind": "openai_compatible",
        "base": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "key_envs": ("GROQ_API_KEY", "TWIN_LLM_API_KEY"),
    },
    "together": {
        "kind": "openai_compatible",
        "base": "https://api.together.xyz/v1",
        "default_model": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        "key_envs": ("TOGETHER_API_KEY", "TWIN_LLM_API_KEY"),
    },
    "fireworks": {
        "kind": "openai_compatible",
        "base": "https://api.fireworks.ai/inference/v1",
        "default_model": "accounts/fireworks/models/llama-v3p1-70b-instruct",
        "key_envs": ("FIREWORKS_API_KEY", "TWIN_LLM_API_KEY"),
    },
    "openrouter": {
        "kind": "openai_compatible",
        "base": "https://openrouter.ai/api/v1",
        "default_model": "anthropic/claude-sonnet-4",
        "key_envs": ("OPENROUTER_API_KEY", "TWIN_LLM_API_KEY"),
    },
    "deepseek": {
        "kind": "openai_compatible",
        "base": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "key_envs": ("DEEPSEEK_API_KEY", "TWIN_LLM_API_KEY"),
    },
    "mistral": {
        "kind": "openai_compatible",
        "base": "https://api.mistral.ai/v1",
        "default_model": "mistral-small-latest",
        "key_envs": ("MISTRAL_API_KEY", "TWIN_LLM_API_KEY"),
    },
    "xai": {
        "kind": "openai_compatible",
        "base": "https://api.x.ai/v1",
        "default_model": "grok-2-latest",
        "key_envs": ("XAI_API_KEY", "TWIN_LLM_API_KEY"),
    },
    "lmstudio": {
        "kind": "openai_compatible",
        "base": "http://127.0.0.1:1234/v1",
        "default_model": "local-model",
        "key_envs": (),
    },
    "vllm": {
        "kind": "openai_compatible",
        "base": "http://127.0.0.1:8000/v1",
        "default_model": "local-model",
        "key_envs": (),
    },
}

_ALIAS_TO_PRESET = {
    "local": "ollama",
    "openai_compat": "openai_compatible",
    "azure": "azure_openai",
    "chatgpt": "openai",
    "gpt": "openai",
    "google_ai": "gemini",
    "google_genai": "gemini",
}


class ChatClient(Protocol):
    name: str
    model: str

    def available(self) -> bool: ...

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        temperature: float = 0.1,
    ) -> dict[str, Any]: ...


def normalize_provider(value: str) -> str:
    """Return a preset key (ollama, anthropic, gemini, openai, groq, …)."""
    v = (value or "ollama").strip().lower().replace("-", "_")
    v = _ALIAS_TO_PRESET.get(v, v)
    if v in PROVIDER_PRESETS:
        return v
    # Unknown names: treat as openai-compatible custom endpoint
    if v in ("openai_compatible",):
        return "openai_compatible"
    return v if v else "ollama"


def provider_kind(value: str) -> str:
    """Return adapter kind: ollama | openai_compatible | anthropic | gemini."""
    preset = PROVIDER_PRESETS.get(normalize_provider(value))
    if preset:
        return preset["kind"]
    return "openai_compatible"


def parse_model_json(content: str) -> dict[str, Any]:
    """Parse structured-output JSON; tolerate think-tags / markdown fences."""
    import re

    raw = (content or "").strip()
    if not raw:
        raise json.JSONDecodeError("empty model content", raw, 0)

    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r"<thinking>.*?</thinking>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r"```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = raw.replace("```", "").strip()

    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        data = json.loads(raw[start : end + 1])
        if isinstance(data, dict):
            return data
    raise json.JSONDecodeError("no JSON object in model content", raw, 0)


def _http_error(provider: str, resp) -> RuntimeError:
    """A verbose HTTP error that carries the provider's own error body.

    A bare ``raise_for_status()`` says only "404 Not Found"; the response body
    usually names the real cause (e.g. an invalid model id or a bad key), which
    is exactly what a caller needs to fix an analysis-model misconfiguration.
    """
    snippet = ""
    try:
        snippet = (resp.text or "")[:400].replace("\n", " ").strip()
    except Exception:
        pass
    code = getattr(resp, "status_code", "?")
    return RuntimeError(f"{provider} HTTP {code}: {snippet}" if snippet
                        else f"{provider} HTTP {code}")


def _close_client(owns: bool, client) -> None:
    if owns and client is not None:
        try:
            client.close()
        except Exception:
            pass


class OllamaChatClient:
    def __init__(self, base_url: str, model: str, client=None, timeout: float = 600):
        import httpx

        self.base_url = base_url.rstrip("/")
        self.model = model
        self.name = f"ollama:{model}"
        self._owns = client is None
        self._client = client or httpx.Client(base_url=self.base_url, timeout=timeout)

    def available(self) -> bool:
        from twin.store.embeddings import ollama_reachable
        return ollama_reachable(self.base_url)

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        import time as _time

        from .usage import emit_usage

        payload = {
            "model": self.model,
            "stream": False,
            "format": schema,
            "think": False,
            "options": {"temperature": temperature},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        _t0 = _time.perf_counter()
        try:
            resp = self._client.post("/api/chat", json=payload)
            if resp.status_code >= 400:
                raise _http_error(self.name, resp)
            body = resp.json()
            message = body.get("message") or {}
            content = message.get("content") or ""
            if not content.strip() and isinstance(message.get("thinking"), str):
                content = message.get("thinking") or ""
            result = parse_model_json(content)
            emit_usage(kind="ollama", model=self.model, body=body, started=_t0)
            return result
        except Exception as exc:
            emit_usage(kind="ollama", model=self.model, body=None,
                       started=_t0, ok=False, extra={"error": str(exc)[:200]})
            raise

    def close(self) -> None:
        _close_client(self._owns, self._client)


class OpenAICompatChatClient:
    """OpenAI Chat Completions API (and compatible local/cloud servers)."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        client=None,
        timeout: float = 600,
        *,
        auth: str = "bearer",
        label: str = "openai_compatible",
    ):
        import httpx

        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.name = f"{label}:{model}"
        self._owns = client is None
        headers = {"Content-Type": "application/json"}
        if api_key:
            if auth == "api_key":
                headers["api-key"] = api_key
            else:
                headers["Authorization"] = f"Bearer {api_key}"
        self._client = client or httpx.Client(
            base_url=self.base_url, timeout=timeout, headers=headers,
        )

    def available(self) -> bool:
        import httpx

        probe = "/models" if self.base_url.rstrip("/").endswith("/v1") else "/v1/models"
        try:
            r = self._client.get(probe, timeout=3.0)
            return r.status_code < 500
        except httpx.HTTPError:
            try:
                r = self._client.get("/", timeout=3.0)
                return r.status_code < 500
            except httpx.HTTPError:
                return False

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        attempts = [
            {
                "type": "json_schema",
                "json_schema": {
                    "name": "twin_response",
                    "schema": schema,
                    "strict": False,
                },
            },
            {"type": "json_object"},
            None,  # plain prompt fallback
        ]
        import time as _time

        from .usage import emit_usage

        last_exc: Exception | None = None
        path = (
            "/chat/completions"
            if self.base_url.rstrip("/").endswith("/v1")
            else "/v1/chat/completions"
        )
        _t0 = _time.perf_counter()
        _requests = 0
        for fmt in attempts:
            _requests += 1
            if fmt is None:
                payload = {
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": system
                            + "\nRespond with a single JSON object only.",
                        },
                        {
                            "role": "user",
                            "content": user
                            + "\n\nJSON schema:\n"
                            + json.dumps(schema)[:4000],
                        },
                    ],
                    "temperature": temperature,
                }
            elif fmt.get("type") == "json_object":
                payload = {
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": system
                            + "\nRespond with JSON only matching the required schema.",
                        },
                        {
                            "role": "user",
                            "content": user
                            + "\n\nJSON schema:\n"
                            + json.dumps(schema)[:4000],
                        },
                    ],
                    "temperature": temperature,
                    "response_format": fmt,
                }
            else:
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "response_format": fmt,
                }
            try:
                resp = self._client.post(path, json=payload)
                if resp.status_code >= 400 and fmt is not None:
                    last_exc = _http_error(
                        f"{self.name} (format={fmt.get('type')})", resp,
                    )
                    continue
                if resp.status_code >= 400:
                    raise _http_error(self.name, resp)
                body = resp.json()
                content = (
                    ((body.get("choices") or [{}])[0].get("message") or {}).get("content")
                    or ""
                )
                result = parse_model_json(content)
                emit_usage(
                    kind="openai_compatible", model=self.model, body=body,
                    started=_t0, requests=_requests,
                )
                return result
            except Exception as exc:
                last_exc = exc
                if fmt is not None:
                    continue
                emit_usage(
                    kind="openai_compatible", model=self.model, body=None,
                    started=_t0, requests=_requests, ok=False,
                    extra={"error": str(exc)[:200]},
                )
                raise
        emit_usage(
            kind="openai_compatible", model=self.model, body=None,
            started=_t0, requests=_requests, ok=False,
            extra={"error": str(last_exc)[:200] if last_exc else "unknown"},
        )
        if last_exc:
            raise last_exc
        raise RuntimeError("openai_compatible chat failed")

    def close(self) -> None:
        _close_client(self._owns, self._client)


class AnthropicChatClient:
    """Anthropic Messages API (Claude)."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        client=None,
        timeout: float = 600,
    ):
        import httpx

        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.name = f"anthropic:{model}"
        self._owns = client is None
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if api_key:
            headers["x-api-key"] = api_key
        self._client = client or httpx.Client(
            base_url=self.base_url, timeout=timeout, headers=headers,
        )

    def available(self) -> bool:
        import httpx

        if not self.api_key:
            return False
        try:
            # Models list is enough as a reachability + auth probe.
            r = self._client.get("/v1/models", timeout=3.0)
            return r.status_code < 500
        except httpx.HTTPError:
            return bool(self.api_key)

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        import time as _time

        from .usage import emit_usage

        _t0 = _time.perf_counter()
        # Prefer tool-use structured output; fall back to JSON-in-text.
        tool_payload = {
            "model": self.model,
            "max_tokens": 8192,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [{
                "name": "twin_response",
                "description": "Return the structured Twin interpretation payload.",
                "input_schema": schema if schema.get("type") == "object" else {
                    "type": "object",
                    "properties": {"items": {"type": "array"}},
                    "additionalProperties": True,
                },
            }],
            "tool_choice": {"type": "tool", "name": "twin_response"},
        }
        try:
            resp = self._client.post("/v1/messages", json=tool_payload)
            if resp.status_code < 400:
                body = resp.json()
                for block in body.get("content") or []:
                    if block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
                        emit_usage(kind="anthropic", model=self.model,
                                   body=body, started=_t0)
                        return block["input"]
                # Unexpected shape — try text blocks
                texts = [
                    b.get("text", "") for b in (body.get("content") or [])
                    if b.get("type") == "text"
                ]
                if texts:
                    result = parse_model_json("\n".join(texts))
                    emit_usage(kind="anthropic", model=self.model,
                               body=body, started=_t0)
                    return result

            # Fallback: plain JSON instruction
            plain = {
                "model": self.model,
                "max_tokens": 8192,
                "temperature": temperature,
                "system": system + "\nRespond with a single JSON object only, no markdown.",
                "messages": [{
                    "role": "user",
                    "content": user + "\n\nJSON schema:\n" + json.dumps(schema)[:4000],
                }],
            }
            resp = self._client.post("/v1/messages", json=plain)
            if resp.status_code >= 400:
                raise _http_error(self.name, resp)
            body = resp.json()
            texts = [
                b.get("text", "") for b in (body.get("content") or [])
                if b.get("type") == "text"
            ]
            result = parse_model_json("\n".join(texts))
            emit_usage(kind="anthropic", model=self.model, body=body,
                       started=_t0, requests=2)
            return result
        except Exception as exc:
            emit_usage(kind="anthropic", model=self.model, body=None,
                       started=_t0, ok=False, extra={"error": str(exc)[:200]})
            raise

    def close(self) -> None:
        _close_client(self._owns, self._client)


class GeminiChatClient:
    """Google Gemini generateContent API."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        client=None,
        timeout: float = 600,
    ):
        import httpx

        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.name = f"gemini:{model}"
        self._owns = client is None
        self._client = client or httpx.Client(base_url=self.base_url, timeout=timeout)

    def _path(self, action: str) -> str:
        # models/gemini-2.0-flash:generateContent
        model = self.model
        if not model.startswith("models/"):
            model = f"models/{model}"
        return f"/v1beta/{model}:{action}"

    def available(self) -> bool:
        import httpx

        if not self.api_key:
            return False
        try:
            r = self._client.get(
                "/v1beta/models",
                params={"key": self.api_key},
                timeout=3.0,
            )
            return r.status_code < 500
        except httpx.HTTPError:
            return bool(self.api_key)

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{
                "role": "user",
                "parts": [{
                    "text": user
                    + "\n\nRespond with a single JSON object matching this schema:\n"
                    + json.dumps(schema)[:4000],
                }],
            }],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
            },
        }
        import time as _time

        from .usage import emit_usage

        _t0 = _time.perf_counter()
        try:
            resp = self._client.post(
                self._path("generateContent"),
                params={"key": self.api_key},
                json=payload,
            )
            if resp.status_code >= 400:
                raise _http_error(self.name, resp)
            body = resp.json()
            parts = (
                ((body.get("candidates") or [{}])[0].get("content") or {}).get("parts")
                or []
            )
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
            result = parse_model_json(text)
            emit_usage(kind="gemini", model=self.model, body=body, started=_t0)
            return result
        except Exception as exc:
            emit_usage(kind="gemini", model=self.model, body=None,
                       started=_t0, ok=False, extra={"error": str(exc)[:200]})
            raise

    def close(self) -> None:
        _close_client(self._owns, self._client)


def resolve_api_key(cfg: Config, preset_name: str | None = None) -> str:
    """Pick the first available API key for the provider preset."""
    if cfg.llm_api_key:
        return cfg.llm_api_key
    name = normalize_provider(preset_name or cfg.llm_provider)
    preset = PROVIDER_PRESETS.get(name, {})
    import os
    for env_name in preset.get("key_envs") or ():
        val = os.environ.get(env_name, "")
        if val:
            return val
    # Custom / unknown OpenAI-shaped endpoints still honor OPENAI_API_KEY.
    if not preset or provider_kind(name) == "openai_compatible":
        for env_name in ("OPENAI_API_KEY", "TWIN_LLM_API_KEY"):
            val = os.environ.get(env_name, "")
            if val:
                return val
    return ""


def get_chat_client(cfg: Config, *, client=None, timeout: float = 600) -> ChatClient:
    preset_name = normalize_provider(cfg.llm_provider)
    preset = PROVIDER_PRESETS.get(preset_name)
    if preset is None:
        # Unknown name → OpenAI-compatible custom gateway
        preset = {
            "kind": "openai_compatible",
            "base": "https://api.openai.com/v1",
            "default_model": "gpt-4o-mini",
            "auth": "bearer",
        }
        preset_name = "openai_compatible"
    kind = preset["kind"]
    model = cfg.resolved_llm_model or preset.get("default_model") or "gpt-4o-mini"
    base = cfg.resolved_llm_base_url or preset.get("base") or ""
    api_key = resolve_api_key(cfg, preset_name)
    auth = preset.get("auth", "bearer")

    if kind == "anthropic":
        return AnthropicChatClient(
            base or "https://api.anthropic.com", model, api_key=api_key,
            client=client, timeout=timeout,
        )
    if kind == "gemini":
        return GeminiChatClient(
            base or "https://generativelanguage.googleapis.com", model,
            api_key=api_key, client=client, timeout=timeout,
        )
    if kind == "openai_compatible":
        return OpenAICompatChatClient(
            base or "https://api.openai.com/v1", model, api_key=api_key,
            client=client, timeout=timeout, auth=auth, label=preset_name,
        )
    return OllamaChatClient(
        base or cfg.ollama_url, model, client=client, timeout=timeout,
    )


def llm_available(cfg: Config) -> bool:
    client = get_chat_client(cfg)
    try:
        return client.available()
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def list_wizard_providers() -> list[tuple[str, str]]:
    """Stable menu entries for twin init."""
    return [
        ("1", "Ollama — local open models (recommended)"),
        ("2", "OpenAI-compatible — OpenAI, Azure, Groq, OpenRouter, LM Studio, …"),
        ("3", "Anthropic — Claude"),
        ("4", "Google — Gemini"),
    ]
