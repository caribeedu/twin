"""Host ↔ cognitive session binding.

Native adapters call this module. They never assemble Context Packs or write
confirmed Memory / Judgment — the same core used by MCP / CLI / API does.

Binding contract:
- ``(host_type, external_session_id, occurrence)`` is unique;
- after SessionEnd, a new SessionStart opens occurrence N+1 + new CognitiveSession;
- security fields (domain/project/persona/purpose/audience/vault) freeze at bind;
- observations are idempotent by ``event_id``.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from twin import ids
from twin.clock import now_iso
from twin.config import UNCLASSIFIED_DOMAIN, Config
from twin.store.embeddings import Embedder
from twin.store.models import (
    HostSessionBinding,
    InterventionRecommendation,
    ClaimStatus,
    SessionStatus,
)
from twin.store.store.base import MemoryStore
from twin.store.store.host_binding_mixin import is_unique_violation
from twin.inject.context_pack import ContextPack, build_context_pack
from .sessions import SessionStart, complete_session, observe_session, start_session

logger = logging.getLogger("twin.cognize.services.host_session")

NATIVE_HOSTS = frozenset({
    "claude-code", "codex", "codex-app-server", "native", "fake-host",
})


def host_instance_id(cfg: Config, host_type: str) -> str:
    """Stable, non-reversible id for *this* host installation.

    Derived from the Twin home + host type + user home so the same machine +
    host produces the same id across sessions, without ever leaking a raw path.
    Used for provenance / identity — never as the privacy ``tool_id`` (native
    sessions always resolve to ``native-host``).
    """
    try:
        user_home = str(Path.home())
    except Exception:
        user_home = ""
    key = "\x1f".join([
        str(getattr(cfg, "home", "") or ""),
        (host_type or "native").lower(),
        user_home,
    ])
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return f"host:{digest}"

ALLOWED_OBSERVE_KINDS = frozenset({
    "session_start",
    "user_message",
    "assistant_result",
    "turn_completed",
    "tool_requested",
    "tool_completed",
    "tool_failed",
    "file_context",
    "project_context",
})

_TOOL_KINDS = frozenset({"tool_requested", "tool_completed", "tool_failed"})


@dataclass
class NativeSessionStart:
    binding: HostSessionBinding
    started: SessionStart


@dataclass
class ObserveResult:
    binding: HostSessionBinding
    duplicated: bool = False


class BindingScopeError(ValueError):
    """Host tried to widen frozen security scope on an open binding."""


def resolve_observation_event_id(
    *,
    event_id: Optional[str] = None,
    delivery_id: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    tool_phase: Optional[str] = None,
    kind: str = "",
    sequence: Optional[int] = None,
) -> str:
    """Stable idempotency key — never fingerprint content alone.

    Preference:
    1. host ``event_id``
    2. ``delivery_id``
    3. ``tool_call_id`` + phase (same tool call = same delivery)
    4. host ``sequence``
    5. allocate a unique id (identical text stays distinct; retries may dup)
    """
    if event_id:
        return str(event_id)
    if delivery_id:
        return f"delivery:{delivery_id}"
    if tool_call_id and kind in _TOOL_KINDS:
        phase = tool_phase or kind
        return f"tool:{tool_call_id}:{phase}"
    if sequence is not None:
        return f"seq:{int(sequence)}:{kind}"
    # No trustworthy identity → do not collapse equal payloads.
    return ids.new_id("hostevent")


def _domain_is_frozen(domain: Optional[str]) -> bool:
    """True when domain is a real (non-placeholder) frozen value."""
    return bool(domain) and domain != UNCLASSIFIED_DOMAIN


def _scope_field_is_frozen(value: Optional[str]) -> bool:
    """True when a persona/purpose/audience value is intentionally frozen.

    ``unknown`` / empty are placeholders from an unclassified SessionStart
    (restricted access) and may be upgraded once with the domain.
    """
    return bool(value) and value not in ("unknown", UNCLASSIFIED_DOMAIN)


def _assert_frozen_scope(
    binding: HostSessionBinding,
    *,
    domain: Optional[str],
    project: Optional[str],
    persona: Optional[str],
    purpose: Optional[str],
    audience: Optional[str],
) -> None:
    """Reject silent scope widening on an open binding.

    ``unclassified`` domain and ``unknown`` persona/purpose/audience are not
    frozen — a later real *domain* may upgrade once when the host later
    supplies semantic input. Authorization fields (persona/purpose/audience/
    principal) are not inferred from dialogue.
    """
    if (
        domain
        and _domain_is_frozen(binding.domain)
        and domain != binding.domain
    ):
        raise BindingScopeError(
            f"domain mismatch: binding frozen to {binding.domain!r}, "
            f"got {domain!r} — start a new host session"
        )
    if persona and _scope_field_is_frozen(binding.persona) and persona != binding.persona:
        raise BindingScopeError(
            f"persona mismatch: binding frozen to {binding.persona!r}"
        )
    if purpose and _scope_field_is_frozen(binding.purpose) and purpose != binding.purpose:
        raise BindingScopeError(
            f"purpose mismatch: binding frozen to {binding.purpose!r}"
        )
    if audience and _scope_field_is_frozen(binding.audience) and audience != binding.audience:
        raise BindingScopeError(
            f"audience mismatch: binding frozen to {binding.audience!r}"
        )


def bind_and_start(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    *,
    host_type: str,
    external_session_id: str,
    query: str,
    cwd: Optional[str] = None,
    domain: Optional[str] = None,
    project: Optional[str] = None,
    task_profile: Optional[str] = None,
    max_tokens: int = 1200,
    persona: str = "individual",
    purpose: str = "task_execution",
    audience: str = "self",
    metadata: Optional[dict[str, Any]] = None,
    deadline_monotonic: Optional[float] = None,
) -> NativeSessionStart:
    """Open or reuse an *active* binding; after SessionEnd, open a new occurrence."""
    if not (external_session_id or "").strip():
        raise ValueError("external_session_id required")
    host_type = (host_type or "native").lower()
    external_session_id = external_session_id.strip()

    existing = store.find_active_host_session_binding(
        host_type=host_type, external_session_id=external_session_id,
    )
    if existing is not None:
        _assert_frozen_scope(
            existing,
            domain=domain, project=project,
            persona=persona, purpose=purpose, audience=audience,
        )
        if project:
            found = store.get_project(project) or store.find_project(project)
            if found is None:
                raise ValueError(f"project {project!r} not found")
            if existing.project_id and found.id != existing.project_id:
                raise BindingScopeError(
                    f"project mismatch: binding frozen to {existing.project_id!r}"
                )
        pack = request_context_pack(
            store, cfg, embedder,
            query=query,
            binding=existing,
            cwd=cwd,
            max_tokens=max_tokens,
            client=host_type,
            deadline_monotonic=deadline_monotonic,
        )
        session = store.get_session(existing.cognitive_session_id)
        if session is None:
            raise ValueError(
                f"binding {existing.id} points at missing session "
                f"{existing.cognitive_session_id}"
            )
        started = SessionStart(
            session=session, pack=pack,
            reading_confidences={}, observer_mode="native",
        )
        return NativeSessionStart(binding=existing, started=started)

    # Re-check under race: peer may have won between lookup and create.
    existing = store.find_active_host_session_binding(
        host_type=host_type, external_session_id=external_session_id,
    )
    if existing is not None:
        return bind_and_start(
            store, cfg, embedder,
            host_type=host_type, external_session_id=external_session_id,
            query=query, cwd=cwd, domain=domain, project=project,
            task_profile=task_profile, max_tokens=max_tokens,
            persona=persona, purpose=purpose, audience=audience,
            metadata=metadata,
            deadline_monotonic=deadline_monotonic,
        )

    occurrence = store.next_host_binding_occurrence(
        host_type=host_type, external_session_id=external_session_id,
    )
    started = start_session(
        store, cfg, embedder, query,
        client=host_type,
        cwd=cwd, domain=domain, project=project,
        task_profile=task_profile, max_tokens=max_tokens,
        persona=persona, purpose=purpose, audience=audience,
        tool_id=None,
        surface="native",
        deadline_monotonic=deadline_monotonic,
    )
    # Vault comes from project / explicit metadata — never inferred from domain name.
    vault_id = None
    if started.session.project_id:
        proj = store.get_project(started.session.project_id)
        if proj is not None:
            vault_id = (proj.metadata or {}).get("vault_id")
    if not vault_id and isinstance(metadata, dict):
        vault_id = metadata.get("vault_id")
    if not vault_id:
        vault_id = None
    binding_meta = dict(metadata or {})
    # Stable installation identity for provenance — never the raw path, never
    # the privacy tool_id (native sessions stay ``native-host``).
    binding_meta.setdefault("host_instance", host_instance_id(cfg, host_type))
    binding = HostSessionBinding(
        host_type=host_type,
        external_session_id=external_session_id,
        occurrence=occurrence,
        cognitive_session_id=started.session.id,
        project_id=started.session.project_id,
        principal_id=started.session.principal_id,
        vault_id=vault_id,
        domain=started.session.domain,
        persona=started.session.persona or persona,
        purpose=started.session.purpose or purpose,
        audience=started.session.audience or audience,
        task_profile=started.session.task_profile or task_profile,
        started_at=started.session.started_at or now_iso(),
        metadata=binding_meta,
    )
    try:
        store.insert_host_session_binding(binding)
    except Exception as exc:
        if not is_unique_violation(exc):
            raise
        # Peer won the race — abandon orphan CognitiveSession, return winner.
        logger.info(
            "host binding race lost host=%s ext=%s occ=%s; abandoning %s",
            host_type, external_session_id, occurrence, started.session.id,
        )
        try:
            store.transition_session(
                started.session.id,
                SessionStatus.active.value,
                SessionStatus.abandoned.value,
                ended_at=now_iso(),
            )
        except Exception:
            logger.exception("failed to abandon orphan session %s", started.session.id)
        winner = store.find_active_host_session_binding(
            host_type=host_type, external_session_id=external_session_id,
        )
        if winner is None:
            raise
        pack = request_context_pack(
            store, cfg, embedder,
            query=query, binding=winner, cwd=cwd,
            max_tokens=max_tokens, client=host_type,
            deadline_monotonic=deadline_monotonic,
        )
        session = store.get_session(winner.cognitive_session_id)
        if session is None:
            raise ValueError(
                f"winning binding {winner.id} points at missing session"
            )
        return NativeSessionStart(
            binding=winner,
            started=SessionStart(
                session=session, pack=pack,
                reading_confidences={}, observer_mode="native",
            ),
        )
    # Fresh start_session already built a pack; when a deadline was set and
    # the pack is still needed under budget pressure, callers may re-request.
    # For first-open we keep the session pack (domain may be unclassified /
    # empty). Deadline applies to re-pack paths above and explicit pack_request.
    return NativeSessionStart(binding=binding, started=started)


def resolve_active_binding(
    store: MemoryStore,
    *,
    host_type: str,
    external_session_id: str,
) -> Optional[HostSessionBinding]:
    if not external_session_id:
        return None
    return store.find_active_host_session_binding(
        host_type=host_type, external_session_id=external_session_id,
    )


def observe_host_event(
    store: MemoryStore,
    *,
    host_type: str,
    external_session_id: str,
    event_kind: str,
    note: str = "",
    ref: Optional[str] = None,
    event_id: Optional[str] = None,
    delivery_id: Optional[str] = None,
    sequence: Optional[int] = None,
    tool_call_id: Optional[str] = None,
    tool_phase: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
    redacted: bool = False,
    redaction_categories: Optional[list[str]] = None,
) -> ObserveResult:
    """Record a host observation on the *active* binding (idempotent)."""
    if event_kind not in ALLOWED_OBSERVE_KINDS:
        raise ValueError(f"unsupported observation kind: {event_kind}")
    binding = resolve_active_binding(
        store, host_type=host_type, external_session_id=external_session_id,
    )
    if binding is None:
        raise ValueError(
            f"no active binding for {host_type}:{external_session_id}"
        )
    eid = resolve_observation_event_id(
        event_id=event_id,
        delivery_id=delivery_id,
        tool_call_id=tool_call_id,
        tool_phase=tool_phase,
        kind=event_kind,
        sequence=sequence,
    )
    inserted = store.insert_host_observed_event(
        host_type=host_type,
        external_session_id=external_session_id,
        occurrence=binding.occurrence,
        event_id=eid,
        binding_id=binding.id,
        kind=event_kind,
        created_at=now_iso(),
    )
    if not inserted:
        return ObserveResult(binding=binding, duplicated=True)

    artifact: dict[str, Any] = {
        "kind": event_kind,
        "host_type": host_type,
        "event_id": eid,
        "occurrence": binding.occurrence,
    }
    if note:
        artifact["note"] = note
    if ref:
        artifact["ref"] = ref
    if tool_call_id:
        artifact["tool_call_id"] = tool_call_id
    if tool_phase:
        artifact["tool_phase"] = tool_phase
    if redacted:
        artifact["redacted"] = True
        artifact["redaction_categories"] = list(redaction_categories or [])
    if extra:
        artifact["host"] = extra
    observe_session(store, binding.cognitive_session_id, artifact)
    return ObserveResult(binding=binding, duplicated=False)


@dataclass
class DomainUpgrade:
    """Result of upgrading an unclassified binding (domain only — no pack)."""

    binding: HostSessionBinding
    previous_domain: str
    resolved_domain: str


@dataclass
class DomainUpgradePack:
    """Result of upgrading an unclassified binding and packing context."""

    binding: HostSessionBinding
    pack: ContextPack
    previous_domain: str
    resolved_domain: str


def _refresh_placeholder_access(
    store: MemoryStore, cfg: Config,
    binding: HostSessionBinding, resolved: str,
):
    """Re-resolve access for packing after a domain upgrade.

    Uses the binding's existing authorization identity (persona/purpose/
    audience/principal). Domain upgrade never invents a more permissive
    identity from dialogue — only ``requested_domains`` changes.
    """
    from twin.privacy.identity import ensure_local_identity, resolve_access
    from twin.privacy.yaml_io import bootstrap_policy_set

    bootstrap_policy_set(store, policies_path=cfg.policies_path)
    ensure_local_identity(store)
    return resolve_access(
        store,
        surface="native",
        client=binding.host_type or "native",
        tool_id=None,
        persona=binding.persona if _scope_field_is_frozen(binding.persona) else "individual",
        purpose=binding.purpose if _scope_field_is_frozen(binding.purpose) else "task_execution",
        audience=binding.audience if _scope_field_is_frozen(binding.audience) else "self",
        principal_id=(
            binding.principal_id
            if binding.principal_id and binding.principal_id != "unknown"
            else None
        ),
        project_id=binding.project_id,
        session_id=binding.cognitive_session_id,
        requested_domains=(
            [resolved] if resolved and resolved != UNCLASSIFIED_DOMAIN else []
        ),
    )


def _apply_upgraded_scope(target, *, domain: str, reading, access) -> None:
    """Apply resolved *domain* (and optional task profile) only.

    Persona / purpose / audience / principal are authorization identity —
    they stay as bound at session start. ``access`` is used for packing, not
    to rewrite those fields from semantic classification.
    """
    _ = access  # packing path consumes access; scope fields stay frozen
    target.domain = domain
    if reading.task_profile and (
        not target.task_profile or target.task_profile == "general"
    ):
        target.task_profile = reading.task_profile


def maybe_upgrade_domain(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    *,
    binding: HostSessionBinding,
    query: str,
    cwd: Optional[str] = None,
) -> Optional[DomainUpgrade]:
    """If binding domain is unclassified, try to resolve it from ``query``.

    Does not assemble a context pack — callers decide whether injection is
    possible before paying for retrieval. Returns ``None`` when domain is
    already frozen, still unclassified, or ``query`` is empty. Never widens
    a frozen real domain. Never rewrites persona / purpose / audience /
    principal.
    """
    if not (query or "").strip():
        return None
    previous = binding.domain or UNCLASSIFIED_DOMAIN
    if _domain_is_frozen(previous):
        return None

    from .observer import resolve_context_domain

    reading = resolve_context_domain(
        store, cfg, embedder, query, cwd=cwd, existing_domain=previous,
    )
    resolved = reading.domain or UNCLASSIFIED_DOMAIN
    if not _domain_is_frozen(resolved):
        return None

    access = _refresh_placeholder_access(store, cfg, binding, resolved)

    _apply_upgraded_scope(binding, domain=resolved, reading=reading, access=access)
    meta = dict(binding.metadata or {})
    meta["domain_upgraded_from"] = previous
    meta["domain_upgraded_at"] = now_iso()
    meta["domain_resolved_via"] = reading.mode
    binding.metadata = meta
    store.update_host_session_binding(binding)

    session = store.get_session(binding.cognitive_session_id)
    if session is not None:
        _apply_upgraded_scope(session, domain=resolved, reading=reading, access=access)
        store.update_session(session)

    logger.info(
        "host binding %s domain %s → %s persona=%s",
        binding.id, previous, resolved, binding.persona,
    )
    return DomainUpgrade(
        binding=binding,
        previous_domain=previous,
        resolved_domain=resolved,
    )


def maybe_upgrade_domain_and_pack(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    *,
    binding: HostSessionBinding,
    query: str,
    cwd: Optional[str] = None,
    max_tokens: int = 1200,
    deadline_monotonic: Optional[float] = None,
) -> Optional[DomainUpgradePack]:
    """Upgrade domain then pack — prefer ``maybe_upgrade_domain`` when the
    host cannot inject, so pack assembly is skipped."""
    upgraded = maybe_upgrade_domain(
        store, cfg, embedder, binding=binding, query=query, cwd=cwd,
    )
    if upgraded is None:
        return None
    pack = request_context_pack(
        store, cfg, embedder,
        query=query,
        binding=upgraded.binding,
        cwd=cwd,
        max_tokens=max_tokens,
        client=upgraded.binding.host_type or "native",
        deadline_monotonic=deadline_monotonic,
    )
    return DomainUpgradePack(
        binding=upgraded.binding,
        pack=pack,
        previous_domain=upgraded.previous_domain,
        resolved_domain=upgraded.resolved_domain,
    )


def request_context_pack(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    *,
    query: str,
    binding: Optional[HostSessionBinding] = None,
    session_id: Optional[str] = None,
    cwd: Optional[str] = None,
    domain: Optional[str] = None,
    project: Optional[str] = None,
    task_profile: Optional[str] = None,
    max_tokens: int = 1200,
    persona: str = "individual",
    purpose: str = "memory_retrieval",
    audience: str = "self",
    client: str = "native",
    deadline_monotonic: Optional[float] = None,
) -> ContextPack:
    """Proactive Context Pack — assembled only by the cognitive core.

    When ``binding`` is set, frozen security fields win; divergent caller
    fields must already have been rejected by the caller. Never calls the
    local LLM for domain on this path — domain comes from the binding /
    session / explicit argument, or a search vote when unbound.
    """
    from twin.config import UNCLASSIFIED_DOMAIN
    from twin.privacy.identity import ensure_local_identity, resolve_access
    from twin.privacy.yaml_io import bootstrap_policy_set
    from .observer import resolve_context_domain
    from .task_profiles import infer_task_profile

    if binding is not None:
        session_id = binding.cognitive_session_id
        domain = binding.domain
        project_id = binding.project_id
        task_profile = binding.task_profile or task_profile
        persona = binding.persona or persona
        purpose = binding.purpose or purpose
        audience = binding.audience or audience
        client = binding.host_type or client
    else:
        project_id = None
        if project:
            found = store.get_project(project) or store.find_project(project)
            if found is None:
                raise ValueError(f"project {project!r} not found")
            project_id = found.id

    if binding is not None:
        session_domain = domain or UNCLASSIFIED_DOMAIN
        if not task_profile or task_profile == "general":
            inferred, _ = infer_task_profile(query)
            if inferred != "general":
                task_profile = inferred
    else:
        reading = resolve_context_domain(
            store, cfg, embedder, query, cwd=cwd, existing_domain=domain,
        )
        if project_id is None:
            project_id = reading.project_id
        if session_id:
            session = store.get_session(session_id)
            if session is not None:
                project_id = project_id or session.project_id
                domain = domain or session.domain
                task_profile = task_profile or session.task_profile
        session_domain = domain or reading.domain
        task_profile = task_profile or reading.task_profile

    bootstrap_policy_set(store, policies_path=cfg.policies_path)
    ensure_local_identity(store)
    # Any HostSessionBinding is a native surface; unbound packs keep CLI/MCP.
    if binding is not None:
        surface = "native"
        client_key = binding.host_type or client
    elif (client or "") in NATIVE_HOSTS:
        surface = "native"
        client_key = client
    else:
        surface = "cli"
        client_key = client
    access_domains = (
        [session_domain]
        if session_domain and session_domain != UNCLASSIFIED_DOMAIN
        else []
    )
    access = resolve_access(
        store,
        surface=surface,
        client=client_key or None,
        tool_id=None if surface == "native" else client,
        persona=persona,
        purpose=purpose,
        audience=audience,
        project_id=project_id,
        session_id=session_id,
        requested_domains=access_domains,
    )
    # Frozen vault is an explicit pack invariant: session/project resolve the
    # same vault; binding.vault_id is the audit anchor and cannot widen silently.
    if binding is not None and binding.vault_id:
        access = access.model_copy(update={
            "metadata": {
                **(access.metadata or {}),
                "frozen_vault_id": binding.vault_id,
                "frozen_domain": binding.domain,
            },
        })
    return build_context_pack(
        store, cfg, embedder, query,
        target_domain=session_domain,
        max_tokens=max_tokens,
        task_profile=task_profile or "general",
        project_id=project_id,
        access=access,
        deadline_monotonic=deadline_monotonic,
    )


def _dialogue_text_for_domain(store: MemoryStore, session_id: str) -> str:
    """Fold user/assistant session artifacts into multi-message evidence."""
    session = store.get_session(session_id)
    if session is None:
        return ""
    lines: list[str] = []
    if session.initial_query:
        lines.append(session.initial_query)
    for art in session.artifacts or []:
        kind = str(art.get("kind") or "")
        if kind not in ("user_message", "assistant_result", "note"):
            continue
        note = (art.get("note") or art.get("ref") or "").strip()
        if not note or note == "[turn_end]":
            continue
        lines.append(note)
    return "\n".join(lines).strip()


def maybe_enqueue_domain_resolve(
    store: MemoryStore,
    binding: HostSessionBinding,
    *,
    cwd: Optional[str] = None,
) -> str:
    """Enqueue background LLM domain resolve when binding is still unclassified.

    Hot-path session start / user_message only search-vote. When that fails,
    a ``session_domain_resolve`` job (twin-runtime) reads multi-message evidence
    and freezes the domain. No-op without a runtime-capable store.
    """
    if _domain_is_frozen(binding.domain):
        return ""
    if not hasattr(store, "insert_runtime_job"):
        return ""
    from twin.interfaces.runtime.models import JobKind
    from twin.interfaces.runtime.queue import RuntimeQueue

    job = RuntimeQueue(store).enqueue(
        JobKind.session_domain_resolve,
        payload={
            "binding_id": binding.id,
            "session_id": binding.cognitive_session_id,
            "cwd": cwd or "",
        },
        idempotency_key=f"session_domain_resolve:{binding.id}",
        priority=35,
        vault_id=binding.vault_id or "vault_general",
    )
    return job.id


def maybe_enqueue_session_complete(
    store: MemoryStore,
    *,
    session_id: str,
    summary: str = "",
    abandoned: bool = False,
    summary_origin: str = "assistant",
    vault_id: str = "vault_general",
) -> str:
    """Enqueue background session consolidation + extract (twin-runtime)."""
    if not hasattr(store, "insert_runtime_job"):
        return ""
    from twin.interfaces.runtime.models import JobKind
    from twin.interfaces.runtime.queue import RuntimeQueue

    job = RuntimeQueue(store).enqueue(
        JobKind.session_complete,
        payload={
            "session_id": session_id,
            "summary": summary,
            "abandoned": abandoned,
            "summary_origin": summary_origin,
        },
        idempotency_key=f"session_complete:{session_id}",
        priority=30,
        vault_id=vault_id or "vault_general",
    )
    return job.id


def end_host_session(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    *,
    host_type: str,
    external_session_id: str,
    summary: str = "",
    abandoned: bool = False,
    summary_origin: str = "assistant",
) -> Optional[HostSessionBinding]:
    """End the active binding. Consolidation runs in the background when possible.

    Closes the binding immediately so the next SessionStart can open occurrence
    N+1 without waiting for extract. Prefers a ``session_complete`` runtime job;
    falls back to in-process ``complete_session`` when the store has no runtime
    queue (tests / single-process installs).
    """
    binding = resolve_active_binding(
        store, host_type=host_type, external_session_id=external_session_id,
    )
    if binding is None:
        logger.warning(
            "session_end with no active binding host=%s ext=%s (no-op)",
            host_type, external_session_id,
        )
        return None
    if binding.ended_at:
        return binding

    # Close binding first — occurrence N+1 must not wait on extract/LLM.
    binding.ended_at = now_iso()
    store.update_host_session_binding(binding)

    job_id = maybe_enqueue_session_complete(
        store,
        session_id=binding.cognitive_session_id,
        summary=summary,
        abandoned=abandoned,
        summary_origin=summary_origin,
        vault_id=binding.vault_id or "vault_general",
    )
    if not job_id:
        complete_session(
            store, cfg, embedder, binding.cognitive_session_id,
            summary=summary, abandoned=abandoned,
            summary_origin=summary_origin,
        )
    else:
        logger.info(
            "session_complete enqueued job=%s session=%s binding=%s",
            job_id, binding.cognitive_session_id, binding.id,
        )
    return binding


def apply_background_domain_resolve(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    *,
    binding_id: str,
    cwd: Optional[str] = None,
) -> dict[str, Any]:
    """Worker path: LLM-classify domain from multi-message session evidence.

    Used by the ``session_domain_resolve`` runtime handler. Safe to call when
    the binding is already frozen (no-op). Never emits host stdout.
    """
    from .observer import read_context

    binding = store.get_host_session_binding(binding_id)
    if binding is None:
        return {"ok": False, "reason": "binding_not_found"}
    if _domain_is_frozen(binding.domain):
        return {"ok": True, "reason": "already_frozen", "domain": binding.domain}

    text = _dialogue_text_for_domain(store, binding.cognitive_session_id)
    if not text:
        return {"ok": False, "reason": "no_dialogue"}

    reading = read_context(store, cfg, text, cwd=cwd)
    resolved = reading.domain or UNCLASSIFIED_DOMAIN
    if not _domain_is_frozen(resolved):
        return {
            "ok": False,
            "reason": reading.fallback_reason or "still_unclassified",
            "mode": reading.mode,
        }

    access = _refresh_placeholder_access(store, cfg, binding, resolved)
    previous = binding.domain or UNCLASSIFIED_DOMAIN
    _apply_upgraded_scope(binding, domain=resolved, reading=reading, access=access)
    meta = dict(binding.metadata or {})
    meta["domain_upgraded_from"] = previous
    meta["domain_upgraded_at"] = now_iso()
    meta["domain_resolved_via"] = reading.mode
    meta["domain_resolved_background"] = True
    # Option A: pack is not pushed mid-turn. Mark pending so the next host
    # event that supports context injection can emit it.
    meta["pending_context_pack"] = True
    binding.metadata = meta
    store.update_host_session_binding(binding)

    session = store.get_session(binding.cognitive_session_id)
    if session is not None:
        _apply_upgraded_scope(session, domain=resolved, reading=reading, access=access)
        store.update_session(session)

    return {
        "ok": True,
        "domain": resolved,
        "previous_domain": previous,
        "mode": reading.mode,
        "binding_id": binding.id,
        "session_id": binding.cognitive_session_id,
    }


def recommend_intervention(
    store: MemoryStore,
    *,
    session_id: str,
    draft_text: str,
    limit: int = 5,
) -> list[InterventionRecommendation]:
    """Heuristic *possible decision reversal cue* (display-only).

    Not a semantic contradiction detector. May false-positive; never modifies
    host state. Stronger actions require a future semantic model.
    """
    text = (draft_text or "").strip()
    if not text:
        return []
    session = store.get_session(session_id)
    if session is None:
        return []

    candidates = []
    for mid in list(session.supplied_claim_ids or [])[:50]:
        mem = store.get_claim(mid)
        if mem is not None:
            candidates.append(mem)
    if not candidates and session.project_id:
        candidates = store.list_claims(
            project_id=session.project_id, status="confirmed", limit=40,
        )

    reverse_cues = (
        "instead", "revert", "undo", "no longer", "don't use", "do not use",
        "replace with", "abandon", "cancel", "postpone", "never mind",
    )
    lowered = text.lower()
    has_reverse = any(c in lowered for c in reverse_cues)
    out: list[InterventionRecommendation] = []
    for mem in candidates:
        if getattr(mem.status, "value", mem.status) not in (
            ClaimStatus.confirmed.value, "confirmed",
        ):
            continue
        if mem.type.value != "decision" and str(mem.type) != "decision":
            continue
        hay = f"{mem.title} {mem.summary}".lower()
        tokens = [t for t in hay.replace(",", " ").split() if len(t) >= 4][:12]
        overlap = sum(1 for t in tokens if t in lowered)
        if overlap < 2 and not (has_reverse and overlap >= 1):
            continue
        urgency = "high" if has_reverse and overlap >= 2 else "medium"
        out.append(InterventionRecommendation(
            type="warning",
            reason=(
                f"Possible decision reversal cue vs confirmed decision "
                f"{mem.id}: {mem.title}"
            ),
            urgency=urgency,
            session_id=session_id,
            supported_actions=["display"],
            requires_confirmation=False,
            metadata={
                "claim_id": mem.id,
                "overlap": overlap,
                "heuristic": "token_overlap_reverse_cue",
            },
        ))
        if len(out) >= limit:
            break
    return out
