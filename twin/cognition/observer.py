"""Memory Observer — attention.

Watches the user's current text (a message, a task, a draft) and suggests
relevant memories without ever answering the user itself.

Flow: search candidates (hybrid, vault-wide) → firewall filter by the
*consumer* domain (the open session, or an explicit argument) → rank, with
a soft boost for memories that already live in that domain → return a
compact suggestion payload (suggested_context / blocked_context).

The observer never guesses the consumer domain from the text: a domain the
firewall trusts must come from a stable source (the frozen session domain or
an explicit argument). With no such domain the target is ``unclassified`` and
the firewall returns nothing — ambiguity degrades to *less* context, never to
somebody else's context.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..config import UNCLASSIFIED_DOMAIN, Config
from ..judgment.firewall import Firewall
from ..memory.embeddings import Embedder
from ..memory.search import search
from ..memory.store.base import MemoryStore

logger = logging.getLogger("twin.cognition.observer")

# Mode of an ObserverReading — how the session domain was decided.
DOMAIN_MODE_SEARCH = "search"        # retrieval vote across confirmed memories
DOMAIN_MODE_LLM = "llm"              # configured local chat model
DOMAIN_MODE_UNRESOLVED = "unresolved"  # nothing could name it → unclassified
DOMAIN_MODE_EXPLICIT = "explicit"    # caller supplied a real domain
DOMAIN_MODE_FROZEN = "frozen"        # already frozen on the binding/session


def infer_project_from_cwd(store: MemoryStore, cwd: Optional[str]) -> Optional[str]:
    """Deterministic project id from a working-directory signal.

    Matches the cwd basename against project name / alias / repo — no LLM,
    no keyword domain guess. Used so ``session_start(..., cwd=...)`` still
    binds a known project when search has nothing to vote on.
    """
    if not cwd:
        return None
    try:
        name = Path(cwd).expanduser().name
    except Exception:
        name = str(cwd).rstrip("/\\").split("/")[-1].split("\\")[-1]
    name = (name or "").strip()
    if not name or name in (".", ".."):
        return None
    found = store.find_project(name)
    return found.id if found is not None else None


@dataclass
class ObserverSuggestion:
    suggested_context: list[dict] = field(default_factory=list)
    blocked_context: list[dict] = field(default_factory=list)
    inferred_domain: str = UNCLASSIFIED_DOMAIN


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
    """Suggest memories relevant to ``current_text`` for a known consumer domain.

    ``target_domain`` is the *consumer* domain (a frozen session domain, or an
    explicit argument). It is never inferred from the text. When it is absent
    the target is ``unclassified``: the firewall denies everything and the
    suggestion comes back empty rather than leaking another domain's memories.
    Same-domain hits get a soft ranking boost so the consumer's own domain wins
    ties without excluding firewall-allowed cross-domain context.
    """
    domain = target_domain or UNCLASSIFIED_DOMAIN
    firewall = firewall or Firewall(cfg.policies_path, store)
    result = search(
        store, embedder, current_text,
        target_domain=domain, firewall=firewall, limit=limit,
        domain_affinity=domain if domain != UNCLASSIFIED_DOMAIN else None,
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
            "score": float(hit.score),
            "allowed": True,
        })
    suggestion.blocked_context = [
        {"memory_id": b.memory_id, "reason": b.rule} for b in result.blocked
    ]
    return suggestion


# -- context observation -------------------------------------------------------
#
# Session/context classification (opening a cognitive session scope) is decided
# by a retrieval vote across confirmed memories and, failing that, the
# configured local chat model. There is no keyword path: the domain either has
# evidence in the store or the model names it, otherwise it stays unclassified.

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
# local LLM resolves it or the client confirms the domain explicitly. The
# model must clear this bar for its own answer to be asserted.
DOMAIN_CONFIDENCE_THRESHOLD = 0.3


@dataclass
class ObserverReading:
    domain: str = UNCLASSIFIED_DOMAIN
    task_profile: str = "general"
    project_id: Optional[str] = None
    confidences: dict = field(default_factory=dict)  # {domain, task_profile, project}
    uncertain: bool = False
    mode: str = DOMAIN_MODE_UNRESOLVED
    fallback_reason: Optional[str] = None  # set when a deep read was attempted and failed

    @property
    def needs_domain_confirmation(self) -> bool:
        return self.domain == UNCLASSIFIED_DOMAIN


def _deep_read(store: MemoryStore, cfg: Config, text: str,
               seed: ObserverReading, client=None) -> ObserverReading:
    from twin.llm import get_chat_client
    from twin.llm.usage import usage_context

    projects = store.list_projects()
    chat = get_chat_client(cfg, client=client, timeout=60)
    try:
        with usage_context(stage="observe", role="llm"):
            data = chat.complete_json(
                system=_DEEP_PROMPT.format(
                    profiles=", ".join(PROFILES),
                    projects=", ".join(p.name for p in projects) or "none",
                ),
                user=text,
                schema=_DEEP_SCHEMA,
                temperature=0.0,
            )
    finally:
        closer = getattr(chat, "close", None)
        if callable(closer) and client is None:
            closer()

    project_id = seed.project_id
    project_conf = seed.confidences.get("project", 0.0)
    if project_id is None and data.get("project"):
        found = store.find_project(str(data["project"]))
        if found is not None:
            project_id, project_conf = found.id, 0.6

    allowed = {"work", "technical", "personal_preferences", "assistant_preferences"}
    domain = data.get("domain", seed.domain)
    if domain not in allowed:
        domain = UNCLASSIFIED_DOMAIN
    domain_conf = float(data.get("domain_confidence", 0.5))
    if domain_conf < DOMAIN_CONFIDENCE_THRESHOLD:
        domain = UNCLASSIFIED_DOMAIN  # the model itself is not sure — don't assert
    task_profile = data.get("task_profile", seed.task_profile)
    if task_profile not in PROFILES:
        task_profile = "general"

    return ObserverReading(
        domain=domain, task_profile=task_profile, project_id=project_id,
        confidences={
            "domain": round(domain_conf, 2),
            "task_profile": round(float(data.get("task_confidence", 0.5)), 2),
            "project": round(project_conf, 2),
        },
        uncertain=(domain == UNCLASSIFIED_DOMAIN),
        mode=DOMAIN_MODE_LLM,
    )


def read_context(store: MemoryStore, cfg: Config, text: str,
                 cwd: Optional[str] = None, client=None) -> ObserverReading:
    """Classify session context with the configured local LLM only.

    No keyword / graph heuristic pass. When the LLM is unavailable or fails,
    return ``unclassified`` (default-deny) with an observable
    ``fallback_reason`` (error type only — never the text being classified).
    ``cwd`` is offered to the model as a hint, not resolved by path rules.

    Prefer ``resolve_context_domain`` at session boundaries — it tries
    retrieval votes before calling this.
    """
    from twin.llm import llm_available

    seed = ObserverReading(
        domain=UNCLASSIFIED_DOMAIN,
        task_profile="general",
        project_id=None,
        confidences={"domain": 0.0, "task_profile": 0.0, "project": 0.0},
        uncertain=True,
        mode=DOMAIN_MODE_UNRESOLVED,
    )
    user = (text or "").strip()
    if cwd:
        user = f"{user}\n\n[cwd: {cwd}]".strip()

    if client is None and not llm_available(cfg):
        seed.fallback_reason = "deep_observer_unavailable"
        logger.warning(
            "deep observer unavailable (%s @ %s); leaving domain=unclassified",
            cfg.normalized_llm_provider, cfg.resolved_llm_base_url,
        )
        return seed
    try:
        return _deep_read(store, cfg, user or "(empty)", seed, client=client)
    except Exception as exc:  # best-effort, never silent, never heuristic fallback
        seed.fallback_reason = f"deep_observer_failed:{type(exc).__name__}"
        logger.warning(
            "deep observer failed (%s); leaving domain=unclassified",
            type(exc).__name__,
        )
        return seed


# Cross-domain retrieval vote → domain. Used before the local LLM.
# Hash/local embedders often land relevant hits in the 0.10–0.20 band.
DOMAIN_VOTE_MIN_HIT_SCORE = 0.10
DOMAIN_VOTE_MIN_SHARE = 0.55
DOMAIN_VOTE_MIN_MARGIN = 0.05


def infer_domain_from_search(
    store: MemoryStore,
    embedder: Embedder,
    text: str,
    *,
    limit: int = 8,
    min_score: float = DOMAIN_VOTE_MIN_HIT_SCORE,
) -> Optional[ObserverReading]:
    """Vote a domain from confirmed memory hits (no firewall / no keywords).

    Returns ``None`` when evidence is missing or ambiguous — caller may then
    fall back to the local LLM. Never invents a domain from empty retrieval.
    """
    query = (text or "").strip()
    if not query:
        return None

    # firewall=None → cross-domain candidates (unclassified target would deny all)
    result = search(
        store, embedder, query,
        target_domain="",
        firewall=None,
        limit=limit,
        include_candidates=False,
    )
    weights: dict[str, float] = {}
    project_votes: dict[str, float] = {}
    for hit in result.hits:
        if hit.score < min_score:
            continue
        domain = (hit.memory.domain or "").strip()
        if not domain or domain == UNCLASSIFIED_DOMAIN:
            continue
        weights[domain] = weights.get(domain, 0.0) + float(hit.score)
        pid = hit.memory.project_id
        if pid:
            project_votes[pid] = project_votes.get(pid, 0.0) + float(hit.score)

    if not weights:
        return None

    ranked = sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))
    top_domain, top_score = ranked[0]
    total = sum(weights.values()) or 1.0
    share = top_score / total
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = top_score - second
    clear = share >= DOMAIN_VOTE_MIN_SHARE or (
        len(ranked) == 1 and top_score >= min_score
    )
    if not clear and margin < DOMAIN_VOTE_MIN_MARGIN:
        return None
    if share < DOMAIN_VOTE_MIN_SHARE and len(ranked) > 1:
        return None

    project_id = None
    project_conf = 0.0
    if project_votes:
        pid, pscore = max(project_votes.items(), key=lambda kv: kv[1])
        if pscore / total >= DOMAIN_VOTE_MIN_SHARE:
            project_id, project_conf = pid, min(1.0, pscore / total)

    # Task profile only orders the pack (coding vs architecture vs …); it is
    # not a firewall input, so cheap keyword hints on the query are fine here.
    task_profile, task_conf = infer_task_profile(query)

    return ObserverReading(
        domain=top_domain,
        task_profile=task_profile,
        project_id=project_id,
        confidences={
            "domain": round(min(1.0, share), 2),
            "task_profile": round(task_conf, 2),
            "project": round(project_conf, 2),
        },
        uncertain=False,
        mode=DOMAIN_MODE_SEARCH,
    )


def resolve_context_domain(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    text: str,
    *,
    cwd: Optional[str] = None,
    client=None,
    existing_domain: Optional[str] = None,
) -> ObserverReading:
    """Resolve domain on the request hot path: search vote only.

    Skips inference when ``existing_domain`` is already a real frozen domain.
    When retrieval cannot name a domain the reading stays ``unclassified`` —
    never call the local LLM here (hooks / session start must stay fast).
    Background ``session_domain_resolve`` jobs and client/MCP explicit domain
    upgrade the binding later from multi-message evidence.

    Project binding is separate: a cwd basename that matches a known project
    is applied deterministically even when the domain stays unclassified.
    """
    if existing_domain and existing_domain != UNCLASSIFIED_DOMAIN:
        reading = ObserverReading(
            domain=existing_domain,
            task_profile="general",
            confidences={"domain": 1.0, "task_profile": 0.0, "project": 0.0},
            uncertain=False,
            mode=DOMAIN_MODE_FROZEN,
        )
    else:
        voted = infer_domain_from_search(store, embedder, text)
        if voted is not None:
            reading = voted
        else:
            reading = ObserverReading(
                domain=UNCLASSIFIED_DOMAIN,
                task_profile="general",
                project_id=None,
                confidences={"domain": 0.0, "task_profile": 0.0, "project": 0.0},
                uncertain=True,
                mode=DOMAIN_MODE_UNRESOLVED,
                fallback_reason="awaiting_background_or_client",
            )

    if not reading.project_id:
        cwd_project = infer_project_from_cwd(store, cwd)
        if cwd_project:
            reading.project_id = cwd_project
            conf = dict(reading.confidences or {})
            conf["project"] = max(float(conf.get("project") or 0.0), 0.9)
            reading.confidences = conf
    return reading
