"""Pattern reflection — the nightly cross-window "dream" pass.

Episode reflection asks "what does this unit of work mean?". Pattern reflection
asks "what does a *window* of the user's activity reveal that they never
bothered to state?" — durable preferences, procedures/habits and standing
constraints mined from repeated choices across senses (GitHub, Slack, meetings,
docs, sessions), optionally scoped to a project.

It compiles an :class:`AnalysisDossier` over a window and hands it to a chat
model. Output is MemoryCandidates only (``needs_review=True``,
``review_reason=pattern_reflect``). No model → defer. No lexical fallback.
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
from twin.sense.sensory.percept import Percept
from .analysis_dossier import AnalysisDossier, compile_window_dossier

PatternReflectorFn = Callable[[AnalysisDossier, Config], list[Any]]

# Conservative dossier budget so a local model's context is not overflowed.
PATTERN_DOSSIER_BUDGET_CHARS = 12_000

_OVERRIDE: Optional[PatternReflectorFn] = None


def set_pattern_override(fn: Optional[PatternReflectorFn]) -> None:
    """Inject a deterministic pattern reflector (tests/evals)."""
    global _OVERRIDE
    _OVERRIDE = fn


@dataclass
class PatternReflectResult:
    vault_id: str
    project_id: Optional[str] = None
    window: tuple[Optional[str], Optional[str]] = (None, None)
    claims: list[dict[str, Any]] = field(default_factory=list)
    skipped_reason: str = ""


def _select_reflector(cfg: Config) -> Optional[PatternReflectorFn]:
    if _OVERRIDE is not None:
        return _OVERRIDE
    from twin.llm import get_chat_client

    if cfg.extractor in (
        "auto", "ollama", "openai", "openai_compatible",
        "anthropic", "claude", "gemini", "google",
    ):
        try:
            from .interpreter.pattern_prompt import reflect_patterns_with_model
            from twin.llm.usage import usage_context

            client = get_chat_client(cfg)
            if client.available():
                def _reflector(dossier: AnalysisDossier, _cfg: Config) -> list[Any]:
                    # A model / parse failure must not fabricate. It surfaces the
                    # cause; pattern_reflect degrades gracefully around it.
                    with usage_context(stage="pattern", role="llm"):
                        return reflect_patterns_with_model(client, dossier)

                return _reflector
        except Exception:
            return None
    return None


def _window_key(vault_id: str, project_id: Optional[str], window) -> str:
    raw = f"{vault_id}|{project_id or ''}|{window[0] or ''}|{window[1] or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _ensure_pattern_percept(
    store: MemoryStore, dossier: AnalysisDossier, claim: Any, wkey: str,
) -> str:
    basis = claim.canonical_claim or {"t": claim.title}
    digest = hashlib.sha256(
        f"{wkey}|{sorted(basis.items()) if isinstance(basis, dict) else basis}".encode()
    ).hexdigest()[:20]
    pid = f"pct_pattern_{digest}"
    body = claim.summary
    if claim.evidence_quotes:
        body = body + "\n\n" + "\n".join(claim.evidence_quotes)
    percept = Percept(
        id=pid,
        percept_type="pattern_reflection",
        source_sensor="pattern_reflect",
        occurred_at=claim.valid_from,
        content=body,
        project_id=dossier.focus.project_id,
        source_trust=0.6,
        metadata={
            "vault_id": dossier.focus.vault_id,
            "window": list(dossier.focus.time_from or ""),
            "pattern_window_key": wkey,
        },
    )
    try:
        store.insert_percept(percept)
    except Exception:
        pass
    return pid


def pattern_reflect(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    *,
    vault_id: str,
    project_id: Optional[str] = None,
    time_from: Optional[str] = None,
    time_until: Optional[str] = None,
    title: str = "",
    session_id: Optional[str] = None,
    dry_run: bool = False,
    reflector: Optional[PatternReflectorFn] = None,
    min_signals: int = 2,
) -> PatternReflectResult:
    """Mine one window (+ optional project) for durable patterns.

    Candidates only. Requires ``min_signals`` primary pieces so a single event
    never masquerades as a pattern. Defers when no model is available.
    """
    window = (time_from, time_until)
    result = PatternReflectResult(
        vault_id=vault_id, project_id=project_id, window=window,
    )
    from .analysis_dossier import DEFAULT_BUDGET_CHARS

    budget = (
        DEFAULT_BUDGET_CHARS
        if cfg.llm_provider_kind != "ollama"
        else PATTERN_DOSSIER_BUDGET_CHARS
    )
    dossier = compile_window_dossier(
        store, embedder,
        vault_id=vault_id, project_id=project_id,
        time_from=time_from, time_until=time_until,
        title=title, session_id=session_id,
        budget_chars=budget,
    )
    if len(dossier.primary) + len(dossier.cross_sense) < min_signals:
        result.skipped_reason = "not enough signal in window for a pattern"
        return result

    reflector = reflector or _select_reflector(cfg)
    if reflector is None:
        result.skipped_reason = "pattern_reflect deferred (model unavailable)"
        return result

    try:
        claims = reflector(dossier, cfg)
    except Exception as exc:
        from .episode_reflect import _one_line

        result.skipped_reason = f"pattern model failed: {_one_line(exc)}"
        return result
    if not claims:
        result.skipped_reason = "reflector returned no patterns (model saw the window but proposed nothing)"
        return result

    wkey = _window_key(vault_id, project_id, window)
    for claim in claims:
        row: dict[str, Any] = {
            "type": claim.type,
            "domain": claim.domain,
            "title": claim.title,
            "summary": claim.summary,
            "created": False,
            "memory_id": None,
        }
        if dry_run:
            result.claims.append(row)
            continue
        try:
            mem_type = MemoryType(claim.type)
        except ValueError:
            mem_type = MemoryType.preference
        payload = {
            "source": "pattern_reflect",
            "brain_stage": "hippocampus_consolidate",
            "pattern": True,
            "pattern_window_key": wkey,
            "window": [time_from, time_until],
            "twin_influenced": bool(getattr(claim, "twin_influenced", True)),
        }
        primary_pid = _ensure_pattern_percept(store, dossier, claim, wkey)
        evidence_quote = (
            claim.evidence_quotes[0] if claim.evidence_quotes else claim.summary
        )
        mem = MemoryItem(
            id=ids.memory_id(),
            type=mem_type,
            title=claim.title,
            summary=claim.summary,
            domain=claim.domain or "technical",
            confidence=claim.confidence,
            valid_from=claim.valid_from,
            valid_until=None,
            payload=payload,
            needs_review=True,
            review_reason="pattern_reflect",
            project_id=project_id,
            canonical_claim=(
                CanonicalClaim(**claim.canonical_claim)
                if claim.canonical_claim else None
            ),
            extractor_version=ExtractorVersion(
                extractor="pattern_reflect",
                model="twin",
                prompt_version="1",
                schema_version="1",
            ),
        )
        mem, action = propose_or_corroborate(
            store, mem,
            percept_id=primary_pid,
            evidence_quote=evidence_quote,
            independence_group=f"pattern:{wkey}",
            source_trust=0.6,
            directness=0.5,
        )
        if action == "created":
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
