"""Policy evaluation engine — contextual access decisions before any LLM."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from .. import ids
from ..clock import now_iso
from ..judgment.firewall import Firewall
from ..memory.models import MemoryItem
from ..memory.store.base import MemoryStore
from .classify import classify_memory
from .grants import consume_grant, find_applicable_grant
from .models import (
    AccessRequest,
    PolicyEffect,
    PrivacyDecision,
    PrivacyPolicy,
    ResourceClassification,
    ResourceDecision,
)
from .redact import apply_redaction_plan, plan_redaction
from .yaml_io import load_governance_policies, resolve_tool


_EFFECT_RANK = {
    PolicyEffect.deny: 100,
    PolicyEffect.quarantine: 95,
    PolicyEffect.require_confirmation: 80,
    PolicyEffect.require_grant: 70,
    PolicyEffect.redact: 60,
    PolicyEffect.aggregate: 55,
    PolicyEffect.generalize: 50,
    PolicyEffect.pseudonymize: 45,
    PolicyEffect.allow: 10,
}


def _wildcard_match(patterns: list[str], value: str) -> bool:
    if not patterns or "*" in patterns:
        return True
    for p in patterns:
        if p == value:
            return True
        if p.endswith(":*") and value.startswith(p[:-1]):
            return True
        if p.endswith("*") and value.startswith(p[:-1]):
            return True
    return False


def policy_matches(
    policy: PrivacyPolicy,
    request: AccessRequest,
    classification: ResourceClassification,
    *,
    execution_location: str,
) -> bool:
    if not policy.enabled:
        return False
    sub = policy.subjects
    if not _wildcard_match(sub.personas, request.persona):
        return False
    if not _wildcard_match(sub.principals, request.principal_id):
        return False
    res = policy.resources
    if res.domains and classification.domain not in res.domains and "*" not in res.domains:
        return False
    if res.sensitivity and classification.sensitivity not in res.sensitivity:
        # also match if field-level exceeds
        field_sens = {f.sensitivity.value for f in classification.fields.values()}
        if not (field_sens & set(res.sensitivity)):
            return False
    if res.labels and not (set(res.labels) & set(classification.labels)):
        return False
    if res.source_owners and classification.source_owner not in res.source_owners:
        return False
    if res.vaults and classification.vault_id not in res.vaults:
        return False
    if res.third_party is True and not classification.third_party:
        return False
    if res.third_party is False and classification.third_party:
        return False
    ctx = policy.context
    if not _wildcard_match(ctx.purposes, request.purpose):
        return False
    if not _wildcard_match(ctx.audiences, request.audience):
        return False
    if not _wildcard_match(ctx.tools, request.tool_id):
        return False
    if ctx.execution_locations and execution_location not in ctx.execution_locations:
        return False
    return True


def _fingerprint(request: AccessRequest, resource_ids: list[str]) -> str:
    raw = json.dumps({
        "req": request.model_dump(),
        "resources": sorted(resource_ids),
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def evaluate_resource(
    policies: list[PrivacyPolicy],
    request: AccessRequest,
    classification: ResourceClassification,
    *,
    execution_location: str,
    store: Optional[MemoryStore] = None,
    consume_grants: bool = False,
    legacy_firewall: Optional[Firewall] = None,
    memory: Optional[MemoryItem] = None,
    target_domain: Optional[str] = None,
) -> ResourceDecision:
    matched: list[PrivacyPolicy] = []
    for p in sorted(policies, key=lambda x: (-x.priority, x.id)):
        if policy_matches(p, request, classification, execution_location=execution_location):
            matched.append(p)

    # Restricted mode: unknown purpose/audience/tool → default deny unless public
    if request.is_restricted_mode and classification.sensitivity not in ("public",):
        if not any(p.effect == PolicyEffect.allow and p.constitutional for p in matched):
            return ResourceDecision(
                resource_id=classification.resource_id,
                effect=PolicyEffect.deny,
                matched_policy_ids=["restricted_mode_default_deny"],
                reason="unknown purpose/audience/tool — restricted mode",
                sensitivity=classification.sensitivity,
                labels=classification.labels,
            )

    # Legacy domain firewall as additional deny signal
    if legacy_firewall is not None and memory is not None:
        domain = target_domain or (request.requested_domains[0] if request.requested_domains else memory.domain)
        verdict = legacy_firewall.evaluate(memory, domain)
        if not verdict.allowed and not verdict.requires_permission:
            return ResourceDecision(
                resource_id=classification.resource_id,
                effect=PolicyEffect.deny,
                matched_policy_ids=[verdict.rule],
                reason=verdict.reason,
                sensitivity=classification.sensitivity,
                labels=classification.labels,
            )
        if verdict.requires_permission:
            matched.append(PrivacyPolicy(
                id=verdict.rule,
                name=verdict.rule,
                effect=PolicyEffect.require_grant,
                priority=500,
                reason=verdict.reason,
            ))

    if not matched:
        # default deny for cloud / cross-sensitive
        if execution_location == "cloud" and classification.sensitivity in (
            "restricted", "highly_restricted", "confidential",
        ):
            return ResourceDecision(
                resource_id=classification.resource_id,
                effect=PolicyEffect.require_grant,
                matched_policy_ids=["cloud_sensitive_default"],
                reason="sensitive data to cloud requires grant or redaction policy",
                sensitivity=classification.sensitivity,
                labels=classification.labels,
            )
        return ResourceDecision(
            resource_id=classification.resource_id,
            effect=PolicyEffect.allow,
            matched_policy_ids=["default_allow"],
            reason="no matching restrictive policy",
            sensitivity=classification.sensitivity,
            labels=classification.labels,
        )

    # Precedence among matched: constitutional deny > deny > require_* > redact > allow
    best = matched[0]
    for p in matched[1:]:
        if p.constitutional and p.effect == PolicyEffect.deny:
            best = p
            break
        if _EFFECT_RANK.get(p.effect, 0) > _EFFECT_RANK.get(best.effect, 0):
            best = p
        elif _EFFECT_RANK.get(p.effect, 0) == _EFFECT_RANK.get(best.effect, 0) and p.priority > best.priority:
            best = p

    decision = ResourceDecision(
        resource_id=classification.resource_id,
        effect=best.effect,
        matched_policy_ids=[p.id for p in matched],
        reason=best.reason or best.name,
        sensitivity=classification.sensitivity,
        labels=classification.labels,
    )

    if best.effect in (PolicyEffect.require_grant, PolicyEffect.redact, PolicyEffect.generalize):
        grant = find_applicable_grant(store, request, classification) if store else None
        if grant is not None:
            if consume_grants:
                consume_grant(store, grant.id, expected_version=grant.version)  # type: ignore[arg-type]
            decision.grant_id = grant.id
            # Grant may authorize redacted read
            if "read" in grant.allowed_effects:
                decision.effect = PolicyEffect.allow
                decision.reason = f"authorized by grant {grant.id}"
            else:
                decision.effect = PolicyEffect.redact
                decision.reason = f"grant {grant.id} allows redacted read"
        elif best.effect == PolicyEffect.require_grant:
            decision.effect = PolicyEffect.require_grant

    return decision


def evaluate_access(
    store: MemoryStore,
    request: AccessRequest,
    memories: list[MemoryItem],
    *,
    policies_path: Optional[Path | str] = None,
    policies: Optional[list[PrivacyPolicy]] = None,
    consume_grants: bool = False,
    persist: bool = True,
    legacy_firewall: Optional[Firewall] = None,
    target_domain: Optional[str] = None,
) -> dict[str, Any]:
    """Evaluate each memory; return decision + ephemeral allowed/redacted views."""
    policies = policies or load_governance_policies(policies_path, store=store)
    tool = resolve_tool(request.tool_id, store=store)
    execution_location = (
        request.execution_location
        or (tool.execution_location if tool else "local")
    )

    resource_decisions: list[ResourceDecision] = []
    allowed_views: list[dict[str, Any]] = []
    denied: list[dict[str, Any]] = []
    redacted: list[dict[str, Any]] = []
    needs_grant: list[dict[str, Any]] = []
    needs_confirm: list[dict[str, Any]] = []
    all_policy_ids: list[str] = []
    grant_ids: list[str] = []
    obligations: list[str] = ["log_decision"]

    for mem in memories:
        classification = classify_memory(mem)
        rd = evaluate_resource(
            policies, request, classification,
            execution_location=execution_location,
            store=store,
            consume_grants=consume_grants,
            legacy_firewall=legacy_firewall,
            memory=mem,
            target_domain=target_domain,
        )
        resource_decisions.append(rd)
        all_policy_ids.extend(rd.matched_policy_ids)
        if rd.grant_id:
            grant_ids.append(rd.grant_id)

        if rd.effect == PolicyEffect.deny:
            denied.append({"memory_id": mem.id, "reason": rd.reason, "rule": rd.matched_policy_ids[0] if rd.matched_policy_ids else ""})
        elif rd.effect == PolicyEffect.require_grant:
            needs_grant.append({"memory_id": mem.id, "reason": rd.reason})
            denied.append({"memory_id": mem.id, "reason": rd.reason, "rule": "require_grant"})
        elif rd.effect == PolicyEffect.require_confirmation:
            needs_confirm.append({"memory_id": mem.id, "reason": rd.reason})
            denied.append({"memory_id": mem.id, "reason": rd.reason, "rule": "require_confirmation"})
        elif rd.effect in (PolicyEffect.redact, PolicyEffect.generalize, PolicyEffect.aggregate, PolicyEffect.pseudonymize):
            plan = plan_redaction(classification, rd, effect=rd.effect)
            view = apply_redaction_plan(classification, plan)
            view["effect"] = rd.effect.value
            redacted.append(view)
            allowed_views.append(view)
        else:
            allowed_views.append({
                "id": mem.id,
                "title": mem.title,
                "summary": mem.summary,
                "domain": mem.domain,
                "sensitivity": classification.sensitivity,
                "payload": dict(mem.payload or {}),
                "redacted": False,
                "effect": "allow",
            })

    # Overall effect
    overall = PolicyEffect.allow
    for rd in resource_decisions:
        if _EFFECT_RANK.get(rd.effect, 0) > _EFFECT_RANK.get(overall, 0):
            overall = rd.effect

    version = store.get_active_policy_set_version() if hasattr(store, "get_active_policy_set_version") else None
    decision = PrivacyDecision(
        id=ids.new_id("pdec"),
        request_fingerprint=_fingerprint(request, [m.id for m in memories]),
        effect=overall,
        matched_policy_ids=sorted(set(all_policy_ids)),
        resource_decisions=resource_decisions,
        obligations=obligations,
        policy_set_version_id=version.id if version else None,
        grant_ids=sorted(set(grant_ids)),
        access_request=request.model_dump(),
        created_at=now_iso(),
        metadata={
            "execution_location": execution_location,
            "resources_considered": len(memories),
            "resources_allowed": len(allowed_views),
            "resources_redacted": len(redacted),
            "resources_denied": len(denied),
        },
    )
    if persist and hasattr(store, "insert_privacy_decision"):
        store.insert_privacy_decision(decision)

    return {
        "decision": decision,
        "decision_id": decision.id,
        "allowed": allowed_views,
        "redacted": redacted,
        "denied": denied,
        "needs_grant": needs_grant,
        "needs_confirmation": needs_confirm,
        "policy_set_version_id": decision.policy_set_version_id,
        "execution_location": execution_location,
    }


def explain_decision(store: MemoryStore, decision_id: str) -> dict[str, Any]:
    d = store.get_privacy_decision(decision_id)
    if d is None:
        raise ValueError(f"decision {decision_id} not found")
    lines = []
    for rd in d.resource_decisions:
        lines.append({
            "resource_id": rd.resource_id,
            "effect": rd.effect.value,
            "reason": rd.reason,
            "matched_policies": rd.matched_policy_ids,
            "redacted_fields": rd.redacted_fields,
            # never include content
        })
    return {
        "decision_id": d.id,
        "effect": d.effect.value,
        "policy_set_version_id": d.policy_set_version_id,
        "grant_ids": d.grant_ids,
        "access_request": {
            k: d.access_request.get(k)
            for k in ("persona", "purpose", "audience", "tool_id", "principal_id")
        },
        "resources": lines,
        "created_at": d.created_at,
    }
