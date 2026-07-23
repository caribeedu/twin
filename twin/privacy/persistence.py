"""Row serializers for privacy / governance entities."""

from __future__ import annotations

import json
from typing import Any

from .models import (
    ClientBinding,
    ConsentRecord,
    DeletionRequest,
    ExportRecord,
    LeakageCanary,
    PermissionGrant,
    PersonaRecord,
    PolicySetVersion,
    Principal,
    PrivacyDecision,
    PrivacyPolicy,
    PrivacyPolicyRevision,
    QuarantineRecord,
    RedactionPlan,
    ToolIdentity,
    Vault,
)


def _j(value: Any) -> str:
    return json.dumps(value if value is not None else {}, default=str)


def _loads(raw: Any, default: Any = None):
    if raw is None:
        return default if default is not None else {}
    if isinstance(raw, (dict, list)):
        return raw
    return json.loads(raw)


def policy_to_row(p: PrivacyPolicy) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "effect": p.effect.value,
        "priority": p.priority,
        "enabled": 1 if p.enabled else 0,
        "overrideable": 1 if p.overrideable else 0,
        "constitutional": 1 if p.constitutional else 0,
        "payload": _j(p.model_dump(mode="json")),
        "created_at": p.created_at,
        "version": p.version,
    }


def row_to_policy(row: Any) -> PrivacyPolicy:
    payload = _loads(row["payload"], {})
    return PrivacyPolicy.model_validate(payload)


def decision_to_row(d: PrivacyDecision) -> dict[str, Any]:
    return {
        "id": d.id,
        "request_fingerprint": d.request_fingerprint,
        "effect": d.effect.value,
        "payload": _j(d.model_dump(mode="json")),
        "policy_set_version_id": d.policy_set_version_id,
        "created_at": d.created_at,
    }


def row_to_decision(row: Any) -> PrivacyDecision:
    return PrivacyDecision.model_validate(_loads(row["payload"], {}))


def grant_to_row(g: PermissionGrant) -> dict[str, Any]:
    return {
        "id": g.id,
        "principal_id": g.principal_id,
        "persona": g.persona,
        "purpose": g.purpose,
        "status": g.status.value,
        "uses": g.uses,
        "max_uses": g.max_uses,
        "version": g.version,
        "valid_from": g.valid_from,
        "valid_until": g.valid_until,
        "revoked_at": g.revoked_at,
        "payload": _j(g.model_dump(mode="json")),
    }


def row_to_grant(row: Any) -> PermissionGrant:
    return PermissionGrant.model_validate(_loads(row["payload"], {}))


def consent_to_row(c: ConsentRecord) -> dict[str, Any]:
    return {
        "id": c.id,
        "subject_id": c.subject_id,
        "status": c.status.value,
        "payload": _j(c.model_dump(mode="json")),
        "created_at": c.created_at,
    }


def row_to_consent(row: Any) -> ConsentRecord:
    return ConsentRecord.model_validate(_loads(row["payload"], {}))


def quarantine_to_row(q: QuarantineRecord) -> dict[str, Any]:
    return {
        "id": q.id,
        "artifact_id": q.artifact_id,
        "percept_id": q.percept_id,
        "status": q.status.value,
        "content_fingerprint": q.content_fingerprint,
        "payload": _j(q.model_dump(mode="json")),
        "created_at": q.created_at,
    }


def row_to_quarantine(row: Any) -> QuarantineRecord:
    return QuarantineRecord.model_validate(_loads(row["payload"], {}))


def canary_to_row(c: LeakageCanary) -> dict[str, Any]:
    return {
        "id": c.id,
        "token": c.token,
        "vault_id": c.vault_id,
        "active": 1 if c.active else 0,
        "payload": _j(c.model_dump(mode="json")),
        "created_at": c.created_at,
    }


def row_to_canary(row: Any) -> LeakageCanary:
    return LeakageCanary.model_validate(_loads(row["payload"], {}))


