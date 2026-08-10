"""Policy evaluation engine — contextual access decisions before any LLM."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from .. import ids
from ..clock import now_iso
from twin.privacy.firewall import Firewall
from twin.store.models import MemoryItem
from twin.store.store.base import MemoryStore
from .classify import classify_memory
from .grants import (
    consume_grant,
    find_applicable_grant,
    grant_max_effect,
    most_restrictive,
)
from .identity import (
    active_consent_covers,
    principal_can_read,
    resolve_execution_location,
    restricted_access,
    validate_vault_access,
)
from .models import (
    AccessRequest,
    PolicyEffect,
    PrivacyDecision,
    PrivacyPolicy,
    Principal,
    ResourceClassification,
    ResourceDecision,
)
from .redact import apply_redaction_plan, leakage_scan, plan_redaction
from .yaml_io import load_active_policy_revisions, load_governance_policies, resolve_tool


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

ENGINE_VERSION = "privacy-engine-v1"


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
    if res.sensitivity and classification.sensitivity not in res.sensitivity and "*" not in res.sensitivity:
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


def _pick_best(matched: list[PrivacyPolicy]) -> PrivacyPolicy:
    """Precedence: constitutional non-overrideable deny > non-overrideable deny > rank > priority."""
    def sort_key(p: PrivacyPolicy) -> tuple:
        const_deny = 1 if (p.constitutional and p.effect == PolicyEffect.deny) else 0
        non_ov_deny = 1 if (not p.overrideable and p.effect == PolicyEffect.deny) else 0
        return (const_deny, non_ov_deny, _EFFECT_RANK.get(p.effect, 0), p.priority)

    return max(matched, key=sort_key)


def _fingerprint(request: AccessRequest, resource_ids: list[str], policy_ids: list[str]) -> str:
    raw = json.dumps({
        "req": request.model_dump(),
        "resources": sorted(resource_ids),
        "policies": sorted(policy_ids),
        "engine": ENGINE_VERSION,
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
    principal: Optional[Principal] = None,
) -> ResourceDecision:
    matched: list[PrivacyPolicy] = []
    for p in policies:
        if policy_matches(p, request, classification, execution_location=execution_location):
            matched.append(p)

    # Fail closed: filled AccessRequest ≠ authenticated AccessRequest
    if classification.sensitivity not in ("public",) and principal is None:
        return ResourceDecision(
            resource_id=classification.resource_id,
            effect=PolicyEffect.deny,
            matched_policy_ids=["unregistered_principal_default_deny"],
            reason="principal is not registered",
            sensitivity=classification.sensitivity,
            labels=classification.labels,
        )

    # Vault persona gate
    allowed_vaults = list((request.metadata or {}).get("allowed_vaults") or [])
    if not validate_vault_access(
        store,  # type: ignore[arg-type]
        vault_id=classification.vault_id,
        persona=request.persona,
        principal=principal,
        allowed_vaults_extra=allowed_vaults,
    ):
        return ResourceDecision(
            resource_id=classification.resource_id,
            effect=PolicyEffect.deny,
            matched_policy_ids=["vault_persona_denied"],
            reason=f"persona {request.persona} cannot access {classification.vault_id}",
            sensitivity=classification.sensitivity,
            labels=classification.labels,
        )

    # Capability gate for non-public: base action AND scopes
    if classification.sensitivity not in ("public",):
        effective_caps = (request.metadata or {}).get("resolved_capabilities")
        if not principal_can_read(
            principal,
            domain=classification.domain,
            vault_id=classification.vault_id,
            project_id=request.project_id,
            effective_capabilities=effective_caps,
        ):
            return ResourceDecision(
                resource_id=classification.resource_id,
                effect=PolicyEffect.deny,
                matched_policy_ids=["capability_denied"],
                reason="principal lacks scoped read capability",
                sensitivity=classification.sensitivity,
                labels=classification.labels,
            )

    # Third-party consent — full category coverage + tool/location semantics
    if classification.third_party or "third_party" in classification.labels:
        subjects = classification.subjects or ["unknown_third_party"]
        if not active_consent_covers(
            store,  # type: ignore[arg-type]
            subject_ids=subjects,
            purpose=request.purpose,
            tool_id=request.tool_id,
            categories=classification.labels,
            execution_location=execution_location,
        ):
            if request.audience in ("public", "client", "unknown") or execution_location == "cloud":
                return ResourceDecision(
                    resource_id=classification.resource_id,
                    effect=PolicyEffect.deny,
                    matched_policy_ids=["third_party_consent_required"],
                    reason="third-party data requires active consent covering all categories",
                    sensitivity=classification.sensitivity,
                    labels=classification.labels,
                )

    # Restricted mode
    if request.is_restricted_mode and classification.sensitivity not in ("public",):
        return ResourceDecision(
            resource_id=classification.resource_id,
            effect=PolicyEffect.deny,
            matched_policy_ids=["restricted_mode_default_deny"],
            reason="unknown purpose/audience/tool/persona — restricted mode",
            sensitivity=classification.sensitivity,
            labels=classification.labels,
        )

    if execution_location == "unknown" and classification.sensitivity not in ("public",):
        return ResourceDecision(
            resource_id=classification.resource_id,
            effect=PolicyEffect.deny,
            matched_policy_ids=["unknown_tool_default_deny"],
            reason="unregistered tool — default deny for non-public data",
            sensitivity=classification.sensitivity,
            labels=classification.labels,
        )

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
                id=verdict.rule, name=verdict.rule,
                effect=PolicyEffect.require_grant, priority=500,
                reason=verdict.reason, overrideable=True,
            ))

    if not matched:
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

    best = _pick_best(matched)
    obligations = sorted({o for p in matched for o in (p.obligations or [])})
    decision = ResourceDecision(
        resource_id=classification.resource_id,
        effect=best.effect,
        matched_policy_ids=[p.id for p in matched],
        reason=best.reason or best.name,
        sensitivity=classification.sensitivity,
        labels=classification.labels,
        obligations=obligations,
    )

    # Grants may only soften overrideable effects, never constitutional deny
    if best.effect != PolicyEffect.deny or best.overrideable:
        if best.effect in (
            PolicyEffect.require_grant, PolicyEffect.redact, PolicyEffect.generalize,
            PolicyEffect.aggregate, PolicyEffect.pseudonymize, PolicyEffect.deny,
        ) and best.overrideable:
            grant = find_applicable_grant(
                store, request, classification,  # type: ignore[arg-type]
                execution_location=execution_location,
            ) if store else None
            if grant is not None:
                if consume_grants:
                    consume_grant(store, grant.id, expected_version=grant.version)  # type: ignore[arg-type]
                decision.grant_id = grant.id
                decision.effect = most_restrictive(best.effect, grant_max_effect(grant))
                if decision.effect == PolicyEffect.require_grant:
                    decision.effect = grant_max_effect(grant)
                decision.reason = f"authorized by grant {grant.id} → {decision.effect.value}"

    if best.effect == PolicyEffect.deny and not best.overrideable:
        decision.effect = PolicyEffect.deny
        decision.grant_id = None

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
    """Evaluate each memory; return decision + ephemeral authorized views."""
    # Never trust client-claimed execution_location
    execution_location = resolve_execution_location(
        request.tool_id, store=store, claimed=request.execution_location,
    )
    request = request.model_copy(update={"execution_location": None})
    request.metadata = {
        **(request.metadata or {}),
        "resolved_execution_location": execution_location,
    }

    policies = policies or (
        load_active_policy_revisions(store)
        if hasattr(store, "get_active_policy_set_version")
        else load_governance_policies(policies_path, store=store)
    )
    # Snapshot of policies actually evaluated (immutable revision payloads)
    policy_snapshot = [p.model_dump(mode="json") for p in policies]
    active = store.get_active_policy_set_version() if hasattr(store, "get_active_policy_set_version") else None
    policy_revision_ids = list((active.revision_ids if active else None) or [
        f"{p.id}@v{p.version}" for p in policies
    ])

    principal = None
    if hasattr(store, "get_principal"):
        principal = store.get_principal(request.principal_id)
    if principal is None:
        # Filled AccessRequest ≠ authenticated AccessRequest
        request = restricted_access(
            project_id=request.project_id,
            session_id=request.session_id,
            requested_domains=request.requested_domains,
            claims={
                "principal_id": request.principal_id,
                "tool_id": request.tool_id,
                "reason": "unregistered_principal",
            },
        )

    resource_decisions: list[ResourceDecision] = []
    allowed_views: list[dict[str, Any]] = []
    denied: list[dict[str, Any]] = []
    redacted: list[dict[str, Any]] = []
    needs_grant: list[dict[str, Any]] = []
    needs_confirm: list[dict[str, Any]] = []
    all_policy_ids: list[str] = []
    grant_ids: list[str] = []
    obligations: set[str] = {"log_decision"}

    plans_to_persist: list[Any] = []

    def _run() -> PrivacyDecision:
        nonlocal resource_decisions, allowed_views, denied, redacted
        nonlocal needs_grant, needs_confirm, all_policy_ids, grant_ids, obligations
        nonlocal plans_to_persist
        resource_decisions = []
        allowed_views = []
        denied = []
        redacted = []
        needs_grant = []
        needs_confirm = []
        all_policy_ids = []
        grant_ids = []
        obligations = {"log_decision"}
        plans_to_persist = []

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
                principal=principal,
            )
            resource_decisions.append(rd)
            all_policy_ids.extend(rd.matched_policy_ids)
            obligations.update(rd.obligations or [])
            if rd.grant_id:
                grant_ids.append(rd.grant_id)

            if rd.effect == PolicyEffect.deny:
                denied.append({"memory_id": mem.id, "reason": rd.reason,
                               "rule": rd.matched_policy_ids[0] if rd.matched_policy_ids else ""})
            elif rd.effect == PolicyEffect.require_grant:
                needs_grant.append({"memory_id": mem.id, "reason": rd.reason})
                denied.append({"memory_id": mem.id, "reason": rd.reason, "rule": "require_grant"})
            elif rd.effect == PolicyEffect.require_confirmation:
                needs_confirm.append({"memory_id": mem.id, "reason": rd.reason})
                denied.append({"memory_id": mem.id, "reason": rd.reason, "rule": "require_confirmation"})
            elif rd.effect in (
                PolicyEffect.redact, PolicyEffect.generalize,
                PolicyEffect.aggregate, PolicyEffect.pseudonymize,
            ):
                plan = plan_redaction(classification, rd, effect=rd.effect)
                rd.redaction_plan_id = plan.id
                if persist and hasattr(store, "insert_redaction_plan"):
                    plans_to_persist.append(plan)
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

        overall = PolicyEffect.allow
        for rd in resource_decisions:
            if _EFFECT_RANK.get(rd.effect, 0) > _EFFECT_RANK.get(overall, 0):
                overall = rd.effect

        version = store.get_active_policy_set_version() if hasattr(store, "get_active_policy_set_version") else None
        return PrivacyDecision(
            id=ids.new_id("pdec"),
            request_fingerprint=_fingerprint(
                request, [m.id for m in memories], [p.id for p in policies],
            ),
            effect=overall,
            matched_policy_ids=sorted(set(all_policy_ids)),
            policy_revision_ids=policy_revision_ids,
            resource_decisions=resource_decisions,
            obligations=sorted(obligations),
            policy_set_version_id=version.id if version else None,
            grant_ids=sorted(set(grant_ids)),
            access_request={
                **request.model_dump(),
                "_resolved": {
                    "principal_id": request.principal_id,
                    "tool_id": request.tool_id,
                    "persona": request.persona,
                    "capabilities": (request.metadata or {}).get("resolved_capabilities"),
                },
                "_claims": (request.metadata or {}).get("claims"),
            },
            engine_version=ENGINE_VERSION,
            created_at=now_iso(),
            metadata={
                "execution_location": execution_location,
                "resources_considered": len(memories),
                "resources_allowed": len(allowed_views),
                "resources_redacted": len(redacted),
                "resources_denied": len(denied),
                "policy_snapshot": policy_snapshot,
            },
        )

    if persist and hasattr(store, "transaction"):
        with store.transaction():
            decision = _run()
            for plan in plans_to_persist:
                store.insert_redaction_plan(plan)
            store.insert_privacy_decision(decision)
    else:
        decision = _run()
        if persist:
            for plan in plans_to_persist:
                if hasattr(store, "insert_redaction_plan"):
                    store.insert_redaction_plan(plan)
            if hasattr(store, "insert_privacy_decision"):
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
        "obligations": decision.obligations,
    }


def evaluate_judgment_items(
    store: MemoryStore,
    request: AccessRequest,
    items: list[Any],
    *,
    policies_path: Optional[Path | str] = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Run governance over judgment items (as classified resources)."""
    from ..judgment.models import JudgmentItem

    synthetic: list[MemoryItem] = []
    for it in items:
        if not isinstance(it, JudgmentItem):
            continue
        synthetic.append(MemoryItem(
            id=it.id,
            type="constraint" if it.kind.value == "constraint" else "belief",
            title=it.statement[:80],
            summary=it.statement,
            domain=it.domain,
            persona=it.persona,
            sensitivity=(
                "restricted" if it.stability.value == "constitutional"
                else "internal"
            ),
            confidence=it.confidence,
            status="confirmed",
            payload={
                "source_owner": (it.provenance.source if it.provenance else "user"),
                "vault_id": "vault_work" if it.domain == "work" else "vault_general",
                "privacy_labels": (
                    ["employment_confidential"] if it.domain == "work" else []
                ),
                "judgment": True,
                "kind": it.kind.value,
            },
        ))
    return evaluate_access(
        store, request, synthetic,
        policies_path=policies_path, persist=persist, consume_grants=False,
    )


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
            "redaction_plan_id": rd.redaction_plan_id,
        })
    return {
        "decision_id": d.id,
        "effect": d.effect.value,
        "engine_version": d.engine_version,
        "policy_set_version_id": d.policy_set_version_id,
        "policy_revision_ids": d.policy_revision_ids,
        "grant_ids": d.grant_ids,
        "obligations": d.obligations,
        "access_request": {
            k: d.access_request.get(k)
            for k in ("persona", "purpose", "audience", "tool_id", "principal_id")
        },
        "resources": lines,
        "created_at": d.created_at,
    }


def validate_output(
    output: str,
    *,
    access: AccessRequest,
    decision: Optional[PrivacyDecision] = None,
    forbidden_substrings: Optional[list[str]] = None,
    store: Optional[MemoryStore] = None,
) -> dict[str, Any]:
    """Scan generated/exported text before release to an external consumer."""
    findings = leakage_scan(output, forbidden_substrings=forbidden_substrings)
    canaries: list[str] = []
    if store is not None and hasattr(store, "list_leakage_canaries"):
        from .canaries import scan_for_canaries
        canaries = scan_for_canaries(store, output)
    blocked = bool(findings) or bool(canaries) or access.is_restricted_mode
    return {
        "allowed": not blocked,
        "findings": findings,
        "canaries": canaries,
        "decision_id": decision.id if decision else None,
        "action": "block" if blocked else "release",
    }


# Alias used by outbound surfaces
validate_outbound_content = validate_output
