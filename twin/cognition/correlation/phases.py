"""Deterministic EpisodePhase assignment.

An episode's active members are ordered in time and mapped to an arc of
phases (goal → decision → execution → outcome). Phases are revisable
structure derived from evidence — never Memory or Judgment. Assignment is
heuristic-first (no LLM in this layer); LLM labeling is reserved for later
reflect enrichment.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Optional

from ...clock import now_iso
from .models import (
    EpisodeLinkStatus,
    EpisodePhase,
    EpisodePhaseKind,
    EpisodePhaseStatus,
    WorkEpisode,
)

# external_type substrings → default phase kind. Ordered by specificity; first
# match wins. Kept conservative — an unmatched type falls back to ``other``.
_TYPE_KIND: tuple[tuple[str, EpisodePhaseKind], ...] = (
    ("issue", EpisodePhaseKind.goal),
    ("discussion", EpisodePhaseKind.goal),
    ("epic", EpisodePhaseKind.goal),
    ("story", EpisodePhaseKind.goal),
    ("review", EpisodePhaseKind.decision),
    ("pull_request", EpisodePhaseKind.decision),
    ("pull request", EpisodePhaseKind.decision),
    ("merge_request", EpisodePhaseKind.decision),
    ("proposal", EpisodePhaseKind.decision),
    ("rfc", EpisodePhaseKind.decision),
    ("commit", EpisodePhaseKind.execution),
    ("push", EpisodePhaseKind.execution),
    ("deploy", EpisodePhaseKind.execution),
    ("build", EpisodePhaseKind.execution),
    ("release", EpisodePhaseKind.outcome),
    ("tag", EpisodePhaseKind.outcome),
    ("ship", EpisodePhaseKind.outcome),
)

# Content language that promotes a member to an ``outcome`` regardless of type.
_OUTCOME_RE = re.compile(
    r"\b(merged|shipped|released|closed|resolved|deployed|done|"
    r"landed|completed|reverted)\b",
    re.I,
)
# Content language that marks a decision (over its default type).
_DECISION_RE = re.compile(
    r"\b(decided|decision|chose|choose|will use|go with|instead|"
    r"pivot|switch to|adopt)\b",
    re.I,
)
# Language that overturns an earlier decision — forces a new phase boundary so
# "intended X → chose Y" is not collapsed into a single decision phase.
_REVERSAL_RE = re.compile(
    r"\b(instead|revert|reverted|reverting|pivot|pivoted|"
    r"changed our mind|no longer|abandon|abandoned|"
    r"switch(?:ed)? to|replace(?:d)? with|supersed)\b",
    re.I,
)


def _phase_kind_for(external_type: str, content: str) -> EpisodePhaseKind:
    text = content or ""
    et = (external_type or "").lower()
    # Outcome language is the strongest signal (a "merged" commit closes an arc).
    if _OUTCOME_RE.search(text):
        return EpisodePhaseKind.outcome
    for needle, kind in _TYPE_KIND:
        if needle in et:
            # A commit/PR whose body reads as a decision is a decision phase.
            if kind == EpisodePhaseKind.execution and _DECISION_RE.search(text):
                return EpisodePhaseKind.decision
            return kind
    if _DECISION_RE.search(text):
        return EpisodePhaseKind.decision
    return EpisodePhaseKind.other


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
        # Tie-break by member ref for stable ordering when times collide.
        pairs.append((lk, rec, occurred))
    pairs.sort(key=lambda t: (t[2] or "~", _member_ref(t[0])))
    return [(lk, rec) for lk, rec, _o in pairs]


def compute_phases(store, ep: WorkEpisode) -> list[EpisodePhase]:
    """Pure computation of phases from active links (no persistence)."""
    pairs = _ordered_active_links(store, ep.id)
    if not pairs:
        return []

    # 1. classify each member
    classified: list[tuple[Any, Any, EpisodePhaseKind, str]] = []
    for lk, rec in pairs:
        content = getattr(rec, "content", "") or ""
        kind = _phase_kind_for(lk.external_type or "", content)
        occurred = getattr(rec, "occurred_at", "") or ""
        classified.append((lk, rec, kind, occurred))

    # 2. collapse contiguous same-kind runs into phases
    phases: list[EpisodePhase] = []
    order = 0
    i = 0
    n = len(classified)
    while i < n:
        j = i
        kind = classified[i][2]
        while j + 1 < n and classified[j + 1][2] == kind:
            # A reversal member opens a new phase even within a same-kind run,
            # so a decision pivot stays visible as two decision phases.
            nxt = classified[j + 1]
            nxt_content = getattr(nxt[1], "content", "") or ""
            if _REVERSAL_RE.search(nxt_content):
                break
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
            confidence=0.6,
            provenance={"method": "heuristic", "twin_influenced": False},
        ))
        order += 1
        i = j + 1
    return phases


def rebuild_phases(store, ep: WorkEpisode) -> list[EpisodePhase]:
    """Recompute and persist phases for one episode (idempotent by phase_key).

    Existing phases whose ``phase_key`` no longer appears are removed. Phases
    that persist keep their id so ``EpisodeEdge`` references (via ``phase_key``)
    stay valid across rebuilds.
    """
    if not hasattr(store, "list_episode_phases"):
        return []
    computed = compute_phases(store, ep)
    computed_by_id = {p.id: p for p in computed}

    existing = {p.id: p for p in store.list_episode_phases(ep.id)}
    # remove stale
    for pid in list(existing):
        if pid not in computed_by_id:
            store.delete_episode_phase(pid)
    # upsert current
    for p in computed:
        if p.id in existing:
            prior = existing[p.id]
            # keep created_at + any human/LLM provenance from prior
            p.created_at = prior.created_at or p.created_at
            if prior.provenance.get("method") == "llm":
                p.provenance = prior.provenance
                p.summary = prior.summary or p.summary
            p.updated_at = now_iso()
            store.update_episode_phase(p)
        else:
            store.insert_episode_phase(p)
    return computed


def phase_by_key(store, episode_id: str, phase_key: str) -> Optional[EpisodePhase]:
    for p in store.list_episode_phases(episode_id):
        if p.phase_key == phase_key:
            return p
    return None