def deletion_to_row(d: DeletionRequest) -> dict[str, Any]:
    return {
        "id": d.id,
        "status": d.status.value,
        "mode": d.mode.value,
        "payload": _j(d.model_dump(mode="json")),
        "created_at": d.created_at,
    }


def row_to_deletion(row: Any) -> DeletionRequest:
    return DeletionRequest.model_validate(_loads(row["payload"], {}))


def export_to_row(e: ExportRecord) -> dict[str, Any]:
    return {
        "id": e.id,
        "purpose": e.purpose,
        "destination": e.destination,
        "payload": _j(e.model_dump(mode="json")),
        "created_at": e.created_at,
    }


def row_to_export(row: Any) -> ExportRecord:
    return ExportRecord.model_validate(_loads(row["payload"], {}))


def policy_set_to_row(v: PolicySetVersion) -> dict[str, Any]:
    meta = dict(v.metadata or {})
    meta["revision_ids"] = list(v.revision_ids or [])
    return {
        "id": v.id,
        "version": v.version,
        "created_at": v.created_at,
        "reason": v.reason,
        "policy_ids": _j(v.policy_ids),
        "active": 1 if v.active else 0,
        "actor": v.actor,
        "metadata": _j(meta),
    }


def row_to_policy_set(row: Any) -> PolicySetVersion:
    meta = _loads(row["metadata"], {})
    revision_ids = list(meta.pop("revision_ids", []) or [])
    return PolicySetVersion(
        id=row["id"],
        version=int(row["version"]),
        created_at=row["created_at"],
        reason=row["reason"] or "",
        policy_ids=_loads(row["policy_ids"], []),
        revision_ids=revision_ids,
        active=bool(row["active"]),
        actor=row["actor"] or "user",
        metadata=meta,
    )


def principal_to_row(p: Principal) -> dict[str, Any]:
    return {"id": p.id, "payload": _j(p.model_dump(mode="json"))}


def row_to_principal(row: Any) -> Principal:
    return Principal.model_validate(_loads(row["payload"], {}))


def tool_to_row(t: ToolIdentity) -> dict[str, Any]:
    return {"id": t.id, "payload": _j(t.model_dump(mode="json"))}


def row_to_tool(row: Any) -> ToolIdentity:
    return ToolIdentity.model_validate(_loads(row["payload"], {}))


def vault_to_row(v: Vault) -> dict[str, Any]:
    return {"id": v.id, "payload": _j(v.model_dump(mode="json"))}


def row_to_vault(row: Any) -> Vault:
    return Vault.model_validate(_loads(row["payload"], {}))


def persona_to_row(p: PersonaRecord) -> dict[str, Any]:
    return {"id": p.id, "payload": _j(p.model_dump(mode="json"))}


def row_to_persona(row: Any) -> PersonaRecord:
    return PersonaRecord.model_validate(_loads(row["payload"], {}))


def binding_to_row(b: ClientBinding) -> dict[str, Any]:
    return {
        "id": b.id,
        "client_id": b.client_id,
        "tool_id": b.tool_id,
        "principal_id": b.principal_id,
        "payload": _j(b.model_dump(mode="json")),
    }


def row_to_binding(row: Any) -> ClientBinding:
    return ClientBinding.model_validate(_loads(row["payload"], {}))


def policy_revision_to_row(r: PrivacyPolicyRevision) -> dict[str, Any]:
    return {
        "id": r.id,
        "policy_id": r.policy_id,
        "version": r.version,
        "payload": _j(r.model_dump(mode="json")),
        "created_at": r.created_at,
    }


def row_to_policy_revision(row: Any) -> PrivacyPolicyRevision:
    return PrivacyPolicyRevision.model_validate(_loads(row["payload"], {}))


def redaction_to_row(r: RedactionPlan) -> dict[str, Any]:
    return {
        "id": r.id,
        "resource_id": r.resource_id,
        "payload": _j(r.model_dump(mode="json")),
        "created_at": r.created_at,
    }


def row_to_redaction(row: Any) -> RedactionPlan:
    return RedactionPlan.model_validate(_loads(row["payload"], {}))
