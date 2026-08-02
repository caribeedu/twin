"""EpisodePhase assembly from cognitive member roles.

Phases are the ``goal → decision → execution → outcome`` arc of a WorkEpisode.
Roles are assigned by the **amygdala** cognition stage (an LLM classifier), not
by lexical rules — this module only does the *structural* work of ordering
members in time and grouping them into phases from the roles it is handed.

There is no semantic regex here: given a ``roles`` map (``member ref → kind``)
this module builds and persists phases idempotently. When no roles are provided
(no model / deferred), no phases are built — correlation never invents an arc.
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from ...clock import now_iso
from .models import (
    EpisodeLinkStatus,
    EpisodePhase,
    EpisodePhaseKind,
    EpisodePhaseStatus,
    WorkEpisode,
)
from .text import rich_excerpt

# Kinds whose contiguous members collapse into a single phase (noise reduction:
# a run of commits is one execution). Goal / decision / outcome stay per member
# so a pivot ("intended Kafka → chose SQS") survives as two decision phases —
# a structural policy over model-assigned roles, not a lexical rule.
_MERGEABLE_KINDS = frozenset({EpisodePhaseKind.execution, EpisodePhaseKind.other})


def _member_ref(link: Any) -> str:
    return f"{link.external_type or ''}:{link.external_id or ''}"


def _phase_id(episode_id: str, phase_key: str) -> str:
    digest = hashlib.sha256(
        f"{episode_id}|{phase_key}".encode("utf-8"),
    ).hexdigest()[:20]
    return f"epphase_{digest}"


def _first_line(content: str) -> str:
    for line in (content or "").splitlines():
        line = line.lstrip("# ").strip()
        if line:
            return line[:120]
    return ""


def _coerce_kind(value: Any) -> EpisodePhaseKind:
    try:
        return EpisodePhaseKind(str(value))
    except (ValueError, TypeError):
        return EpisodePhaseKind.other


def _ordered_active_links(store, episode_id: str) -> list[tuple[Any, Any]]:
    """Return (link, record) pairs for active links, sorted by occurred_at."""
    pairs: list[tuple[Any, Any, str]] = []
    for lk in store.list_episode_links(episode_id):
        st = getattr(lk.status, "value", lk.status)
        if st != EpisodeLinkStatus.active.value:
            continue
        rec = None
        occurred = ""
        if lk.connector_record_id and hasattr(store, "get_connector_record"):
            rec = store.get_connector_record(lk.connector_record_id)
            if rec is not None:
                occurred = rec.occurred_at or ""
        pairs.append((lk, rec, occurred))
    # Tie-break by member ref for stable ordering when times collide.
    pairs.sort(key=lambda t: (t[2] or "~", _member_ref(t[0])))
    return [(lk, rec) for lk, rec, _o in pairs]


def member_briefs(store, ep: WorkEpisode) -> list[dict[str, Any]]:
    """Structured, evidence-only view of an episode's active members.

    This is the input the amygdala classifier reasons over — external type,
    time and a denser content excerpt (title + body, not headline alone).
    No conclusions, no roles.
    """
    from ..actor_labels import humanize_record_text

    briefs: list[dict[str, Any]] = []
    for lk, rec in _ordered_active_links(store, ep.id):
        content = getattr(rec, "content", "") or ""
        if rec is not None:
            content = humanize_record_text(store, rec, content)
        briefs.append({
            "ref": _member_ref(lk),
            "external_type": lk.external_type or "",
            "occurred_at": getattr(rec, "occurred_at", "") or "",
            "excerpt": rich_excerpt(content) or _first_line(content) or content[:120],
        })
    return briefs


def build_phases_from_roles(
    store,
    ep: WorkEpisode,
    roles: dict[str, Any],
    *,
    brain_stage: str = "amygdala",
) -> list[EpisodePhase]:
    """Assemble ordered phases from a model-assigned ``roles`` map.

    ``roles`` maps ``member ref → {"kind": ..., "salience": ...}`` (or bare
    kind strings). Members with no role default to ``other``. Contiguous
    mergeable-kind members collapse into one phase; goal / decision / outcome
    stay per member so pivots and framing survive.
    """
    pairs = _ordered_active_links(store, ep.id)
    if not pairs:
        return []

    classified: list[tuple[Any, Any, EpisodePhaseKind, str]] = []
    for lk, rec in pairs:
        ref = _member_ref(lk)
        info = roles.get(ref)
        kind_val = info.get("kind") if isinstance(info, dict) else info
        kind = _coerce_kind(kind_val)
        occurred = getattr(rec, "occurred_at", "") or ""
        classified.append((lk, rec, kind, occurred))

    phases: list[EpisodePhase] = []
    order = 0
    i = 0
    n = len(classified)
    while i < n:
        kind = classified[i][2]
        j = i
        if kind in _MERGEABLE_KINDS:
            while j + 1 < n and classified[j + 1][2] == kind:
                j += 1
        run = classified[i:j + 1]
        link_ids = [lk.id for lk, _r, _k, _o in run]
        refs = [_member_ref(lk) for lk, _r, _k, _o in run]
        times = [o for _lk, _r, _k, o in run if o]
        anchor = refs[0] if refs else f"idx{order}"
        phase_key = f"{kind.value}:{anchor}"
        summary = ""
        for _lk, rec, _k, _o in run:
            summary = _first_line(getattr(rec, "content", "") or "")
            if summary:
                break
        salience = 0.6
        first_info = roles.get(refs[0]) if refs else None
        if isinstance(first_info, dict) and first_info.get("salience") is not None:
            try:
                salience = float(first_info["salience"])
            except (TypeError, ValueError):
                salience = 0.6
        phases.append(EpisodePhase(
            id=_phase_id(ep.id, phase_key),
            episode_id=ep.id,
            vault_id=ep.vault_id,
            kind=kind,
            phase_key=phase_key,
            order=order,
            started_at=(sorted(times)[0] if times else None),
            ended_at=(sorted(times)[-1] if times else None),
            status=EpisodePhaseStatus.active,
            member_external_refs=refs,
            member_link_ids=link_ids,
            summary=summary,
            confidence=round(min(1.0, max(0.1, salience)), 2),
            provenance={
                "method": "llm",
                "twin_influenced": True,
                "brain_stage": brain_stage,
            },
        ))
        order += 1
        i = j + 1
    return phases


def persist_phases(
    store, ep: WorkEpisode, phases: list[EpisodePhase],
) -> list[EpisodePhase]:
    """Idempotently persist phases (stable ids by ``phase_key``).

    Existing phases whose ``phase_key`` no longer appears are removed; those
    that persist keep their ``created_at`` so edge references stay valid.
    """
    if not hasattr(store, "list_episode_phases"):
        return phases
    computed_by_id = {p.id: p for p in phases}
    existing = {p.id: p for p in store.list_episode_phases(ep.id)}
    for pid in list(existing):
        if pid not in computed_by_id:
            store.delete_episode_phase(pid)
    for p in phases:
        if p.id in existing:
            prior = existing[p.id]
            p.created_at = prior.created_at or p.created_at
            p.updated_at = now_iso()
            store.update_episode_phase(p)
        else:
            store.insert_episode_phase(p)
    return phases


def clear_phases(store, ep: WorkEpisode) -> None:
    """Drop all phases for an episode (deferred / no-model reconciliation)."""
    if not hasattr(store, "list_episode_phases"):
        return
    for p in store.list_episode_phases(ep.id):
        store.delete_episode_phase(p.id)


def phase_by_key(store, episode_id: str, phase_key: str) -> Optional[EpisodePhase]:
    for p in store.list_episode_phases(episode_id):
        if p.phase_key == phase_key:
            return p
    return None
