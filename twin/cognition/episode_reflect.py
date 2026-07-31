"""Episode reflection — the hippocampus_consolidate cognition stage.

Atomic ``extract_percept`` sees one source at a time and can only say "Edu
committed A, then B". Reflection reads a whole :class:`WorkEpisode` — its phase
arc and narrative edges — and synthesizes *trajectory* claims like "intended
the Kafka path, then chose SQS". Those land as **MemoryCandidates only**
(``needs_review=True``); reflection never confirms Memory or Judgment.

This is a cognitive layer (not correlation): the cortex stage proposes the
structure, reflect interprets it with a chat model. When no model is available
the stage **defers** (like the interpreter) — it never falls back to lexical
rules and never fabricates a trajectory. Tests inject a deterministic reflector
via ``set_reflect_override`` or the ``reflector=`` argument.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .. import ids
from ..config import Config
from ..memory.embeddings import Embedder
from ..memory.formation import propose_or_corroborate
from ..memory.models import CanonicalClaim, ExtractorVersion, MemoryItem, MemoryType
from ..memory.search import search
from ..memory.store.base import MemoryStore
from ..sensory.percept import Percept
from .correlation.models import EpisodeLinkStatus
from .correlation.text import rich_excerpt


@dataclass
class EpisodeBrief:
    """Structured input to a reflector — evidence, not conclusions."""
    episode_id: str
    vault_id: str
    title: str
    project_id: Optional[str]
    phases: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    quotes_by_ref: dict[str, str] = field(default_factory=dict)
    percept_by_ref: dict[str, str] = field(default_factory=dict)
    related_memories: list[dict[str, Any]] = field(default_factory=list)
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None


@dataclass
class TrajectoryClaim:
    """A synthesized cross-source claim (0..N per episode)."""
    type: str = MemoryType.decision.value
    domain: str = "technical"
    title: str = ""
    summary: str = ""
    evidence_quotes: list[str] = field(default_factory=list)
    related_memory_ids: list[str] = field(default_factory=list)
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    confidence: float = 0.6
    phase_keys: list[str] = field(default_factory=list)
    edge_ids: list[str] = field(default_factory=list)
    percept_ids: list[str] = field(default_factory=list)
    canonical_claim: Optional[dict[str, Any]] = None
    twin_influenced: bool = False


@dataclass
class ReflectResult:
    episode_id: str
    claims: list[dict[str, Any]] = field(default_factory=list)
    skipped_reason: str = ""


ReflectorFn = Callable[[EpisodeBrief, Config], list[TrajectoryClaim]]

_OVERRIDE: Optional[ReflectorFn] = None


def set_reflect_override(fn: Optional[ReflectorFn]) -> None:
    """Inject a deterministic reflector (tests/evals). ``None`` restores the
    default (model-backed, or defer when no model)."""
    global _OVERRIDE
    _OVERRIDE = fn


# -- brief construction ---------------------------------------------------


def build_episode_brief(store: MemoryStore, episode_id: str) -> Optional[EpisodeBrief]:
    ep = store.get_work_episode(episode_id)
    if ep is None:
        return None
    if not hasattr(store, "list_episode_phases"):
        return None

    quotes_by_ref: dict[str, str] = {}
    percept_by_ref: dict[str, str] = {}
    for lk in store.list_episode_links(episode_id):
        st = getattr(lk.status, "value", lk.status)
        if st != EpisodeLinkStatus.active.value:
            continue
        ref = f"{lk.external_type or ''}:{lk.external_id or ''}"
        if lk.connector_record_id and hasattr(store, "get_connector_record"):
            rec = store.get_connector_record(lk.connector_record_id)
            if rec is not None:
                content = rec.content or ""
                quotes_by_ref[ref] = rich_excerpt(content) or content[:200]
                if getattr(rec, "percept_id", None):
                    percept_by_ref[ref] = rec.percept_id

    phases = []
    for p in store.list_episode_phases(episode_id):
        phases.append({
            "phase_key": p.phase_key,
            "kind": getattr(p.kind, "value", p.kind),
            "order": p.order,
            "started_at": p.started_at,
            "ended_at": p.ended_at,
            "summary": p.summary,
            "members": list(p.member_external_refs or []),
        })
    edges = []
    for e in store.list_episode_edges(episode_id):
        edges.append({
            "id": e.id,
            "relation": getattr(e.relation, "value", e.relation),
            "status": getattr(e.status, "value", e.status),
            "from_key": e.from_ref.get("id"),
            "to_key": e.to_ref.get("id"),
            "evidence_quote": e.evidence_quote,
        })

    return EpisodeBrief(
        episode_id=ep.id,
        vault_id=ep.vault_id,
        title=ep.title,
        project_id=ep.project_id,
        phases=phases,
        edges=edges,
        quotes_by_ref=quotes_by_ref,
        percept_by_ref=percept_by_ref,
        valid_from=ep.started_at,
        valid_until=ep.ended_at,
    )


# -- related-memory retrieval ---------------------------------------------


def _reflect_search_query(brief: EpisodeBrief) -> str:
    parts = [brief.title]
    for p in sorted(brief.phases, key=lambda x: x.get("order", 0)):
        if p.get("summary"):
            parts.append(str(p["summary"]))
    for q in list(brief.quotes_by_ref.values())[:8]:
        parts.append(q[:160])
    return " ".join(parts)[:900]


_SESSION_ARTIFACT_KINDS = frozenset({
    "decision", "note", "preference", "constraint", "intent", "belief",
})


def gather_session_artifacts(
    store: MemoryStore,
    brief: EpisodeBrief,
    *,
    limit: int = 8,
    session_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Live session observe notes as soft context for consolidate.

    Closed-session intent only becomes Memory after ``session_complete``
    extraction. Open-session artifacts bridge that gap so reflect can link
    chat/Cursor intent to a PR/commit episode without waiting for close.
    """
    if not hasattr(store, "list_sessions") and not hasattr(store, "get_session"):
        return []
    sessions = []
    if session_id and hasattr(store, "get_session"):
        ses = store.get_session(session_id)
        if ses is not None:
            sessions = [ses]
    elif hasattr(store, "list_sessions"):
        try:
            sessions = list(store.list_sessions(status="active", limit=20))
        except TypeError:
            sessions = [
                s for s in store.list_sessions(limit=20)
                if getattr(getattr(s, "status", None), "value", s.status) == "active"
            ]
    out: list[dict[str, Any]] = []
    for ses in sessions:
        sid = ses.id
        ses_project = getattr(ses, "project_id", None)
        if brief.project_id and ses_project and ses_project != brief.project_id:
            continue
        domain = getattr(ses, "domain", None) or "technical"
        arts = list(getattr(ses, "artifacts", None) or [])
        for art in arts:
            if not isinstance(art, dict):
                continue
            kind = str(art.get("kind") or "").lower().strip()
            if kind not in _SESSION_ARTIFACT_KINDS:
                continue
            note = str(art.get("note") or "").strip()
            if not note:
                continue
            at = str(art.get("at") or "")
            out.append({
                "id": f"sesart:{sid}:{at}:{kind}",
                "type": kind,
                "domain": domain,
                "status": "session_artifact",
                "title": f"[{kind}] open session",
                "summary": note[:240],
                "score": 0.55,
                "why": "active session artifact",
                "ref": art.get("ref"),
                "session_id": sid,
            })
    # Prefer newest notes (artifacts append chronologically).
    if len(out) > limit:
        out = out[-limit:]
    return out


