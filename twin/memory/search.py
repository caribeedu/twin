"""Hybrid search: full-text + vector similarity + graph boost, filtered by
the Judgment layer's Domain Firewall."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..clock import now_iso
from ..judgment.firewall import Firewall
from .embeddings import Embedder
from .models import INACTIVE_STATUSES, MemoryItem, MemoryStatus
from .store.base import MemoryStore

FTS_WEIGHT = 0.55
VECTOR_WEIGHT = 0.35
ENTITY_WEIGHT = 0.10
# Soft boost for a hit that already lives in the consumer's domain. Small
# enough that a strong cross-domain match still surfaces, large enough to win
# ties in favour of the domain the caller is actually working in.
DOMAIN_AFFINITY_WEIGHT = 0.15


@dataclass
class SearchHit:
    memory: MemoryItem
    score: float
    why: str


@dataclass
class BlockedHit:
    memory_id: str
    rule: str
    reason: str


@dataclass
class SearchResult:
    hits: list[SearchHit]
    blocked: list[BlockedHit]


def _entity_boost(query: str, memory: MemoryItem) -> float:
    q = query.lower()
    return 1.0 if any(e.lower() in q for e in memory.entities) else 0.0


def search(
    store: MemoryStore,
    embedder: Embedder,
    query: str,
    target_domain: str = "technical",
    firewall: Optional[Firewall] = None,
    type_: Optional[str] = None,
    limit: int = 10,
    include_candidates: bool = True,
    include_rejected: bool = False,
    domain_affinity: Optional[str] = None,
) -> SearchResult:
    fts_scores = store.fts_search(query, limit=100)
    query_vec = embedder.embed(query)
    vec_scores = store.similar(query_vec, "memory", embedder.name)

    candidate_ids = set(fts_scores) | set(vec_scores)
    if not candidate_ids:
        return SearchResult(hits=[], blocked=[])

    # normalize FTS scores to 0..1
    if fts_scores:
        max_fts = max(fts_scores.values())
        min_fts = min(fts_scores.values())
        span = (max_fts - min_fts) or 1.0
        fts_norm = {k: (v - min_fts) / span for k, v in fts_scores.items()}
    else:
        fts_norm = {}

    hits: list[SearchHit] = []
    blocked: list[BlockedHit] = []
    as_of = now_iso()

    for mem_id in candidate_ids:
        memory = store.get_memory(mem_id)
        if memory is None:
            continue
        st = memory.status.value
        if st in INACTIVE_STATUSES:
            # Reflect/consolidation may want rejected as *negative* context;
            # other inactive statuses stay out of default search.
            if not (include_rejected and st == MemoryStatus.rejected.value):
                continue
        if not include_candidates and st != MemoryStatus.confirmed.value:
            if not (include_rejected and st == MemoryStatus.rejected.value):
                continue
        if type_ and memory.type.value != type_:
            continue

        if firewall is not None:
            verdict = firewall.evaluate(memory, target_domain, as_of=as_of)
            if not verdict.allowed:
                blocked.append(BlockedHit(memory_id=mem_id, rule=verdict.rule, reason=verdict.reason))
                continue

        score = (
            FTS_WEIGHT * fts_norm.get(mem_id, 0.0)
            + VECTOR_WEIGHT * vec_scores.get(mem_id, 0.0)
            + ENTITY_WEIGHT * _entity_boost(query, memory)
        )
        same_domain = bool(domain_affinity) and memory.domain == domain_affinity
        if same_domain:
            score += DOMAIN_AFFINITY_WEIGHT
        why_parts = []
        if mem_id in fts_norm:
            why_parts.append("text match")
        if vec_scores.get(mem_id, 0) > 0.2:
            why_parts.append("semantic similarity")
        if _entity_boost(query, memory):
            why_parts.append("entity match")
        if same_domain:
            why_parts.append("same-domain")
        if st == MemoryStatus.rejected.value:
            why_parts.append("rejected")
        hits.append(SearchHit(memory=memory, score=round(score, 4), why=", ".join(why_parts) or "weak match"))

    hits.sort(key=lambda h: h.score, reverse=True)
    return SearchResult(hits=hits[:limit], blocked=blocked)
