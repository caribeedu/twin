"""Embeddings — local-first, pluggable, regenerable.

Backends:
- ``OllamaEmbedder`` (preferred local): Ollama ``/api/embed``
- ``OpenAICompatEmbedder``: OpenAI-compatible ``/v1/embeddings`` (cloud or local)
- ``GeminiEmbedder``: Google ``:embedContent``
- ``HashEmbedder`` (fallback): deterministic hashed bag-of-words; no server

Embeddings are tagged with the embedder name in the store, searches only
compare same-model vectors, and ``twin reindex`` regenerates everything —
so switching backends is a config change, never a data migration.
"""

from __future__ import annotations

import hashlib
import math
import re
import struct
from typing import TYPE_CHECKING, Protocol

_TOKEN_RE = re.compile(r"[\w-]+", re.UNICODE)

if TYPE_CHECKING:
    from ..config import Config


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, text: str) -> list[float]: ...


class HashEmbedder:
    def __init__(self, dim: int = 512):
        self.dim = dim
        self.name = f"hash-v1-{dim}"

    def _features(self, text: str) -> list[str]:
        tokens = [t.lower() for t in _TOKEN_RE.findall(text)]
        feats = list(tokens)
        feats += [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
        for t in tokens:
            if len(t) > 4:
                feats += [t[i:i + 3] for i in range(len(t) - 2)]
        return feats

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for feat in self._features(text):
            h = hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "little") % self.dim
            sign = 1.0 if h[4] & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


class OllamaEmbedder:
    """Local semantic embeddings via Ollama's /api/embed."""

    def __init__(self, base_url: str = "http://127.0.0.1:11434",
                 model: str = "nomic-embed-text", client=None):
        import httpx

        self.base_url = base_url.rstrip("/")
        self.model = model
        self.name = f"ollama-{model}"
        self._client = client or httpx.Client(base_url=self.base_url, timeout=120)
        self.dim = 0  # discovered on first embed

    def embed(self, text: str) -> list[float]:
        resp = self._client.post("/api/embed", json={"model": self.model, "input": text})
        resp.raise_for_status()
        vector = resp.json()["embeddings"][0]
        self.dim = len(vector)
        return vector


class OpenAICompatEmbedder:
    """OpenAI-compatible /v1/embeddings (OpenAI, LM Studio, vLLM, …)."""

    def __init__(
        self,
        base_url: str = "https://api.openai.com/v1",
        model: str = "text-embedding-3-small",
        api_key: str = "",
        client=None,
    ):
        import httpx

        self.base_url = base_url.rstrip("/")
        self.model = model
        self.name = f"openai-{model}"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = client or httpx.Client(
            base_url=self.base_url, timeout=120, headers=headers,
        )
        self.dim = 0

    def embed(self, text: str) -> list[float]:
        path = "/embeddings" if self.base_url.endswith("/v1") else "/v1/embeddings"
        resp = self._client.post(path, json={"model": self.model, "input": text})
        resp.raise_for_status()
        vector = resp.json()["data"][0]["embedding"]
        self.dim = len(vector)
        return vector


class GeminiEmbedder:
    """Google Gemini embedContent API."""

    def __init__(
        self,
        base_url: str = "https://generativelanguage.googleapis.com",
        model: str = "text-embedding-004",
        api_key: str = "",
        client=None,
    ):
        import httpx

        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.name = f"gemini-{model}"
        self._client = client or httpx.Client(base_url=self.base_url, timeout=120)
        self.dim = 0

    def embed(self, text: str) -> list[float]:
        model = self.model
        if not model.startswith("models/"):
            model = f"models/{model}"
        resp = self._client.post(
            f"/v1beta/{model}:embedContent",
            params={"key": self.api_key},
            json={"model": model, "content": {"parts": [{"text": text}]}},
        )
        resp.raise_for_status()
        vector = resp.json()["embedding"]["values"]
        self.dim = len(vector)
        return vector


def sanitize_base_url(base_url: str) -> str:
    """Strip whitespace and terminal/env junk that breaks httpx URL parsing.

    WSL and mis-decoded ``.env`` values sometimes inject UTF-16 surrogates
    (e.g. ``\\udcc3`` from a lone ``0xC3`` byte). Those are not valid in a
    URL and raise ``UnicodeEncodeError`` inside httpx before any request.
    """
    text = (base_url or "").strip()
    return "".join(
        ch for ch in text
        if ch.isprintable() and not (0xD800 <= ord(ch) <= 0xDFFF)
    ).strip()


