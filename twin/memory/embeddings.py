"""Embeddings — local-first, pluggable, regenerable.

Backends:
- ``OllamaEmbedder`` (preferred): real semantic embeddings from a local
  Ollama server (default model ``nomic-embed-text``). Nothing leaves the
  machine.
- ``HashEmbedder`` (fallback): deterministic hashed bag-of-words with
  n-grams; zero dependencies, works with no server running.

Embeddings are tagged with the embedder name in the store, searches only
compare same-model vectors, and ``twin reindex`` regenerates everything —
so switching backends is a config change, never a data migration.
"""

from __future__ import annotations

import hashlib
import math
import re
import struct
from typing import Optional, Protocol

_TOKEN_RE = re.compile(r"[\w-]+", re.UNICODE)


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
        # word bigrams add a bit of phrase sensitivity
        feats += [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
        # character trigrams help with morphology (pt-BR inflections)
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


def ollama_reachable(base_url: str, timeout: float = 1.5) -> bool:
    import httpx

    try:
        return httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=timeout).status_code == 200
    except httpx.HTTPError:
        return False


def get_embedder(kind: str = "auto", dim: int = 512,
                 ollama_url: str = "http://127.0.0.1:11434",
                 ollama_model: str = "nomic-embed-text",
                 client=None) -> Embedder:
    if kind == "ollama":
        return OllamaEmbedder(ollama_url, ollama_model, client=client)
    if kind == "auto" and ollama_reachable(ollama_url):
        return OllamaEmbedder(ollama_url, ollama_model, client=client)
    return HashEmbedder(dim=dim)


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
