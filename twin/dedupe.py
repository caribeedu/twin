"""Deduplication and contradiction hints for candidate memories.

MVP policy:
- cosine >= 0.92 against an existing memory of the same type → duplicate:
  skip the new memory, attach its evidence to the existing one.
- 0.80 <= cosine < 0.92 with the same type → possibly an update or a
  contradiction: keep the new memory but flag it for review and record a
  ``related_to`` relation so the review UI can show both side by side.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .db import Database
from .embeddings import Embedder, cosine, from_blob

DUPLICATE_THRESHOLD = 0.92
RELATED_THRESHOLD = 0.80


@dataclass
class DedupeVerdict:
    action: str  # "insert" | "duplicate" | "review"
    existing_id: Optional[str] = None
    similarity: float = 0.0


def check(db: Database, embedder: Embedder, mem_type: str, text: str) -> DedupeVerdict:
    vector = embedder.embed(text)
    best_id: Optional[str] = None
    best_sim = 0.0
    for ref_id, blob in db.iter_embeddings("memory"):
        existing = db.get_memory(ref_id)
        if existing is None or existing.type.value != mem_type:
            continue
        if existing.status.value in ("rejected", "deprecated"):
            continue
        sim = cosine(vector, from_blob(blob))
        if sim > best_sim:
            best_sim = sim
            best_id = ref_id
    if best_id and best_sim >= DUPLICATE_THRESHOLD:
        return DedupeVerdict(action="duplicate", existing_id=best_id, similarity=best_sim)
    if best_id and best_sim >= RELATED_THRESHOLD:
        return DedupeVerdict(action="review", existing_id=best_id, similarity=best_sim)
    return DedupeVerdict(action="insert", similarity=best_sim)
