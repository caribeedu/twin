"""Classify memories into ResourceClassification for policy evaluation."""

from __future__ import annotations

from typing import Any

from ..memory.models import MemoryItem
from .models import FieldSensitivity, ResourceClassification, SensitivityClass

_DOMAIN_LABELS = {
    "finance": ["financial"],
    "health": ["health"],
    "legal": ["legal"],
    "relationship": ["relationship"],
    "family": ["relationship"],
    "work": ["employment_confidential"],
}

_SENSITIVITY_MAP = {
    "public": SensitivityClass.public,
    "internal": SensitivityClass.internal,
    "private": SensitivityClass.confidential,
    "restricted": SensitivityClass.restricted,
}


def classify_memory(mem: MemoryItem) -> ResourceClassification:
    payload = dict(mem.payload or {})
    labels: list[str] = list(payload.get("privacy_labels") or [])
    labels.extend(_DOMAIN_LABELS.get(mem.domain, []))
    if payload.get("third_party"):
        labels.append("third_party")
    if any(k in payload for k in ("password", "api_key", "secret", "token")):
        labels.append("credential")
        labels.append("secret")
    labels = sorted(set(labels))

    sens = mem.sensitivity.value if hasattr(mem.sensitivity, "value") else str(mem.sensitivity)
    mapped = _SENSITIVITY_MAP.get(sens, SensitivityClass.internal)

    fields: dict[str, FieldSensitivity] = {}
    raw_fields = payload.get("fields") or {}
    if isinstance(raw_fields, dict):
        for path, spec in raw_fields.items():
            if isinstance(spec, dict):
                fields[path] = FieldSensitivity(
                    sensitivity=SensitivityClass(spec.get("sensitivity", mapped.value)),
                    labels=list(spec.get("labels") or []),
                    third_party=bool(spec.get("third_party")),
                    owner=spec.get("owner"),
                )
            else:
                fields[path] = FieldSensitivity(sensitivity=mapped)

    # Common sensitive payload keys without explicit field map
    for key in ("salary", "income", "bank_account", "cpf", "ssn", "password", "api_key"):
        if key in payload and key not in fields:
            fields[key] = FieldSensitivity(
                sensitivity=SensitivityClass.restricted
                if key in ("salary", "income", "bank_account", "password", "api_key")
                else SensitivityClass.confidential,
                labels=["financial"] if key in ("salary", "income", "bank_account") else ["pii"],
            )

    source_owner = (
        payload.get("source_owner")
        or payload.get("owner")
        or ("employer" if mem.domain == "work" else "user")
    )
    vault_id = payload.get("vault_id") or (
        "vault_work" if source_owner == "employer" or mem.domain == "work"
        else "vault_personal" if mem.domain in ("finance", "health", "relationship", "family")
        else "vault_general"
    )

    return ResourceClassification(
        resource_id=mem.id,
        domain=mem.domain,
        sensitivity=mapped.value,
        labels=labels,
        persona=mem.persona or "individual",
        vault_id=vault_id,
        source_owner=str(source_owner),
        subjects=list(payload.get("subjects") or []),
        third_party=bool(payload.get("third_party")) or "third_party" in labels,
        fields=fields,
        payload=payload,
        title=mem.title,
        summary=mem.summary,
    )


def classify_text_blob(resource_id: str, text: str, **kwargs: Any) -> ResourceClassification:
    """Minimal classification for non-memory resources (exports, packs)."""
    return ResourceClassification(
        resource_id=resource_id,
        summary=text[:500],
        **kwargs,
    )
