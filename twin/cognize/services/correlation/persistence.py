"""Row codecs for correlation tables."""

from __future__ import annotations

import json
from typing import Any

from .models import (
    EpisodeEdge,
    EpisodeEdgeRelation,
    EpisodeEdgeStatus,
    EpisodeLink,
    EpisodeLinkKind,
    EpisodeLinkStatus,
    EpisodePhase,
    EpisodePhaseKind,
    EpisodePhaseStatus,
    EpisodeStatus,
    ExternalIdentity,
    IdentityLink,
    IdentityStatus,
    ProjectLink,
    WorkEpisode,
)


def _dump(model: Any) -> str:
    return json.dumps(model.model_dump(mode="json"), default=str)


def _load(cls, payload: str | bytes | dict):
    if isinstance(payload, dict):
        return cls.model_validate(payload)
    return cls.model_validate_json(payload)


def identity_to_row(ident: ExternalIdentity) -> dict[str, Any]:
    return {
        "id": ident.id,
        "provider": ident.provider,
        "external_id": ident.external_id,
        "source_account_id": ident.source_account_id or "",
        "vault_id": ident.vault_id or "",
        "actor_id": ident.actor_id or "",
        "payload": _dump(ident),
    }


def row_to_identity(row: Any, decrypt=None) -> ExternalIdentity:
    payload = row["payload"]
    if decrypt:
        payload = decrypt(payload)
    return _load(ExternalIdentity, payload)


def identity_link_to_row(link: IdentityLink) -> dict[str, Any]:
    return {
        "id": link.id,
        "left_identity_id": link.left_identity_id,
        "right_identity_id": link.right_identity_id or "",
        "vault_id": link.vault_id or "",
        "status": link.status.value if isinstance(link.status, IdentityStatus) else link.status,
        "payload": _dump(link),
    }


def row_to_identity_link(row: Any, decrypt=None) -> IdentityLink:
    payload = row["payload"]
    if decrypt:
        payload = decrypt(payload)
    return _load(IdentityLink, payload)


def project_link_to_row(link: ProjectLink) -> dict[str, Any]:
    return {
        "id": link.id,
        "project_id": link.project_id,
        "external_type": link.external_type,
        "external_id": link.external_id,
        "source_account_id": link.source_account_id or "",
        "vault_id": link.vault_id or "",
        "payload": _dump(link),
    }


def row_to_project_link(row: Any, decrypt=None) -> ProjectLink:
    payload = row["payload"]
    if decrypt:
        payload = decrypt(payload)
    return _load(ProjectLink, payload)


def episode_to_row(ep: WorkEpisode) -> dict[str, Any]:
    return {
        "id": ep.id,
        "vault_id": ep.vault_id or "",
        "correlation_key": ep.correlation_key or "",
        "project_id": ep.project_id or "",
        "status": ep.status.value if isinstance(ep.status, EpisodeStatus) else ep.status,
        "independence_group": ep.independence_group or "",
        "payload": _dump(ep),
    }


def row_to_episode(row: Any, decrypt=None) -> WorkEpisode:
    payload = row["payload"]
    if decrypt:
        payload = decrypt(payload)
    return _load(WorkEpisode, payload)


def episode_link_to_row(link: EpisodeLink) -> dict[str, Any]:
    return {
        "id": link.id,
        "episode_id": link.episode_id,
        "vault_id": link.vault_id or "",
        "external_type": link.external_type or "",
        "external_id": link.external_id or "",
        "kind": link.kind.value if isinstance(link.kind, EpisodeLinkKind) else link.kind,
        "status": (
            link.status.value if isinstance(link.status, EpisodeLinkStatus)
            else link.status
        ),
        "payload": _dump(link),
    }


def row_to_episode_link(row: Any, decrypt=None) -> EpisodeLink:
    payload = row["payload"]
    if decrypt:
        payload = decrypt(payload)
    return _load(EpisodeLink, payload)


def episode_phase_to_row(phase: EpisodePhase) -> dict[str, Any]:
    return {
        "id": phase.id,
        "episode_id": phase.episode_id,
        "vault_id": phase.vault_id or "",
        "phase_key": phase.phase_key or "",
        "kind": (
            phase.kind.value if isinstance(phase.kind, EpisodePhaseKind)
            else phase.kind
        ),
        "status": (
            phase.status.value if isinstance(phase.status, EpisodePhaseStatus)
            else phase.status
        ),
        "ordinal": phase.order,
        "payload": _dump(phase),
    }


def row_to_episode_phase(row: Any, decrypt=None) -> EpisodePhase:
    payload = row["payload"]
    if decrypt:
        payload = decrypt(payload)
    return _load(EpisodePhase, payload)


def episode_edge_to_row(edge: EpisodeEdge) -> dict[str, Any]:
    return {
        "id": edge.id,
        "episode_id": edge.episode_id,
        "vault_id": edge.vault_id or "",
        "relation": (
            edge.relation.value if isinstance(edge.relation, EpisodeEdgeRelation)
            else edge.relation
        ),
        "status": (
            edge.status.value if isinstance(edge.status, EpisodeEdgeStatus)
            else edge.status
        ),
        "payload": _dump(edge),
    }


def row_to_episode_edge(row: Any, decrypt=None) -> EpisodeEdge:
    payload = row["payload"]
    if decrypt:
        payload = decrypt(payload)
    return _load(EpisodeEdge, payload)
