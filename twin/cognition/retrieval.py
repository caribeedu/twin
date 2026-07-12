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

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..clock import now_iso
from ..judgment.firewall import Firewall
from ..memory.embeddings import Embedder
from ..memory.models import MemoryItem
from ..memory.search import BlockedHit, SearchHit, SearchResult, search
from ..memory.store.base import MemoryStore

logger = logging.getLogger("twin.cognition.retrieval")

PROJECT_BOOST = 0.15        # additive score for memories linked to the active project
TRUST_FLOOR = 0.5            # score multiplier range: TRUST_FLOOR..1.0 by confidence

# Graph expansion scoring: the pulled-in memory inherits a fraction of the
# origin hit's score, damped by how specific the shared entity is — an
# entity attached to 3 memories is a strong signal, one attached to 80
# (a language, a person's name) is nearly no signal at all.
GRAPH_ORIGIN_SHARE = 0.5     # fraction of the origin score inherited
GRAPH_SPECIFIC_DEGREE = 4    # entities with ≤ this many memories count fully
GRAPH_MIN_SCORE = 0.02       # expansions damped below this are dropped

# A reranker takes (query, hits) and returns the hits reordered.
Reranker = Callable[[str, list[SearchHit]], list[SearchHit]]


@dataclass
class RetrievalResult:
    hits: list[SearchHit]
    blocked: list[BlockedHit]
    stages: dict[str, int] = field(default_factory=dict)  # stage → candidate count
    diagnostics: dict = field(default_factory=dict)  # fallback visibility — never content


@dataclass
class _Expansion:
    memory: MemoryItem
    score: float
    via_entity: str


def _graph_expand(store: MemoryStore, hits: list[SearchHit],
                  limit: int) -> list[_Expansion]:
    """Pull in memories sharing entities with the current top hits — context
    the lexical/vector stage missed but the graph knows is adjacent.

    Relevance is not assumed from mere co-mention: the expansion score is a
    fraction of the origin hit's score scaled by entity specificity, and
    ``why`` records which entity carried the connection."""
    seen = {h.memory.id for h in hits}
    expanded: list[_Expansion] = []
    for hit in hits[:5]:
        for name in hit.memory.entities[:5]:
            entity = store.get_entity_by_name(name)
            if entity is None:
                continue
            adjacent = store.memories_for_entity(entity.id)
            specificity = min(1.0, GRAPH_SPECIFIC_DEGREE / max(len(adjacent), 1))
            score = round(hit.score * GRAPH_ORIGIN_SHARE * specificity, 4)
            if score < GRAPH_MIN_SCORE:
                continue  # too broad an entity / too weak an origin to trust
            for mem in adjacent[:10]:
                if mem.id in seen:
                    continue
                if mem.status.value in ("rejected", "deprecated", "contradicted"):
                    continue
                seen.add(mem.id)
                expanded.append(_Expansion(memory=mem, score=score, via_entity=name))
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
    for exp in _graph_expand(store, hits, limit=10):
        mem = exp.memory
        if not include_candidates and mem.status.value != "confirmed":
            continue
        if firewall is not None:
            verdict = firewall.evaluate(mem, target_domain, as_of=as_of)
            if not verdict.allowed:
                blocked.append(BlockedHit(memory_id=mem.id, rule=verdict.rule,
                                          reason=verdict.reason))
                continue
        hits.append(SearchHit(memory=mem, score=exp.score,
                              why=f"graph expansion via {exp.via_entity}"))
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

    # 5. local reranking (optional, off by default). The deterministic order
    # is the fallback, but a failure is diagnosed and logged — a permanently
    # broken reranker must not masquerade as a working pipeline.
    diagnostics: dict = {}
    if reranker is not None:
        try:
            hits = reranker(query, hits)
            diagnostics["reranker"] = {"attempted": True, "succeeded": True}
        except Exception as exc:
            diagnostics["reranker"] = {
                "attempted": True, "succeeded": False,
                "error_type": type(exc).__name__,  # type only — never content
            }
            logger.warning("reranker failed (%s); deterministic order stands",
                           type(exc).__name__)
    stages["final"] = min(len(hits), limit)

    return RetrievalResult(hits=hits[:limit], blocked=blocked, stages=stages,
                           diagnostics=diagnostics)
