"""Memory Observer — attention.

Watches the user's current text (a message, a task, a draft) and suggests
relevant memories without ever answering the user itself.

Flow: infer probable domain → search candidates → firewall filter → rank →
return a compact suggestion payload (suggested_context / blocked_context).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from ..config import UNCLASSIFIED_DOMAIN, Config
from ..judgment.firewall import Firewall
from ..memory.embeddings import Embedder
from ..memory.models import INACTIVE_STATUSES
from ..memory.search import search
from ..memory.store.base import MemoryStore

logger = logging.getLogger("twin.cognition.observer")

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
    they are attached to — inference informed by the graph, not just
    keywords."""
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
            if mem.status.value in INACTIVE_STATUSES:
                continue
            votes[mem.domain] = votes.get(mem.domain, 0) + 1
    return votes


def infer_domain(text: str, store: Optional[MemoryStore] = None) -> str:
    """Keyword hints + (when a store is given) domain votes from the graph.

    With no evidence at all the answer is ``unclassified`` — never a real
    domain. Downstream the firewall treats it as default-deny, so ambiguity
    degrades to *less* context, not to somebody else's context."""
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
        return UNCLASSIFIED_DOMAIN
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


# -- fast / deep observation ---------------------------------------------------
#
# Observation happens at two levels:
#   fast: deterministic — keywords, entity matches, project/repository
#         signals and graph votes; cheap enough to run on every call.
#   deep: local LLM classification, used only when domain, project or task
#         profile remains ambiguous after the fast pass.
# The reading carries confidence per dimension, not a single guess.

from pathlib import Path

from .task_profiles import PROFILES, infer_task_profile

_DEEP_SCHEMA = {
    "type": "object",
    "properties": {
        "domain": {"type": "string"},
        "task_profile": {"type": "string", "enum": list(PROFILES)},
        "project": {"type": ["string", "null"]},
        "domain_confidence": {"type": "number"},
        "task_confidence": {"type": "number"},
    },
    "required": ["domain", "task_profile", "project",
                 "domain_confidence", "task_confidence"],
    "additionalProperties": False,
}

_DEEP_PROMPT = """\
You classify the user's current text for a personal memory system.
Known domains: work, technical, personal_preferences, assistant_preferences.
Known task profiles: {profiles}.
Known projects: {projects}.
Return the most likely domain, task profile and project (or null), with
confidence between 0 and 1 for domain and task. Respond with JSON only."""


# Below this confidence the observer refuses to name a domain: the reading
# says "unclassified" and downstream operates default-deny until either the
# deep observer resolves it or the client confirms the domain explicitly.
# One explicit keyword hit scores ~0.33 — that IS evidence and passes; zero
# evidence scores 0.0 and never does.
DOMAIN_CONFIDENCE_THRESHOLD = 0.3
# Below this the fast reading is *uncertain* and worth a deep (LLM) pass —
# a higher bar than asserting the domain at all.
UNCERTAIN_DOMAIN_CONFIDENCE = 0.34


@dataclass
class ObserverReading:
    domain: str = UNCLASSIFIED_DOMAIN
    task_profile: str = "general"
    project_id: Optional[str] = None
    confidences: dict = field(default_factory=dict)  # {domain, task_profile, project}
    uncertain: bool = False
    mode: str = "fast"
    fallback_reason: Optional[str] = None  # set when a deep read was attempted and failed

    @property
    def needs_domain_confirmation(self) -> bool:
        return self.domain == UNCLASSIFIED_DOMAIN


