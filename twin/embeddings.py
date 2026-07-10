"""Pluggable embeddings with a zero-dependency local default.

The default ``HashEmbedder`` is a deterministic hashed bag-of-words with
character n-grams — not state of the art, but fully local, instant, and good
enough for MVP-scale hybrid search where FTS carries most of the precision.
Embeddings are regenerable, so swapping in ``sentence-transformers`` later is
a config change plus a reindex (a design goal: no vendor lock-in).
"""

from __future__ import annotations

import hashlib
import math
import re
import struct
from typing import Protocol

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


class SentenceTransformerEmbedder:
    """Optional higher-quality local embedder (pip install sentence-transformers)."""

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        from sentence_transformers import SentenceTransformer  # lazy import

        self._model = SentenceTransformer(model_name)
        self.dim = self._model.get_sentence_embedding_dimension()
        self.name = f"st-{model_name}"

    def embed(self, text: str) -> list[float]:
        return self._model.encode(text, normalize_embeddings=True).tolist()


def get_embedder(kind: str = "hash", dim: int = 512) -> Embedder:
    if kind == "sentence-transformers":
        return SentenceTransformerEmbedder()
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
