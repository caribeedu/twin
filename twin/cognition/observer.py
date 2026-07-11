"""Memory Observer — attention.

Watches the user's current text (a message, a task, a draft) and suggests
relevant memories without ever answering the user itself.

Flow: infer probable domain → search candidates → firewall filter → rank →
return a compact suggestion payload (suggested_context / blocked_context).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ..config import Config
from ..judgment.firewall import Firewall
from ..memory.embeddings import Embedder
from ..memory.search import search
from ..memory.store.base import MemoryStore

_DOMAIN_HINTS: list[tuple[str, list[str]]] = [
    ("technical", [
        "arquitetura", "architecture", "deploy", "api", "banco", "database",
        "código", "code", "bug", "refactor", "rfc", "backend", "frontend",
        "infra", "docker", "kubernetes", "migração", "migration", "stack",
    ]),
    ("work", [
        "reunião", "meeting", "sprint", "prazo", "deadline", "cliente", "client",
        "equipe", "team", "entrega", "roadmap", "stakeholder", "1:1", "okr",
    ]),
    ("assistant_preferences", [
        "responda", "responder", "answer me", "tom de voz", "formato de resposta",
        "explique como", "assistant", "assistente",
    ]),
]


@dataclass
class ObserverSuggestion:
    suggested_context: list[dict] = field(default_factory=list)
    blocked_context: list[dict] = field(default_factory=list)
    inferred_domain: str = "technical"


_CANDIDATE_ENTITY_RE = re.compile(r"\b[A-Z][a-zA-Z0-9]{2,}(?:\s+[A-Z][a-zA-Z0-9]+)*\b")


def _graph_domain_votes(store: MemoryStore, text: str) -> dict[str, int]:
    """Entities mentioned in the text vote with the domains of the memories
    they are attached to (README §27.5: inference informed by the graph,
    not just keywords)."""
    votes: dict[str, int] = {}
    seen: set[str] = set()
    for match in _CANDIDATE_ENTITY_RE.finditer(text):
        name = match.group(0)
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        entity = store.get_entity_by_name(name)
        if entity is None:
            continue
        for mem in store.memories_for_entity(entity.id)[:20]:
            if mem.status.value in ("rejected", "deprecated", "contradicted"):
                continue
            votes[mem.domain] = votes.get(mem.domain, 0) + 1
    return votes


def infer_domain(text: str, store: Optional[MemoryStore] = None) -> str:
    """Keyword hints + (when a store is given) domain votes from the graph."""
    lowered = text.lower()
    scores: dict[str, float] = {}
    for domain, keywords in _DOMAIN_HINTS:
        hits = sum(1 for kw in keywords if re.search(rf"\b{re.escape(kw)}\b", lowered))
        if hits:
            scores[domain] = scores.get(domain, 0.0) + float(hits)
    if store is not None:
        graph_votes = _graph_domain_votes(store, text)
        total = sum(graph_votes.values())
        if total:
            # graph signal is capped at the weight of ~2 keyword hits so a
            # heavily-populated domain can't drown explicit wording
            for domain, count in graph_votes.items():
                scores[domain] = scores.get(domain, 0.0) + 2.0 * (count / total)
    if not scores:
        return "technical"
    return max(scores, key=scores.get)  # ties resolve by insertion (keywords first)


def observe(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    current_text: str,
    target_domain: Optional[str] = None,
    limit: int = 5,
    min_score: float = 0.15,
    firewall: Optional[Firewall] = None,
) -> ObserverSuggestion:
    domain = target_domain or infer_domain(current_text, store)
    firewall = firewall or Firewall(cfg.policies_path, store)
    result = search(
        store, embedder, current_text,
        target_domain=domain, firewall=firewall, limit=limit,
    )
    suggestion = ObserverSuggestion(inferred_domain=domain)
    for hit in result.hits:
        if hit.score < min_score:
            continue
        suggestion.suggested_context.append({
            "memory_id": hit.memory.id,
            "summary": hit.memory.summary,
            "why_relevant": hit.why,
            "confidence": hit.memory.confidence,
            "allowed": True,
        })
    suggestion.blocked_context = [
        {"memory_id": b.memory_id, "reason": b.rule} for b in result.blocked
    ]
    return suggestion
