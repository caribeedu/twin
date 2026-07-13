"""Temporary permission grants — explicit, scoped, consumable atomically."""

from __future__ import annotations

from typing import Any, Optional

from .. import ids
from ..clock import now_iso
from ..memory.store.base import MemoryStore
from .models import AccessRequest, GrantStatus, PermissionGrant, ResourceClassification


def create_grant(
    store: MemoryStore,
    *,
    principal_id: str,
    persona: str,
    purpose: str,
    resource_scope: Optional[dict[str, Any]] = None,
    allowed_effects: Optional[list[str]] = None,
    ttl_seconds: int = 900,
    max_uses: int = 1,
    reason: str = "",
    granted_by: str = "user",
) -> PermissionGrant:
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    until = (now + timedelta(seconds=ttl_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
    grant = PermissionGrant(
        id=ids.new_id("grant"),
        principal_id=principal_id,
        granted_by=granted_by,
        persona=persona,
        purpose=purpose,
        resource_scope=resource_scope or {},
        allowed_effects=allowed_effects or ["read_redacted"],
        valid_from=now_iso(),
        valid_until=until,
        max_uses=max_uses,
        uses=0,
        reason=reason,
        status=GrantStatus.active,
    )
    store.insert_permission_grant(grant)
    return grant


def revoke_grant(store: MemoryStore, grant_id: str) -> PermissionGrant:
    g = store.get_permission_grant(grant_id)
    if g is None:
        raise ValueError(f"grant {grant_id} not found")
    store.update_permission_grant(
        grant_id,
        status=GrantStatus.revoked.value,
        revoked_at=now_iso(),
    )
    return store.get_permission_grant(grant_id)  # type: ignore[return-value]


def grant_covers(
    grant: PermissionGrant,
    request: AccessRequest,
    classification: ResourceClassification,
) -> bool:
    if grant.status != GrantStatus.active:
        return False
    if grant.revoked_at:
        return False
    now = now_iso()
    if grant.valid_until and grant.valid_until < now:
        return False
    if grant.max_uses is not None and grant.uses >= grant.max_uses:
        return False
    if grant.principal_id not in ("*", request.principal_id):
        return False
    if grant.persona not in ("*", request.persona):
        return False
    if grant.purpose and grant.purpose not in ("*", request.purpose):
        return False
    scope = grant.resource_scope or {}
    domains = scope.get("domains") or []
    if domains and classification.domain not in domains and "*" not in domains:
        return False
    labels = scope.get("labels") or []
    if labels and not (set(labels) & set(classification.labels)) and "*" not in labels:
        return False
    memory_ids = scope.get("memory_ids") or []
    if memory_ids and classification.resource_id not in memory_ids:
        return False
    return True


def find_applicable_grant(
    store: MemoryStore,
    request: AccessRequest,
    classification: ResourceClassification,
) -> Optional[PermissionGrant]:
    if not hasattr(store, "list_permission_grants"):
        return None
    for g in store.list_permission_grants(status=GrantStatus.active.value):
        if grant_covers(g, request, classification):
            return g
    return None


def consume_grant(
    store: MemoryStore,
    grant_id: str,
    *,
    expected_version: Optional[int] = None,
) -> PermissionGrant:
    """Atomic compare-and-set consumption of a single use."""
    if hasattr(store, "consume_permission_grant"):
        ok = store.consume_permission_grant(grant_id, expected_version=expected_version)
        if not ok:
            raise ValueError("grant_consume_conflict")
        g = store.get_permission_grant(grant_id)
        if g is None:
            raise ValueError(f"grant {grant_id} not found")
        return g

    # Fallback non-CAS path (still transactional if caller wraps)
    g = store.get_permission_grant(grant_id)
    if g is None:
        raise ValueError(f"grant {grant_id} not found")
    if expected_version is not None and g.version != expected_version:
        raise ValueError("grant_consume_conflict")
    if g.status != GrantStatus.active:
        raise ValueError(f"grant is {g.status.value}")
    if g.max_uses is not None and g.uses >= g.max_uses:
        raise ValueError("grant exhausted")
    now = now_iso()
    if g.valid_until and g.valid_until < now:
        store.update_permission_grant(grant_id, status=GrantStatus.expired.value)
        raise ValueError("grant expired")
    new_uses = g.uses + 1
    status = GrantStatus.exhausted.value if (
        g.max_uses is not None and new_uses >= g.max_uses
    ) else GrantStatus.active.value
    store.update_permission_grant(
        grant_id, uses=new_uses, version=g.version + 1, status=status,
    )
    return store.get_permission_grant(grant_id)  # type: ignore[return-value]
