"""Causal / narrative edges over episode phases.

Edges (motivated / superseded / resolved / continues / contradicts) are
proposed by the **cortex** cognition stage — an LLM that reads the phase arc
and member quotes. This module holds the data plumbing: build ``EpisodeEdge``
objects from model output and persist them idempotently while preserving human
confirm / reject decisions. There is no lexical rule here; without a model no
edges are proposed.
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from twin.clock import now_iso
from .models import (
    EpisodeEdge,
    EpisodeEdgeRelation,
    EpisodeEdgeStatus,
    EpisodePhase,
    WorkEpisode,
)


def edge_id(episode_id: str, relation: str, from_key: str, to_key: str) -> str:
    digest = hashlib.sha256(
        f"{episode_id}|{relation}|{from_key}|{to_key}".encode("utf-8"),
    ).hexdigest()[:20]
    return f"epedge_{digest}"


def _coerce_relation(value: Any) -> Optional[EpisodeEdgeRelation]:
    try:
        return EpisodeEdgeRelation(str(value))
    except (ValueError, TypeError):
        return None


def build_edges_from_llm(
    ep: WorkEpisode,
    phases: list[EpisodePhase],
    proposals: list[dict[str, Any]],
    *,
    brain_stage: str = "cortex",
) -> list[EpisodeEdge]:
    """Turn model edge proposals into ``EpisodeEdge`` objects.

    Each proposal is ``{"from_key", "to_key", "relation", "confidence",
    "evidence_quote"}``. Keys must reference existing ``phase_key``s and the
    relation must be known; anything else is dropped (the model never widens
    the schema).
    """
    valid_keys = {p.phase_key for p in phases}
    out: list[EpisodeEdge] = []
    seen: set[str] = set()
    for pr in proposals:
        if not isinstance(pr, dict):
            continue
        from_key = pr.get("from_key")
        to_key = pr.get("to_key")
        if from_key not in valid_keys or to_key not in valid_keys:
            continue
        if from_key == to_key:
            continue
        relation = _coerce_relation(pr.get("relation"))
        if relation is None:
            continue
        eid = edge_id(ep.id, relation.value, str(from_key), str(to_key))
        if eid in seen:
            continue
        seen.add(eid)
        try:
            conf = float(pr.get("confidence"))
        except (TypeError, ValueError):
            conf = 0.6
        out.append(EpisodeEdge(
            id=eid,
            episode_id=ep.id,
            vault_id=ep.vault_id,
            from_ref={"kind": "phase", "id": from_key},
            to_ref={"kind": "phase", "id": to_key},
            relation=relation,
            status=EpisodeEdgeStatus.proposed,
            confidence=round(min(1.0, max(0.1, conf)), 2),
            evidence_quote=(str(pr.get("evidence_quote") or "")[:280]),
            provenance={
                "method": "llm",
                "twin_influenced": True,
                "brain_stage": brain_stage,
            },
        ))
    return out


def persist_edges(
    store, ep: WorkEpisode, edges: list[EpisodeEdge],
) -> list[EpisodeEdge]:
    """Idempotently persist proposed edges, preserving human decisions.

    An edge the user confirmed or rejected keeps its status even if the model
    re-proposes (or stops proposing) it. Untouched ``proposed`` edges that are
    no longer proposed are removed.
    """
    if not hasattr(store, "list_episode_edges"):
        return edges
    proposed_by_id = {e.id: e for e in edges}
    existing = {e.id: e for e in store.list_episode_edges(ep.id)}

    for eid, prior in existing.items():
        status = getattr(prior.status, "value", prior.status)
        if eid not in proposed_by_id and status == EpisodeEdgeStatus.proposed.value:
            store.delete_episode_edge(eid)

    for e in edges:
        if e.id in existing:
            prior = existing[e.id]
            status = getattr(prior.status, "value", prior.status)
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
    return edges


def clear_proposed_edges(store, ep: WorkEpisode) -> None:
    """Drop model-proposed edges (keep human-confirmed/rejected ones)."""
    if not hasattr(store, "list_episode_edges"):
        return
    for e in store.list_episode_edges(ep.id):
        status = getattr(e.status, "value", e.status)
        if status == EpisodeEdgeStatus.proposed.value:
            store.delete_episode_edge(e.id)


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
