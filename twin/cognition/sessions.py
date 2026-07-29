"""Cognitive session lifecycle.

A session closes the read-only flow (twin → LLM) into a maintained loop:

 session_start → identify project/domain/task, supply a context pack
 session_observe → record artifacts produced or changed during the work
 session_complete → turn what happened into a percept and candidate memories
 session_feedback → record explicit usefulness feedback

Sessions are the unit product metrics hang from: what was supplied, what
came back, and whether it was actually useful.

Design rules this module enforces:

- ambiguity fails visibly and conservatively — an unknown explicit project
 raises instead of being replaced by inference, and an unclassified domain
 yields an empty (default-deny) pack plus ``needs_domain_confirmation``;
- completion (the work ended) and consolidation (twin learned from it) are
 separate states: consolidation is idempotent and retryable, anchored on a
 deterministic percept dedup key;
- artifact and feedback writes are append-only store operations, safe under
 concurrent clients.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .. import ids
from ..clock import now_iso
from ..config import UNCLASSIFIED_DOMAIN, Config
from ..memory.embeddings import Embedder
from ..memory.models import (
    FEEDBACK_SCOPES,
    CognitiveSession,
    ConsolidationStatus,
    FeedbackVerdict,
    Project,
    SessionStatus,
)
from ..memory.store.base import MemoryStore
from ..sensory.percept import Percept
from .context_pack import ContextPack, build_context_pack
from .observer import DOMAIN_MODE_EXPLICIT, ObserverReading, resolve_context_domain
from .pipeline import extract_percept
from .task_profiles import infer_task_profile

logger = logging.getLogger("twin.cognition.sessions")

# How much a session summary can be trusted depends on who wrote it, not on
# the fact that it arrived through a session. "user" means the human typed
# or explicitly confirmed it; "derived" means deterministically assembled
# from verified artifacts; "client" is a free-form program-supplied text;
# "assistant" is an LLM's own unconfirmed account of what it did.
SUMMARY_TRUST = {"user": 0.9, "derived": 0.85, "client": 0.7, "assistant": 0.6}
DEFAULT_STALE_HOURS = 24.0

# Folded into the extractable session_summary Percept: the dialogue plus the
# deliberate observations a human or host records (twin session observe, and
# the host's file/project context). Tool I/O (tool_requested / tool_completed /
# tool_failed) and session_start boilerplate stay on session.artifacts for
# replay — copied into the percept they drown the interpreter with pack dumps.
_SUMMARY_PERCEPT_KINDS = frozenset({
    "user_message",
    "assistant_result",
    "file",
    "commit",
    "doc",
    "note",
    "file_context",
    "project_context",
})
# Structural / protocol markers — never cognitive content for extraction.
_SUMMARY_IGNORE_TEXT = frozenset({
    "prompt_input_exit", "clear", "logout", "other", "abort", "stop",
    "[turn_end]",
})
_SUMMARY_IGNORE_KINDS = frozenset({
    "turn_completed",
    "tool_requested",
    "tool_completed",
    "tool_failed",
    "session_start",
})


@dataclass
class SessionStart:
    session: CognitiveSession
    pack: ContextPack
    reading_confidences: dict[str, float]
    observer_mode: str
    needs_domain_confirmation: bool = False
    observer_fallback: Optional[str] = None


def start_session(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    query: str,
    client: str = "unknown",
    cwd: Optional[str] = None,
    domain: Optional[str] = None,
    project: Optional[str] = None,      # explicit project name/alias/id
    task_profile: Optional[str] = None,
    max_tokens: int = 1200,
    include_candidates: bool = False,
    persona: str = "individual",
    purpose: str = "task_execution",
    audience: str = "self",
    tool_id: Optional[str] = None,
    api_token: Optional[str] = None,
    surface: Optional[str] = None,
) -> SessionStart:
    """Identify project/domain/task profile (unless given explicitly), build
    a task-aware pack and open the session that records what was supplied.

    An explicit ``project`` that cannot be resolved raises ValueError —
    inference never silently substitutes an explicit argument. When neither
    the caller nor observation can name a domain, the session opens as
    ``unclassified``: the firewall blocks all memories, the pack carries no
    judgment, and ``needs_domain_confirmation`` asks the client to confirm.

    Domain inference on this hot path is search-vote only (no local LLM).
    When the vote is inconclusive the session opens ``unclassified``; a
    background ``session_domain_resolve`` job or an explicit client/MCP domain
    freezes it later.
    """
    if domain and domain != UNCLASSIFIED_DOMAIN:
        reading = ObserverReading(
            domain=domain,
            task_profile=task_profile or "general",
            confidences={
                "domain": 1.0,
                "task_profile": 1.0 if task_profile else 0.0,
                "project": 0.0,
            },
            uncertain=False,
            mode=DOMAIN_MODE_EXPLICIT,
        )
    else:
        reading = resolve_context_domain(
            store, cfg, embedder, query, cwd=cwd,
        )

    if project:
        found = store.get_project(project) or store.find_project(project)
        if found is None:
            raise ValueError(f"project {project!r} not found — create it first "
                             "or omit it to let twin infer the project")
        project_id: Optional[str] = found.id
        if reading.project_id and reading.project_id != found.id:
            logger.info("explicit project %s overrides inferred %s",
                        found.id, reading.project_id)
    else:
        project_id = reading.project_id

    session_domain = domain or reading.domain
    needs_confirmation = session_domain == UNCLASSIFIED_DOMAIN

    # Task profile orders the pack and is independent of the domain decision:
    # infer it from the query whenever the caller did not pin it and the
    # reading only carries the generic default.
    resolved_task_profile = task_profile or reading.task_profile or "general"
    if not task_profile and resolved_task_profile == "general":
        inferred_profile, _ = infer_task_profile(query)
        if inferred_profile != "general":
            resolved_task_profile = inferred_profile

    started_at = now_iso()
    from ..privacy.identity import ensure_local_identity, resolve_access
    from ..privacy.yaml_io import bootstrap_policy_set
    # Surface identity is resolved server-side. Missing/unknown client →
    # restricted mode — never silently elevate to local-cli.
    # Native host adapters run as local hooks: CognitiveSession.client records
    # the host product, auth surface is ``native`` (not CLI).
    _native = frozenset({
        "claude-code", "codex", "codex-app-server", "native",
    })
    if client in _native or (surface or "").lower() == "native":
        resolved_surface = "native"
    elif client in ("cli", "local-cli", "twin-cli"):
        resolved_surface = "cli"
    else:
        resolved_surface = "mcp"
    if client in ("unknown", "", None) and not tool_id and resolved_surface != "native":
        resolved_surface = "unknown"
    if resolved_surface in ("cli", "native"):
        bootstrap_policy_set(store, policies_path=cfg.policies_path)
        ensure_local_identity(store)
    # ``unclassified`` is not a real allowlist domain — pass it and identity
    # collapses to restricted. Auth identity comes from host/persona defaults;
    # the firewall still blocks memories until domain freezes.
    access_domains = (
        [session_domain]
        if session_domain and session_domain != UNCLASSIFIED_DOMAIN
        else []
    )
    access = resolve_access(
        store,
        surface=resolved_surface,
        client=client if client not in ("unknown", "") else None,
        # Native: never pass host product name as tool_id — identity layer
        # uses ``native-host``. Concrete tools only on real tool calls.
        tool_id=None if resolved_surface == "native" else tool_id,
        persona=persona,
        purpose=purpose,
        audience=audience,
        project_id=project_id,
        requested_domains=access_domains,
        api_token=api_token,
    )
    session = CognitiveSession(
        id=ids.session_id(),
        client=client,
        project_id=project_id,
        domain=session_domain,
        task_profile=resolved_task_profile,
        initial_query=query,
        started_at=started_at,
        last_activity_at=started_at,
        principal_id=access.principal_id,
        persona=access.persona,
        purpose=access.purpose,
        audience=access.audience,
        tool_id=access.tool_id,
    )
    access = access.model_copy(update={"session_id": session.id})
    pack = build_context_pack(
        store, cfg, embedder, query,
        target_domain=session.domain, max_tokens=max_tokens,
        include_candidates=include_candidates,
        # an unconfirmed domain gets nothing, not even the judgment profile
        include_judgment=not needs_confirmation,
        task_profile=session.task_profile, project_id=project_id,
        access=access,
    )
    session.supplied_memory_ids = [s["memory_id"] for s in pack.sources]
    session.pack_chars = len(pack.context_pack)
    session.judgment_snapshot_id = pack.judgment_snapshot_id
    session.privacy_decision_ids = (
        [pack.privacy_decision_id] if pack.privacy_decision_id else []
    )
    session.grant_ids = list((pack.privacy_meta or {}).get("grant_ids") or [])
    session.policy_snapshot_id = (pack.privacy_meta or {}).get("policy_set_version")
    store.insert_session(session)
    return SessionStart(
        session=session, pack=pack,
        reading_confidences=reading.confidences, observer_mode=reading.mode,
        needs_domain_confirmation=needs_confirmation,
        observer_fallback=reading.fallback_reason,
    )


def observe_session(store: MemoryStore, session_id: str,
                    artifact: dict[str, Any]) -> CognitiveSession:
    """Record an artifact produced or changed during the session — a file,
    commit, PR, document or free-form note ({kind, ref?, note?, percept_id?}).

    When the artifact was already ingested by a sensor, pass its
    ``percept_id``: the session then references the verified percept instead
    of duplicating text, and consolidation will not re-extract the note.

    The append is atomic at the store level: concurrent observers never
    overwrite each other, and a session that is no longer active rejects
    the write instead of absorbing it silently."""
    if not str(artifact.get("kind", "")).strip():
        raise ValueError("artifact needs a non-empty 'kind'")
    store.append_session_artifact(session_id, {**artifact, "at": now_iso()})
    return store.get_session(session_id)


def complete_session(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    session_id: str,
    summary: str = "",
    abandoned: bool = False,
    summary_origin: str = "client",   # user | assistant | client | derived
    user_confirmed: bool = False,
) -> CognitiveSession:
    """Close the session and consolidate what happened.

    Completion is a compare-and-set transition (two concurrent completes
    cannot both win). Consolidation — an optional summary plus **user /
    assistant** artifact notes become a ``session_summary`` percept;
    tool I/O stays on the session for replay but is not folded into that
    percept. Extraction then turns the percept into candidate memories.
    Retryable: calling complete again on a failed consolidation re-runs
    only consolidation, without duplicating percepts (dedup key =
    session id)."""
    if summary_origin not in SUMMARY_TRUST:
        raise ValueError(f"summary_origin must be one of {sorted(SUMMARY_TRUST)}")
    session = store.get_session(session_id)
    if session is None:
        raise ValueError(f"session {session_id} not found")

    if session.status == SessionStatus.active:
        target = SessionStatus.abandoned if abandoned else SessionStatus.completed
        if not store.transition_session(session_id, SessionStatus.active.value,
                                        target.value, ended_at=now_iso()):
            raise ValueError(f"session {session_id} was concurrently transitioned")
        session = store.get_session(session_id)
    elif (session.status == SessionStatus.completed
          and session.consolidation_status == ConsolidationStatus.failed
          and not abandoned):
        pass  # retry path: only consolidation runs again
    else:
        raise ValueError(
            f"session {session_id} is {session.status.value} "
            f"(consolidation: {session.consolidation_status.value}), not completable"
        )

    if abandoned:
        session.consolidation_status = ConsolidationStatus.skipped
        store.update_session(session)
        return session

    lines: list[str] = []
    summary_text = (summary or "").strip()
    if summary_text and summary_text.lower() not in _SUMMARY_IGNORE_TEXT:
        lines.append(summary_text)
    for artifact in session.artifacts:
        if artifact.get("percept_id"):
            continue  # already a first-class percept — never duplicated as text
        kind = str(artifact.get("kind") or "").strip()
        if kind not in _SUMMARY_PERCEPT_KINDS or kind in _SUMMARY_IGNORE_KINDS:
            continue
        note = artifact.get("note") or artifact.get("ref") or ""
        if not note or str(note).strip().lower() in _SUMMARY_IGNORE_TEXT:
            continue
        from .evidence_text import fold_summary_line
        lines.append(fold_summary_line(kind, str(note)))
    if not lines:
        session.consolidation_status = ConsolidationStatus.skipped
        store.update_session(session)
        return session

    return _consolidate(store, cfg, embedder, session, lines,
                        summary_origin, user_confirmed)


def _consolidate(store: MemoryStore, cfg: Config, embedder: Embedder,
                 session: CognitiveSession, lines: list[str],
                 summary_origin: str, user_confirmed: bool) -> CognitiveSession:
    session.consolidation_status = ConsolidationStatus.pending
    session.consolidation_error = None
    store.update_session(session)
    try:
        trust = 0.9 if user_confirmed else SUMMARY_TRUST[summary_origin]
        percept = Percept(
            percept_type="session_summary",
            source_sensor="session",
            occurred_at=session.ended_at,
            ingested_at=now_iso(),
            actors=[],
            content="\n".join(lines),
            content_refs=[{"kind": "cognitive_session", "session_id": session.id}],
            privacy_hints={"domain_hint": session.domain},
            metadata={"summary_origin": summary_origin,
                      "user_confirmed": user_confirmed},
            source_trust=trust,
            source_scope=session.domain,
            source_confidentiality="internal",
            project_id=session.project_id,
        )
        # deterministic dedup key → a retry can never store a second percept
        percept.integrity["content_hash"] = f"session:{session.id}"
        percept.seal()
        if store.insert_percept(percept) is None:
            if session.summary_percept_id is None:
                raise RuntimeError("summary percept already stored but its id "
                                   "was lost — inspect the percepts table")
            percept = store.get_percept(session.summary_percept_id)
            if percept is None:
                raise RuntimeError(f"summary percept "
                                   f"{session.summary_percept_id} disappeared")
        session.summary_percept_id = percept.id

        report = extract_percept(store, cfg, embedder, percept)
        new_ids = [m for m in report.inserted if m not in session.created_memory_ids]
        session.created_memory_ids = session.created_memory_ids + new_ids
        if session.project_id:
            for mid in new_ids:
                store.update_memory(mid, project_id=session.project_id)
        if session.judgment_snapshot_id:
            for mid in new_ids:
                mem = store.get_memory(mid)
                if mem is None:
                    continue
                payload = dict(mem.payload or {})
                payload["judgment_influenced"] = True
                payload["decision_origin"] = "twin_assisted"
                payload["judgment_snapshot_id"] = session.judgment_snapshot_id
                store.update_memory(mid, payload=payload)
        session.consolidation_status = ConsolidationStatus.completed
    except Exception as exc:
        # never silent: the session stays diagnosable and retryable
        session.consolidation_status = ConsolidationStatus.failed
        session.consolidation_error = f"{type(exc).__name__}: {exc}"[:300]
        logger.warning("session %s consolidation failed: %s",
                       session.id, type(exc).__name__)
    store.update_session(session)
    return session


def record_feedback(store: MemoryStore, session_id: str, verdict: str,
                    memory_id: Optional[str] = None, note: str = "",
                    scope: Optional[str] = None) -> CognitiveSession:
    """Explicit usefulness feedback — the raw material of product metrics.

    ``scope`` says what the verdict is about: the whole ``session``, the
    supplied ``pack``, or one ``memory`` (implied when memory_id is given).
    A memory_id must exist and must have been part of this session (supplied
    in the pack or created by it) — feedback about foreign memories would
    silently corrupt the usage metrics."""
    FeedbackVerdict(verdict)  # raises ValueError on unknown verdicts
    session = store.get_session(session_id)
    if session is None:
        raise ValueError(f"session {session_id} not found")

    if memory_id:
        if store.get_memory(memory_id) is None:
            raise ValueError(f"memory {memory_id} not found")
        if memory_id not in session.supplied_memory_ids + session.created_memory_ids:
            raise ValueError(f"memory {memory_id} was not supplied by or created "
                             f"in session {session_id}")
        scope = scope or "memory"
    else:
        scope = scope or "session"
    if scope not in FEEDBACK_SCOPES:
        raise ValueError(f"scope must be one of {FEEDBACK_SCOPES}")
    if scope == "memory" and not memory_id:
        raise ValueError("scope='memory' requires memory_id")

    store.append_session_feedback(session_id, {
        "scope": scope,
        "verdict": verdict,
        "memory_id": memory_id,
        "note": note,
        "at": now_iso(),
    })
    return store.get_session(session_id)


def ensure_project(store: MemoryStore, name: str, repos: Optional[list[str]] = None,
                   aliases: Optional[list[str]] = None) -> Project:
    """Create the project or merge new repos/aliases into the existing one —
    calling it again with more signals enriches the project instead of
    silently discarding them."""
    existing = store.find_project(name)
    if existing is not None:
        changed = False
        for repo in repos or []:
            if repo.lower() not in {r.lower() for r in existing.repos}:
                existing.repos.append(repo)
                changed = True
        current = {existing.name.lower()} | {a.lower() for a in existing.aliases}
        for alias in aliases or []:
            if alias.lower() not in current:
                existing.aliases.append(alias)
                changed = True
        if changed:
            store.update_project(existing)
        return existing
    project = Project(id=ids.project_id(), name=name,
                      repos=repos or [], aliases=aliases or [])
    store.insert_project(project)
    return project


def stale_sessions(store: MemoryStore,
                   max_idle_hours: float = DEFAULT_STALE_HOURS) -> list[CognitiveSession]:
    """Active sessions with no activity for longer than ``max_idle_hours``."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_idle_hours)).isoformat()
    return [
        s for s in store.list_sessions(status=SessionStatus.active.value, limit=10000)
        if (s.last_activity_at or s.started_at) < cutoff
    ]


def abandon_stale_sessions(store: MemoryStore,
                           max_idle_hours: float = DEFAULT_STALE_HOURS) -> list[str]:
    """Mark stale active sessions as abandoned. Returns the ids affected."""
    abandoned: list[str] = []
    for session in stale_sessions(store, max_idle_hours):
        if store.transition_session(session.id, SessionStatus.active.value,
                                    SessionStatus.abandoned.value, ended_at=now_iso()):
            session = store.get_session(session.id)
            session.consolidation_status = ConsolidationStatus.skipped
            store.update_session(session)
            abandoned.append(session.id)
    return abandoned
