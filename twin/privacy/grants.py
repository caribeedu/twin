"""Temporary permission grants — explicit, scoped, consumable atomically."""

from __future__ import annotations

from typing import Any, Optional

from .. import ids
from ..clock import now_iso
from twin.store.store.base import TwinStore
from .identity import purpose_allowed
from .models import AccessRequest, GrantStatus, PermissionGrant, PolicyEffect, ResourceClassification

# Grant allowed_effects → maximum PolicyEffect they authorize
_EFFECT_FROM_GRANT = {
    "read": PolicyEffect.allow,
    "read_redacted": PolicyEffect.redact,
    "read_generalized": PolicyEffect.generalize,
    "read_aggregated": PolicyEffect.aggregate,
    "read_pseudonymized": PolicyEffect.pseudonymize,
}

_EFFECT_STRENGTH = {
    PolicyEffect.allow: 0,
    PolicyEffect.pseudonymize: 1,
    PolicyEffect.generalize: 2,
    PolicyEffect.aggregate: 3,
    PolicyEffect.redact: 4,
    PolicyEffect.require_grant: 5,
    PolicyEffect.require_confirmation: 6,
    PolicyEffect.quarantine: 7,
    PolicyEffect.deny: 8,
}


def grant_max_effect(grant: PermissionGrant) -> PolicyEffect:
    best = PolicyEffect.deny
    best_s = 99
    for name in grant.allowed_effects or []:
        eff = _EFFECT_FROM_GRANT.get(name)
        if eff is None:
            continue
        s = _EFFECT_STRENGTH.get(eff, 99)
        if s < best_s:
            best_s = s
            best = eff
    return best


def most_restrictive(a: PolicyEffect, b: PolicyEffect) -> PolicyEffect:
    if _EFFECT_STRENGTH.get(a, 0) >= _EFFECT_STRENGTH.get(b, 0):
        return a
    return b


def create_grant(
    store: TwinStore,
    *,
    principal_id: str,
    persona: str,
    purpose: str,
    resource_scope: Optional[dict[str, Any]] = None,
    allowed_effects: Optional[list[str]] = None,
    tool_ids: Optional[list[str]] = None,
    audiences: Optional[list[str]] = None,
    execution_locations: Optional[list[str]] = None,
    requested_actions: Optional[list[str]] = None,
    session_id: Optional[str] = None,
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
        tool_ids=list(tool_ids or []),
        audiences=list(audiences or ["self"]),
        execution_locations=list(execution_locations or []),
        requested_actions=list(requested_actions or ["read"]),
        session_id=session_id,
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


def revoke_grant(store: TwinStore, grant_id: str) -> PermissionGrant:
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
    *,
    execution_location: str,
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
    if grant.purpose and grant.purpose != "*" and not purpose_allowed(
        request.purpose, [grant.purpose]
    ):
        return False
    if grant.tool_ids and request.tool_id not in grant.tool_ids and "*" not in grant.tool_ids:
        return False
    if grant.audiences and request.audience not in grant.audiences and "*" not in grant.audiences:
        return False
    if (
        grant.execution_locations
        and execution_location not in grant.execution_locations
        and "*" not in grant.execution_locations
    ):
        return False
    if grant.session_id and grant.session_id != request.session_id:
        return False
    actions = set(request.requested_actions or ["read"])
    allowed_actions = set(grant.requested_actions or ["read"])
    if allowed_actions and not (actions & allowed_actions) and "*" not in allowed_actions:
        return False
    scope = grant.resource_scope or {}
    domains = scope.get("domains") or []
    if domains and classification.domain not in domains and "*" not in domains:
        return False
    labels = scope.get("labels") or []
    if labels and not (set(labels) & set(classification.labels)) and "*" not in labels:
        return False
    claim_ids = scope.get("claim_ids") or []
    if claim_ids and classification.resource_id not in claim_ids:
        return False
    return True


def find_applicable_grant(
    store: TwinStore,
    request: AccessRequest,
    classification: ResourceClassification,
    *,
    execution_location: str,
) -> Optional[PermissionGrant]:
    if not hasattr(store, "list_permission_grants"):
        return None
    for g in store.list_permission_grants(status=GrantStatus.active.value):
        if grant_covers(g, request, classification, execution_location=execution_location):
            return g
    return None


def consume_grant(
    store: TwinStore,
    grant_id: str,
    *,
    expected_version: Optional[int] = None,
) -> PermissionGrant:
    """Atomic compare-and-set consumption. Success only if THIS call won the update."""
    if not hasattr(store, "consume_permission_grant"):
        raise ValueError("store does not support atomic grant consume")
    ok = store.consume_permission_grant(grant_id, expected_version=expected_version)
    if not ok:
        raise ValueError("grant_consume_conflict")
    g = store.get_permission_grant(grant_id)
    if g is None:
        raise ValueError(f"grant {grant_id} not found")
    return g
