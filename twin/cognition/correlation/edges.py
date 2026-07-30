"""Causal / narrative edges over episode phases.

Heuristic proposers read the phase arc and member content to propose revisable
edges (motivated / superseded / resolved / continues / contradicts). Edges are
proposals — they never write Memory or Judgment and never alone create a
memory. Human confirm/reject is the only promotion path.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Optional

from ...clock import now_iso
from .models import (
    EpisodeEdge,
    EpisodeEdgeRelation,
    EpisodeEdgeStatus,
    EpisodeLinkStatus,
    EpisodePhase,
    EpisodePhaseKind,
    WorkEpisode,
)

# Language that signals a later decision overturning an earlier one.
_REVERSAL_RE = re.compile(
    r"\b(instead|revert|reverted|reverting|pivot|pivoted|"
    r"changed our mind|no longer|abandon|abandoned|"
    r"switch(?:ed)? to|replace(?:d)? with|supersed)\b",
    re.I,
)
_RESOLVE_RE = re.compile(
    r"\b(closes|closed|fixes|fixed|resolves|resolved|done|merged|shipped)\b",
    re.I,
)


def _edge_id(episode_id: str, relation: str, from_key: str, to_key: str) -> str:
    digest = hashlib.sha256(
        f"{episode_id}|{relation}|{from_key}|{to_key}".encode("utf-8"),
    ).hexdigest()[:20]
    return f"epedge_{digest}"


def _ref(phase: EpisodePhase) -> dict[str, str]:
    return {"kind": "phase", "id": phase.phase_key}


def _ref_key(ref: dict[str, Any]) -> str:
    return f"{ref.get('kind')}:{ref.get('id')}"


def _content_by_ref(store, ep: WorkEpisode) -> dict[str, str]:
    """Map ``external_type:external_id`` → member content for active links."""
    out: dict[str, str] = {}
    if not hasattr(store, "list_episode_links"):
        return out
    for lk in store.list_episode_links(ep.id):
        st = getattr(lk.status, "value", lk.status)
        if st != EpisodeLinkStatus.active.value:
            continue
        content = ""
        if lk.connector_record_id and hasattr(store, "get_connector_record"):
            rec = store.get_connector_record(lk.connector_record_id)
            if rec is not None:
                content = rec.content or ""
        out[f"{lk.external_type or ''}:{lk.external_id or ''}"] = content
    return out


def _phase_text(phase: EpisodePhase, content_by_ref: dict[str, str]) -> str:
    parts = [phase.summary or ""]
    for ref in phase.member_external_refs:
        c = content_by_ref.get(ref)
        if c:
            parts.append(c)
    return " ".join(p for p in parts if p)


def propose_edges(store, ep: WorkEpisode) -> list[EpisodeEdge]:
    """Pure proposer — returns edges without persisting."""
    phases = (
        store.list_episode_phases(ep.id)
        if hasattr(store, "list_episode_phases") else []
    )
    phases = sorted(phases, key=lambda p: p.order)
    if len(phases) < 2:
        return []
    content_by_ref = _content_by_ref(store, ep)

    out: list[EpisodeEdge] = []
    seen: set[str] = set()

    def _add(rel: EpisodeEdgeRelation, a: EpisodePhase, b: EpisodePhase,
             conf: float, quote: str) -> None:
        from_ref, to_ref = _ref(a), _ref(b)
        eid = _edge_id(ep.id, rel.value, _ref_key(from_ref), _ref_key(to_ref))
        if eid in seen:
            return
        seen.add(eid)
        out.append(EpisodeEdge(
            id=eid,
            episode_id=ep.id,
            vault_id=ep.vault_id,
            from_ref=from_ref,
            to_ref=to_ref,
            relation=rel,
            status=EpisodeEdgeStatus.proposed,
            confidence=conf,
            evidence_quote=quote[:280],
            provenance={"method": "heuristic", "twin_influenced": False},
        ))

    # 1. Sequential arc: each phase continues/motivates the next.
    for a, b in zip(phases, phases[1:]):
        text_b = _phase_text(b, content_by_ref)
        if a.kind in (EpisodePhaseKind.goal, EpisodePhaseKind.decision) and \
                b.kind in (EpisodePhaseKind.execution, EpisodePhaseKind.decision):
            _add(EpisodeEdgeRelation.motivated, a, b, 0.6, a.summary or "")
        else:
            _add(EpisodeEdgeRelation.continues, a, b, 0.5, a.summary or "")
        # 2. Resolution: an outcome phase resolves the originating goal/decision.
        if b.kind == EpisodePhaseKind.outcome or _RESOLVE_RE.search(text_b):
            for prior in phases:
                if prior.order < b.order and prior.kind in (
                    EpisodePhaseKind.goal, EpisodePhaseKind.decision,
                ):
                    _add(EpisodeEdgeRelation.resolved, prior, b, 0.55,
                         b.summary or "")

    # 3. Decision reversal: a later decision phase whose text overturns an
    #    earlier decision → superseded edge (the heart of "intended X → chose Y").
    decisions = [p for p in phases if p.kind == EpisodePhaseKind.decision]
    for earlier, later in zip(decisions, decisions[1:]):
        later_text = _phase_text(later, content_by_ref)
        if _REVERSAL_RE.search(later_text):
            _add(EpisodeEdgeRelation.superseded, earlier, later, 0.7,
                 later.summary or "")

    # 4. Cross-source conflict findings seed contradicts edges between the
    #    phases holding the conflicting members.
    if hasattr(store, "get_findings"):
        try:
            findings = store.get_findings(f"episode:{ep.id}", unresolved_only=True)
        except Exception:
            findings = []
        for f in findings:
            refs = (f.metadata or {}).get("member_refs") or []
            ph = [p for p in phases if any(r in p.member_external_refs for r in refs)]
            if len(ph) >= 2:
                _add(EpisodeEdgeRelation.contradicts, ph[0], ph[1], 0.5,
                     getattr(f, "reason", "") or "")

    return out


def rebuild_edges(store, ep: WorkEpisode) -> list[EpisodeEdge]:
    """Recompute and persist proposed edges (idempotent by deterministic id).

    Human decisions on edges are preserved: an edge the user confirmed or
    rejected keeps its status even if the heuristic re-proposes it. Proposed
    edges that no longer arise are removed.
    """
    if not hasattr(store, "list_episode_edges"):
        return []
    proposed = propose_edges(store, ep)
    proposed_by_id = {e.id: e for e in proposed}
    existing = {e.id: e for e in store.list_episode_edges(ep.id)}

    for eid, prior in existing.items():
        status = getattr(prior.status, "value", prior.status)
        if eid not in proposed_by_id and status == EpisodeEdgeStatus.proposed.value:
            # heuristic no longer proposes it and no human touched it → drop
            store.delete_episode_edge(eid)

    for e in proposed:
        if e.id in existing:
            prior = existing[e.id]
            status = getattr(prior.status, "value", prior.status)
            # never overwrite a human decision
            if status in (
                EpisodeEdgeStatus.confirmed.value,
                EpisodeEdgeStatus.rejected.value,
            ):
                continue
            e.created_at = prior.created_at or e.created_at
            e.updated_at = now_iso()
            store.update_episode_edge(e)
        else:
            store.insert_episode_edge(e)
    return proposed


def confirm_edge(store, edge_id: str) -> EpisodeEdge:
    edge = store.get_episode_edge(edge_id)
    if edge is None:
        raise ValueError(f"episode edge {edge_id} not found")
    edge.status = EpisodeEdgeStatus.confirmed
    edge.updated_at = now_iso()
    store.update_episode_edge(edge)
    return edge


def reject_edge(store, edge_id: str) -> EpisodeEdge:
    edge = store.get_episode_edge(edge_id)
    if edge is None:
        raise ValueError(f"episode edge {edge_id} not found")
    edge.status = EpisodeEdgeStatus.rejected
    edge.updated_at = now_iso()
    store.update_episode_edge(edge)
    return edge