def _fast_read(store: MemoryStore, text: str, cwd: Optional[str] = None) -> ObserverReading:
    lowered = text.lower()
    domain_scores: dict[str, float] = {}
    for domain, keywords in _DOMAIN_HINTS:
        hits = sum(1 for kw in keywords if re.search(rf"\b{re.escape(kw)}\b", lowered))
        if hits:
            domain_scores[domain] = domain_scores.get(domain, 0.0) + float(hits)
    graph_votes = _graph_domain_votes(store, text)
    total_votes = sum(graph_votes.values())
    if total_votes:
        for domain, count in graph_votes.items():
            domain_scores[domain] = domain_scores.get(domain, 0.0) + 2.0 * (count / total_votes)

    if domain_scores:
        domain = max(domain_scores, key=domain_scores.get)
        domain_conf = min(1.0, domain_scores[domain] / 3)
    else:
        domain, domain_conf = UNCLASSIFIED_DOMAIN, 0.0
    if domain_conf < DOMAIN_CONFIDENCE_THRESHOLD:
        # not enough evidence to assert a domain — never guess a permissive one
        domain = UNCLASSIFIED_DOMAIN

    task_profile, task_conf = infer_task_profile(text)

    # project resolution: repository/directory signal first, then mentions
    project_id: Optional[str] = None
    project_conf = 0.0
    if cwd:
        project = store.find_project(Path(cwd).name)
        if project is not None:
            project_id, project_conf = project.id, 0.9
    if project_id is None:
        for p in store.list_projects():
            names = [p.name] + p.aliases
            if any(re.search(rf"\b{re.escape(n.lower())}\b", lowered) for n in names):
                project_id, project_conf = p.id, 0.7
                break

    return ObserverReading(
        domain=domain, task_profile=task_profile, project_id=project_id,
        confidences={"domain": round(domain_conf, 2),
                     "task_profile": round(task_conf, 2),
                     "project": round(project_conf, 2)},
        uncertain=(domain_conf < UNCERTAIN_DOMAIN_CONFIDENCE or task_conf < 0.5),
        mode="fast",
    )


def _deep_read(store: MemoryStore, cfg: Config, text: str,
               fast: ObserverReading, client=None) -> ObserverReading:
    import json as _json

    import httpx

    projects = store.list_projects()
    http = client or httpx.Client(base_url=cfg.ollama_url.rstrip("/"), timeout=60)
    resp = http.post("/api/chat", json={
        "model": cfg.ollama_model,
        "stream": False,
        "format": _DEEP_SCHEMA,
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": _DEEP_PROMPT.format(
                profiles=", ".join(PROFILES),
                projects=", ".join(p.name for p in projects) or "none",
            )},
            {"role": "user", "content": text},
        ],
    })
    resp.raise_for_status()
    data = _json.loads(resp.json()["message"]["content"])

    project_id = fast.project_id
    project_conf = fast.confidences.get("project", 0.0)
    if project_id is None and data.get("project"):
        found = store.find_project(str(data["project"]))
        if found is not None:
            project_id, project_conf = found.id, 0.6

    domain = data.get("domain", fast.domain)
    if domain not in {d for d, _ in _DOMAIN_HINTS} | {"work", "technical",
                                                      "personal_preferences",
                                                      "assistant_preferences"}:
        domain = fast.domain  # may be unclassified — the safe answer stands
    domain_conf = float(data.get("domain_confidence", 0.5))
    if domain_conf < DOMAIN_CONFIDENCE_THRESHOLD:
        domain = UNCLASSIFIED_DOMAIN  # the model itself is not sure — don't assert
    task_profile = data.get("task_profile", fast.task_profile)
    if task_profile not in PROFILES:
        task_profile = fast.task_profile

    return ObserverReading(
        domain=domain, task_profile=task_profile, project_id=project_id,
        confidences={
            "domain": round(domain_conf, 2),
            "task_profile": round(float(data.get("task_confidence", 0.5)), 2),
            "project": round(project_conf, 2),
        },
        uncertain=(domain == UNCLASSIFIED_DOMAIN),
        mode="deep",
    )


def read_context(store: MemoryStore, cfg: Config, text: str,
                 cwd: Optional[str] = None, client=None) -> ObserverReading:
    """Fast observation always; deep (local LLM) only when the fast pass is
    uncertain and Ollama is reachable.

    Every fallback is observable: when the deep read is skipped or fails,
    the reading carries ``fallback_reason`` (error type only — never the
    text being classified) and a warning is logged. An unresolved reading
    keeps ``domain=unclassified``, which downstream means default-deny."""
    fast = _fast_read(store, text, cwd=cwd)
    if not fast.uncertain:
        return fast
    from .extractors import ollama as ollama_extractor

    if client is None and not ollama_extractor.available(cfg.ollama_url):
        fast.fallback_reason = "deep_observer_unavailable"
        logger.warning("deep observer unavailable (%s unreachable); "
                       "fast reading stands with domain=%s", cfg.ollama_url, fast.domain)
        return fast
    try:
        return _deep_read(store, cfg, text, fast, client=client)
    except Exception as exc:  # deep observation is best-effort, but never silent
        fast.fallback_reason = f"deep_observer_failed:{type(exc).__name__}"
        logger.warning("deep observer failed (%s); fast reading stands with domain=%s",
                       type(exc).__name__, fast.domain)
        return fast
