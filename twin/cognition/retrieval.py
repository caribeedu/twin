"""Multi-stage retrieval pipeline.

Retrieval is an explicit pipeline rather than one opaque score:

    project/domain/task detection   (caller / observer)
        ↓
    lexical + vector candidate generation
        ↓
    graph expansion and temporal filtering
        ↓
    Domain Firewall and source-trust weighting
        ↓
    local reranking (optional)
        ↓
    task-aware context construction (context_pack)

The deterministic hybrid search remains the baseline and the fallback: with
no project, no reranker and default weights, this pipeline reduces to it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from ..clock import now_iso
from ..judgment.firewall import Firewall
from ..memory.embeddings import Embedder
from ..memory.models import MemoryItem
from ..memory.search import BlockedHit, SearchHit, SearchResult, search
from ..memory.store.base import MemoryStore

PROJECT_BOOST = 0.15        # additive score for memories linked to the active project
GRAPH_EXPANSION_SCORE = 0.1  # base score for memories pulled in via the graph
TRUST_FLOOR = 0.5            # score multiplier range: TRUST_FLOOR..1.0 by confidence

# A reranker takes (query, hits) and returns the hits reordered.
Reranker = Callable[[str, list[SearchHit]], list[SearchHit]]


@dataclass
class RetrievalResult:
    hits: list[SearchHit]
    blocked: list[BlockedHit]
    stages: dict[str, int] = field(default_factory=dict)  # stage → candidate count


def _graph_expand(store: MemoryStore, hits: list[SearchHit],
                  limit: int) -> list[MemoryItem]:
    """Pull in memories sharing entities with the current top hits — context
    the lexical/vector stage missed but the graph knows is adjacent."""
    seen = {h.memory.id for h in hits}
    expanded: list[MemoryItem] = []
    for hit in hits[:5]:
        for name in hit.memory.entities[:5]:
            entity = store.get_entity_by_name(name)
            if entity is None:
                continue
            for mem in store.memories_for_entity(entity.id)[:10]:
                if mem.id in seen:
                    continue
                if mem.status.value in ("rejected", "deprecated", "contradicted"):
                    continue
                seen.add(mem.id)
                expanded.append(mem)
                if len(expanded) >= limit:
                    return expanded
    return expanded


def _avg_source_trust(store: MemoryStore, mem: MemoryItem) -> float:
    trusts = []
    for pid in mem.percept_ids[:5]:
        percept = store.get_percept(pid)
        if percept is not None:
            trusts.append(percept.source_trust)
    return sum(trusts) / len(trusts) if trusts else 0.8


def retrieve(
    store: MemoryStore,
    embedder: Embedder,
    query: str,
    target_domain: str = "technical",
    firewall: Optional[Firewall] = None,
    project_id: Optional[str] = None,
    limit: int = 20,
    include_candidates: bool = False,
    reranker: Optional[Reranker] = None,
) -> RetrievalResult:
    stages: dict[str, int] = {}

    # 1-2. lexical + vector candidate generation (deterministic baseline)
    base = search(store, embedder, query, target_domain=target_domain,
                  firewall=firewall, limit=max(limit * 2, 20),
                  include_candidates=include_candidates)
    hits = list(base.hits)
    blocked = list(base.blocked)
    stages["candidates"] = len(hits)

    # 3. graph expansion + temporal filtering
    as_of = now_iso()
    for mem in _graph_expand(store, hits, limit=10):
        if not include_candidates and mem.status.value != "confirmed":
            continue
        if firewall is not None:
            verdict = firewall.evaluate(mem, target_domain, as_of=as_of)
            if not verdict.allowed:
                blocked.append(BlockedHit(memory_id=mem.id, rule=verdict.rule,
                                          reason=verdict.reason))
                continue
        hits.append(SearchHit(memory=mem, score=GRAPH_EXPANSION_SCORE,
                              why="graph expansion"))
    hits = [h for h in hits
            if not (h.memory.valid_until and h.memory.valid_until < as_of)]
    stages["after_graph"] = len(hits)

    # 4. source-trust weighting + project boost
    for hit in hits:
        trust = _avg_source_trust(store, hit.memory)
        hit.score = round(hit.score * (TRUST_FLOOR + (1 - TRUST_FLOOR) * trust), 4)
        if project_id and hit.memory.project_id == project_id:
            hit.score = round(hit.score + PROJECT_BOOST, 4)
            hit.why = f"{hit.why}, project match"
    hits.sort(key=lambda h: h.score, reverse=True)
    stages["after_weighting"] = len(hits)

    # 5. local reranking (optional, off by default)
    if reranker is not None:
        try:
            hits = reranker(query, hits)
        except Exception:
            pass  # reranker is best-effort; the deterministic order stands
    stages["final"] = min(len(hits), limit)

    return RetrievalResult(hits=hits[:limit], blocked=blocked, stages=stages)