def ollama_reachable(base_url: str, timeout: float = 1.5) -> bool:
    import httpx

    base = sanitize_base_url(base_url).rstrip("/")
    if not base:
        return False
    try:
        return httpx.get(f"{base}/api/tags", timeout=timeout).status_code == 200
    except Exception:
        # Probe helper: network, timeout, bad URL, TLS — never crash callers
        # (twin init / doctor). httpx.HTTPError alone misses UnicodeEncodeError.
        return False


def openai_compat_reachable(base_url: str, api_key: str = "", timeout: float = 1.5) -> bool:
    import httpx

    base = sanitize_base_url(base_url).rstrip("/")
    if not base:
        return False
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    probe = f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"
    try:
        return httpx.get(probe, headers=headers, timeout=timeout).status_code < 500
    except Exception:
        return False


def get_embedder(kind: str = "auto", dim: int = 512,
                 ollama_url: str = "http://127.0.0.1:11434",
                 ollama_model: str = "nomic-embed-text",
                 client=None,
                 *,
                 base_url: str | None = None,
                 model: str | None = None,
                 api_key: str = "") -> Embedder:
    kind_n = (kind or "auto").strip().lower().replace("-", "_")
    if kind_n in ("openai", "openai_compatible"):
        return OpenAICompatEmbedder(
            base_url or "https://api.openai.com/v1",
            model or "text-embedding-3-small",
            api_key=api_key,
            client=client,
        )
    if kind_n == "gemini":
        return GeminiEmbedder(
            base_url or "https://generativelanguage.googleapis.com",
            model or "text-embedding-004",
            api_key=api_key,
            client=client,
        )
    if kind_n == "ollama":
        return OllamaEmbedder(base_url or ollama_url, model or ollama_model, client=client)
    if kind_n == "hash":
        return HashEmbedder(dim=dim)
    # auto
    url = base_url or ollama_url
    emb_model = model or ollama_model
    if api_key and "generativelanguage.googleapis.com" in url:
        return GeminiEmbedder(url, emb_model, api_key=api_key, client=client)
    if api_key and openai_compat_reachable(url, api_key):
        return OpenAICompatEmbedder(url, emb_model, api_key=api_key, client=client)
    if ollama_reachable(url):
        return OllamaEmbedder(url, emb_model, client=client)
    return HashEmbedder(dim=dim)


def get_embedder_for_config(cfg: "Config", client=None) -> Embedder:
    kind = (cfg.embedder or "auto").strip().lower().replace("-", "_")
    llm_kind = cfg.llm_provider_kind
    if kind in ("openai", "openai_compatible"):
        return OpenAICompatEmbedder(
            cfg.resolved_embed_base_url,
            cfg.resolved_embed_model,
            api_key=cfg.resolved_embed_api_key,
            client=client,
        )
    if kind == "gemini":
        return GeminiEmbedder(
            cfg.resolved_embed_base_url,
            cfg.resolved_embed_model,
            api_key=cfg.resolved_embed_api_key,
            client=client,
        )
    if kind == "ollama":
        return OllamaEmbedder(
            cfg.resolved_embed_base_url, cfg.resolved_embed_model, client=client,
        )
    if kind == "hash":
        return HashEmbedder(dim=cfg.embedding_dim)
    # auto — follow chat provider when it has native embeddings
    if llm_kind == "gemini":
        return GeminiEmbedder(
            cfg.resolved_embed_base_url,
            cfg.resolved_embed_model,
            api_key=cfg.resolved_embed_api_key,
            client=client,
        )
    if llm_kind == "openai_compatible":
        if openai_compat_reachable(
            cfg.resolved_embed_base_url, cfg.resolved_embed_api_key,
        ):
            return OpenAICompatEmbedder(
                cfg.resolved_embed_base_url,
                cfg.resolved_embed_model,
                api_key=cfg.resolved_embed_api_key,
                client=client,
            )
        return HashEmbedder(dim=cfg.embedding_dim)
    # anthropic has no embeddings API — prefer local Ollama, else hash
    if ollama_reachable(cfg.ollama_url):
        return OllamaEmbedder(
            cfg.ollama_url, cfg.resolved_embed_model, client=client,
        )
    return HashEmbedder(dim=cfg.embedding_dim)


def to_blob(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def from_blob(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