def gather_related_memories(
    store: MemoryStore,
    embedder: Embedder,
    brief: EpisodeBrief,
    *,
    limit: int = 12,
    session_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Confirmed + candidate + rejected neighbors, plus open-session artifacts.

    Same-episode reflections are excluded so prior meta claims cannot reinforce
    themselves. No Domain Firewall here — this is internal cognition writing
    candidates, not a consumer pack.
    """
    session_hits = gather_session_artifacts(
        store, brief, limit=min(8, limit), session_id=session_id,
    )
    mem_budget = max(limit - len(session_hits), 4)
    query = _reflect_search_query(brief).strip()
    mem_hits: list[dict[str, Any]] = []
    if query:
        result = search(
            store, embedder, query,
            target_domain="technical",
            firewall=None,
            include_candidates=True,
            include_rejected=True,
            limit=max(mem_budget * 2, 24),
        )
        for hit in result.hits:
            mem = hit.memory
            payload = mem.payload or {}
            if payload.get("episode_id") == brief.episode_id:
                continue
            mem_hits.append({
                "id": mem.id,
                "type": mem.type.value if hasattr(mem.type, "value") else str(mem.type),
                "domain": mem.domain,
                "status": mem.status.value if hasattr(mem.status, "value") else str(mem.status),
                "title": mem.title,
                "summary": (mem.summary or "")[:240],
                "score": hit.score,
                "why": hit.why,
            })
            if len(mem_hits) >= mem_budget:
                break
    # Session intent first — the model should see live dogfood notes before
    # older vault neighbors that often dominate lexical search.
    return session_hits + mem_hits


# -- reflectors -----------------------------------------------------------


def _select_reflector(cfg: Config) -> Optional[ReflectorFn]:
    """Pick the reflector, or ``None`` when the stage must defer.

    Only a chat model reflects — there is no lexical fallback. An explicit
    override (tests/CI) wins; ``heuristic`` / ``echo`` / an unreachable model
    all return ``None`` so the caller defers instead of inventing a trajectory.
    """
    if _OVERRIDE is not None:
        return _OVERRIDE
    if cfg.extractor in (
        "auto", "ollama", "openai", "openai_compatible",
        "anthropic", "claude", "gemini", "google",
    ):
        try:
            from .llm import get_chat_client
            client = get_chat_client(cfg)
            if client.available():
                return _make_llm_reflector(client)
        except Exception:
            return None
    return None


def _make_llm_reflector(client) -> ReflectorFn:
    from .interpreter.reflect_prompt import reflect_with_model

    def _reflector(brief: EpisodeBrief, cfg: Config) -> list[TrajectoryClaim]:
        # A model failure must not fabricate — return no claims (stage defers).
        claims = reflect_with_model(client, brief)
        for c in claims:
            c.twin_influenced = True
        return claims

    return _reflector


# -- persistence ----------------------------------------------------------


def _has_arc(brief: EpisodeBrief) -> bool:
    """Cortex produced structure (≥2 phases) — enough to ask the model."""
    return len(brief.phases) >= 2


def reflect_episode(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    episode_id: str,
    *,
    dry_run: bool = False,
    reflector: Optional[ReflectorFn] = None,
    session_id: Optional[str] = None,
) -> ReflectResult:
    """Synthesize trajectory MemoryCandidates from one episode's arc.

    Emits candidates only (``needs_review=True``, ``review_reason=episode_reflect``).
    Idempotent through formation identity: re-reflecting corroborates rather
    than duplicating. Never confirms Memory or Judgment. Whether the arc
    yields a claim is the model's job — there is no lexical pre-filter.
    """
    brief = build_episode_brief(store, episode_id)
    if brief is None:
        return ReflectResult(episode_id=episode_id, skipped_reason="episode not found")
    if not _has_arc(brief):
        return ReflectResult(
            episode_id=episode_id,
            skipped_reason="no arc yet (run cortex: twin correlate)",
        )

    brief.related_memories = gather_related_memories(
        store, embedder, brief, session_id=session_id,
    )

    reflector = reflector or _select_reflector(cfg)
    if reflector is None:
        return ReflectResult(
            episode_id=episode_id,
            skipped_reason="hippocampus_consolidate deferred (model unavailable)",
        )
    claims = reflector(brief, cfg)
    result = ReflectResult(episode_id=episode_id)
    if not claims:
        result.skipped_reason = "reflector produced no trajectory claims"
        return result

    for claim in claims:
        row: dict[str, Any] = {
            "type": claim.type,
            "domain": claim.domain,
            "title": claim.title,
            "summary": claim.summary,
            "valid_from": claim.valid_from,
            "created": False,
            "memory_id": None,
        }
        if dry_run:
            result.claims.append(row)
            continue

        try:
            mem_type = MemoryType(claim.type)
        except ValueError:
            mem_type = MemoryType.decision
        payload = {
            "episode_id": brief.episode_id,
            "phase_keys": list(claim.phase_keys),
            "edge_ids": list(claim.edge_ids),
            "related_memory_ids": list(claim.related_memory_ids),
            "source": "episode_reflect",
            "brain_stage": "hippocampus_consolidate",
            "trajectory": True,
            "twin_influenced": bool(claim.twin_influenced),
        }
        # The reflection is a cross-source reading; anchor its primary evidence
        # on a deterministic percept that captures what was read, so the memory
        # is grounded even when raw member percepts are unavailable.
        primary_pid = _ensure_reflection_percept(store, brief, claim)
        evidence_quote = (
            claim.evidence_quotes[0] if claim.evidence_quotes else claim.summary
        )
        # Trajectory claims are durable stances — do not pin valid_until to the
        # episode end (that collapses into temporal_gate and hides them).
        valid_until = claim.valid_until
        if valid_until and claim.valid_from and valid_until <= claim.valid_from:
            valid_until = None
        elif valid_until and brief.valid_until and valid_until == brief.valid_until:
            valid_until = None
        mem = MemoryItem(
            id=ids.memory_id(),
            type=mem_type,
            title=claim.title,
            summary=claim.summary,
            domain=claim.domain or "technical",
            confidence=claim.confidence,
            valid_from=claim.valid_from,
            valid_until=valid_until,
            payload=payload,
            needs_review=True,
            review_reason="episode_reflect",
            project_id=brief.project_id,
            canonical_claim=(
                CanonicalClaim(**claim.canonical_claim)
                if claim.canonical_claim else None
            ),
            extractor_version=ExtractorVersion(
                extractor="episode_reflect",
                model="twin",
                prompt_version="6",
                schema_version="1",
            ),
        )
        mem, action = propose_or_corroborate(
            store, mem,
            percept_id=primary_pid,
            evidence_quote=evidence_quote,
            independence_group=f"episode:{brief.episode_id}",
            source_trust=0.7,
            directness=0.6,
        )
        # Additional corroborating evidence spanning the other sources.
        if action == "created":
            _attach_extra_evidence(store, mem.id, claim, primary_pid)
            try:
                store.store_embedding(
                    mem.id, "memory", embedder.name,
                    embedder.embed(f"{claim.title}\n{claim.summary}"),
                )
            except Exception:
                pass
        row["created"] = action == "created"
        row["memory_id"] = mem.id
        result.claims.append(row)

    return result


def _claim_key(brief: EpisodeBrief, claim: TrajectoryClaim) -> str:
    basis = claim.canonical_claim or {"t": claim.title}
    raw = f"{brief.episode_id}|{sorted(basis.items()) if isinstance(basis, dict) else basis}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _ensure_reflection_percept(
    store: MemoryStore, brief: EpisodeBrief, claim: TrajectoryClaim,
) -> str:
    """Create (or reuse) the deterministic percept that grounds a reflection.

    The id is derived from the episode + claim identity, so re-reflecting reuses
    the same percept instead of creating duplicates.
    """
    pid = f"pct_reflect_{_claim_key(brief, claim)}"
    body = claim.summary
    if claim.evidence_quotes:
        body = body + "\n\n" + "\n".join(claim.evidence_quotes)
    percept = Percept(
        id=pid,
        percept_type="episode_reflection",
        source_sensor="episode_reflect",
        occurred_at=claim.valid_from,
        content=body,
        project_id=brief.project_id,
        source_trust=0.7,
        metadata={
            "episode_id": brief.episode_id,
            "phase_keys": list(claim.phase_keys),
            "edge_ids": list(claim.edge_ids),
        },
    )
    try:
        store.insert_percept(percept)  # returns None on dedupe — id is stable
    except Exception:
        pass
    return pid


def _attach_extra_evidence(
    store: MemoryStore, memory_id: str, claim: TrajectoryClaim, primary_pid: str,
) -> None:
    from ..memory.provenance import attach_corroborating_evidence

    seen_pid = {primary_pid}
    quotes = claim.evidence_quotes[1:] if claim.evidence_quotes else []
    pids = [p for p in claim.percept_ids if p and p not in seen_pid]
    for i, pid in enumerate(pids):
        # only ground on member percepts that actually exist (FK safety)
        if hasattr(store, "get_percept") and store.get_percept(pid) is None:
            continue
        quote = quotes[i] if i < len(quotes) else claim.summary
        try:
            attach_corroborating_evidence(
                store, memory_id, pid, quote,
                independence_group=f"episode:{claim.canonical_claim}",
                source_trust=0.7, bump_confidence=False,
            )
        except Exception:
            pass
        seen_pid.add(pid)
