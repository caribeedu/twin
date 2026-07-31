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
from ..memory.store.base import MemoryStore
from ..sensory.percept import Percept
from .correlation.models import EpisodeLinkStatus


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
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None


@dataclass
class TrajectoryClaim:
    """A synthesized cross-source claim (0..N per episode)."""
    type: str = MemoryType.decision.value
    title: str = ""
    summary: str = ""
    evidence_quotes: list[str] = field(default_factory=list)
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


def _first_line(content: str) -> str:
    for line in (content or "").splitlines():
        line = line.lstrip("# ").strip()
        if line:
            return line[:160]
    return ""


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
                quotes_by_ref[ref] = _first_line(rec.content or "") or (rec.content or "")[:160]
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
    # Cortex produced structure (≥2 phases). Reflectability is a stricter gate.
    return len(brief.phases) >= 2


def _has_reflectable_arc(brief: EpisodeBrief) -> bool:
    """True only when the arc can yield a *non-tautological* trajectory claim.

    Pure ``goal → execution`` with a single ``motivated`` edge (typical GitHub
    PR + merge-commit pair) just restates membership — atomic extract already
    covers that. Reflection waits for a pivot, a contradiction, a resolved
    decision, or a goal that actually closes as an outcome.
    """
    if len(brief.phases) < 2:
        return False
    kinds = {p.get("kind") for p in brief.phases}
    rels = {e.get("relation") for e in brief.edges}
    if rels & {"superseded", "contradicts"}:
        return True
    if "decision" in kinds and (rels & {"resolved", "superseded"} or "outcome" in kinds):
        return True
    if "goal" in kinds and "outcome" in kinds:
        return True
    return False


def reflect_episode(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    episode_id: str,
    *,
    dry_run: bool = False,
    reflector: Optional[ReflectorFn] = None,
) -> ReflectResult:
    """Synthesize trajectory MemoryCandidates from one episode's arc.

    Emits candidates only (``needs_review=True``, ``review_reason=episode_reflect``).
    Idempotent through formation identity: re-reflecting corroborates rather
    than duplicating. Never confirms Memory or Judgment.
    """
    brief = build_episode_brief(store, episode_id)
    if brief is None:
        return ReflectResult(episode_id=episode_id, skipped_reason="episode not found")
    if not _has_arc(brief):
        return ReflectResult(
            episode_id=episode_id,
            skipped_reason="no arc yet (run cortex: twin correlate)",
        )
    if not _has_reflectable_arc(brief):
        return ReflectResult(
            episode_id=episode_id,
            skipped_reason=(
                "arc is structural only (e.g. PR→commit) — no pivot, "
                "contradiction, or goal→outcome to reflect"
            ),
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
        mem = MemoryItem(
            id=ids.memory_id(),
            type=mem_type,
            title=claim.title,
            summary=claim.summary,
            domain="technical",
            confidence=claim.confidence,
            valid_from=claim.valid_from,
            valid_until=claim.valid_until,
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
                prompt_version="1",
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
