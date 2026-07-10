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


def infer_domain(text: str) -> str:
    lowered = text.lower()
    best_domain, best_hits = "technical", 0
    for domain, keywords in _DOMAIN_HINTS:
        hits = sum(1 for kw in keywords if re.search(rf"\b{re.escape(kw)}\b", lowered))
        if hits > best_hits:
            best_domain, best_hits = domain, hits
    return best_domain


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
    domain = target_domain or infer_domain(current_text)
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
