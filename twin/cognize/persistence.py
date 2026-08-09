"""Row codecs for Cognize entity tables."""

from __future__ import annotations

import json
from typing import Any

from twin.cognize.models import (
    EpistemicState,
    EvidenceAnchor,
    Interpretation,
    Narrative,
    NarrativeRevisionDecision,
    Reflection,
    Relation,
    Situation,
    Trace,
)


def _dump(model: Any) -> str:
    return json.dumps(model.model_dump(mode="json"), default=str)


def _load(cls, payload: str | bytes | dict):
    if isinstance(payload, dict):
        return cls.model_validate(payload)
    return cls.model_validate_json(payload)


def situation_to_row(obj: Situation) -> dict[str, Any]:
    return {
        "id": obj.id,
        "vault_id": obj.vault_id,
        "status": obj.status.value if hasattr(obj.status, "value") else obj.status,
        "payload": _dump(obj),
    }


def row_to_situation(row: Any, decrypt=None) -> Situation:
    payload = row["payload"]
    if decrypt:
        payload = decrypt(payload)
    return _load(Situation, payload)


def reflection_to_row(obj: Reflection) -> dict[str, Any]:
    return {
        "id": obj.id,
        "vault_id": obj.vault_id,
        "status": obj.status.value if hasattr(obj.status, "value") else obj.status,
        "payload": _dump(obj),
    }


def row_to_reflection(row: Any, decrypt=None) -> Reflection:
    payload = row["payload"]
    if decrypt:
        payload = decrypt(payload)
    return _load(Reflection, payload)


def interpretation_to_row(obj: Interpretation) -> dict[str, Any]:
    return {
        "id": obj.id,
        "vault_id": obj.vault_id,
        "status": obj.status.value if hasattr(obj.status, "value") else obj.status,
        "payload": _dump(obj),
    }


def row_to_interpretation(row: Any, decrypt=None) -> Interpretation:
    payload = row["payload"]
    if decrypt:
        payload = decrypt(payload)
    return _load(Interpretation, payload)


def relation_to_row(obj: Relation) -> dict[str, Any]:
    return {
        "id": obj.id,
        "vault_id": obj.vault_id,
        "from_id": obj.from_id,
        "to_id": obj.to_id,
        "type": obj.type.value if hasattr(obj.type, "value") else obj.type,
        "asserted_by": obj.asserted_by.value
        if hasattr(obj.asserted_by, "value")
        else obj.asserted_by,
        "payload": _dump(obj),
    }


def row_to_relation(row: Any, decrypt=None) -> Relation:
    payload = row["payload"]
    if decrypt:
        payload = decrypt(payload)
    return _load(Relation, payload)


def epistemic_state_to_row(obj: EpistemicState) -> dict[str, Any]:
    return {
        "id": obj.id,
        "status": obj.status.value if hasattr(obj.status, "value") else obj.status,
        "payload": _dump(obj),
    }


def row_to_epistemic_state(row: Any, decrypt=None) -> EpistemicState:
    payload = row["payload"]
    if decrypt:
        payload = decrypt(payload)
    return _load(EpistemicState, payload)


def narrative_to_row(obj: Narrative) -> dict[str, Any]:
    return {
        "id": obj.id,
        "vault_id": obj.vault_id,
        "status": obj.status.value if hasattr(obj.status, "value") else obj.status,
        "epistemic_state_id": obj.epistemic_state_id or "",
        "domain": obj.domain or "",
        "payload": _dump(obj),
    }


def row_to_narrative(row: Any, decrypt=None) -> Narrative:
    payload = row["payload"]
    if decrypt:
        payload = decrypt(payload)
    return _load(Narrative, payload)


def evidence_anchor_to_row(obj: EvidenceAnchor) -> dict[str, Any]:
    return {
        "id": obj.id,
        "vault_id": obj.vault_id,
        "percept_id": obj.percept_id,
        "target_kind": obj.target_kind or "",
        "target_id": obj.target_id or "",
        "payload": _dump(obj),
    }


def row_to_evidence_anchor(row: Any, decrypt=None) -> EvidenceAnchor:
    payload = row["payload"]
    if decrypt:
        payload = decrypt(payload)
    return _load(EvidenceAnchor, payload)


def trace_to_row(obj: Trace) -> dict[str, Any]:
    return {
        "id": obj.id,
        "vault_id": obj.vault_id or "",
        "event_kind": obj.event_kind,
        "resource_kind": obj.resource_kind or "",
        "resource_id": obj.resource_id or "",
        "payload": _dump(obj),
    }


def row_to_trace(row: Any, decrypt=None) -> Trace:
    payload = row["payload"]
    if decrypt:
        payload = decrypt(payload)
    return _load(Trace, payload)


def narrative_revision_to_row(obj: NarrativeRevisionDecision) -> dict[str, Any]:
    return {
        "id": obj.id,
        "vault_id": obj.vault_id or "",
        "outcome": obj.outcome.value if hasattr(obj.outcome, "value") else obj.outcome,
        "prior_narrative_id": obj.prior_narrative_id or "",
        "payload": _dump(obj),
    }


def row_to_narrative_revision(row: Any, decrypt=None) -> NarrativeRevisionDecision:
    payload = row["payload"]
    if decrypt:
        payload = decrypt(payload)
    return _load(NarrativeRevisionDecision, payload)
