"""Stream membership vs global deletion for mail connectors.

Leaving one allowlisted label/folder is not the same as leaving the connector
scope. Tombstones must also resolve the persisted ``external_type`` so
``thread_message`` lineage is found (same class of bug Slack already fixed).
"""

from __future__ import annotations

from typing import Any, Optional

MAIL_EXTERNAL_TYPES = ("thread_message", "message")


def configured_memberships(
    *, provider: str, configured_ids: list[str], kind: str,
) -> list[str]:
    """kind is ``label`` or ``folder``."""
    return [f"{kind}:{cid}" for cid in configured_ids]


def active_memberships(
    *, kind: str, configured_ids: list[str], current_ids: list[str],
) -> list[str]:
    configured = set(configured_ids)
    return [f"{kind}:{cid}" for cid in current_ids if cid in configured]


def still_in_scope(
    *, configured_ids: list[str], current_ids: list[str],
) -> bool:
    return bool(set(configured_ids) & set(current_ids))


def resolve_mail_tombstone_type(
    store, connector_id: str, external_id: str,
) -> str:
    """Prefer the type that already has live evidence."""
    if store is None:
        return "message"
    for ext_type in MAIL_EXTERNAL_TYPES:
        prior = store.list_connector_records_for_object(
            connector_id, ext_type, external_id,
        )
        if any(not p.deleted for p in prior):
            return ext_type
    for ext_type in MAIL_EXTERNAL_TYPES:
        if store.list_connector_records_for_object(
            connector_id, ext_type, external_id,
        ):
            return ext_type
    return "message"


def merge_membership_metadata(
    message: dict[str, Any], memberships: list[str],
) -> dict[str, Any]:
    out = dict(message)
    out["source_memberships"] = list(memberships)
    return out
