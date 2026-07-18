"""Row codecs for correlation tables."""

from __future__ import annotations

import json
from typing import Any

from .models import (
    EpisodeLink,
    EpisodeLinkKind,
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
        "external_type": link.external_type or "",
        "external_id": link.external_id or "",
        "kind": link.kind.value if isinstance(link.kind, EpisodeLinkKind) else link.kind,
        "payload": _dump(link),
    }


def row_to_episode_link(row: Any, decrypt=None) -> EpisodeLink:
    payload = row["payload"]
    if decrypt:
        payload = decrypt(payload)
    return _load(EpisodeLink, payload)
