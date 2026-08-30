"""Explicit memory formation pipeline.

Turns grounded interpretations into durable candidates with deterministic
identity, evidence aggregation, review gates, and auditable confirm/reject.
Never self-confirms Memory or Judgment.
"""

from __future__ import annotations

import hashlib
import re
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from twin import ids
from twin.clock import now_iso
from .models import (
    Evidence,
    StoreClaim,
    ClaimOperation,
    ClaimStatus,
    ClaimType,
)
from .store.base import TwinStore


class FormationState(str, Enum):
    """Logical formation stage (may overlay ClaimStatus + flags)."""

    candidate = "candidate"
    corroborating = "corroborating"
    conflicting = "conflicting"
    awaiting_review = "awaiting_review"
    confirmed = "confirmed"
    rejected = "rejected"
    superseded = "superseded"
    expired = "expired"


# Per-type confirmation / review defaults (formation policy).
FORMATION_POLICY: dict[str, dict[str, Any]] = {
    ClaimType.fact.value: {
        "auto_confirm": False, "require_review_below": 0.75, "expires": False,
    },
    ClaimType.event.value: {
        "auto_confirm": False, "require_review_below": 0.7, "expires": False,
    },
    ClaimType.decision.value: {
        "auto_confirm": False, "require_review_below": 0.85, "expires": False,
    },
    ClaimType.task.value: {
        "auto_confirm": False, "require_review_below": 0.65, "expires": True,
    },
    ClaimType.constraint.value: {
        "auto_confirm": False, "require_review_below": 0.8, "expires": False,
    },
    ClaimType.preference.value: {
        "auto_confirm": False, "require_review_below": 0.8, "expires": False,
    },
    ClaimType.belief.value: {
        "auto_confirm": False, "require_review_below": 0.0, "expires": False,
        "always_review": True,
    },
    ClaimType.procedure.value: {
        "auto_confirm": False, "require_review_below": 0.0, "expires": False,
        "always_review": True,
    },
    ClaimType.relationship.value: {
        "auto_confirm": False, "require_review_below": 0.75, "expires": False,
    },
    ClaimType.communication_act.value: {
        "auto_confirm": False, "require_review_below": 0.7, "expires": False,
    },
}


class ClaimCandidate(BaseModel):
    """Formation-facing view over a StoreClaim awaiting human review.

    Not a product “memory” entity. Twin’s durable substrate is Narrative /
    Reflection / Interpretation / Stance / Evidence (docs/v2.md §2.2). This
    type is the review-queue shape used by formation helpers.
    """

    id: str
    formation_identity: str
    formation_state: FormationState
    claim: StoreClaim
    evidence_count: int = 0
    interpretation_percept_ids: list[str] = Field(default_factory=list)
    reject_reason: str = ""
    policy: dict[str, Any] = Field(default_factory=dict)
    explanation: str = ""


def _norm(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t


def formation_identity(
    *,
    type_: str,
    domain: str,
    project_id: Optional[str],
    title: str,
    summary: str,
    canonical_claim: Optional[dict[str, Any]] = None,
) -> str:
    """Deterministic identity for a cognitive claim (not a random mem id)."""
    if canonical_claim and (canonical_claim.get("subject") or canonical_claim.get("predicate")):
        claim = "|".join([
            _norm(str(canonical_claim.get("subject", ""))),
            _norm(str(canonical_claim.get("predicate", ""))),
            _norm(str(canonical_claim.get("object", ""))),
        ])
    else:
        claim = f"{_norm(title)}|{_norm(summary)[:240]}"
    raw = f"{type_}|{_norm(domain)}|{project_id or ''}|{claim}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:22]
    return f"fid_{digest}"


def claim_id_for_identity(identity: str) -> str:
    """Stable StoreClaim.id derived from formation identity."""
    digest = identity.removeprefix("fid_")
    return f"mem_f{digest}"


def derive_formation_state(mem: StoreClaim) -> FormationState:
    st = mem.status.value if hasattr(mem.status, "value") else str(mem.status)
    if st == ClaimStatus.confirmed.value:
        return FormationState.confirmed
    if st == ClaimStatus.rejected.value:
        return FormationState.rejected
    if st in (ClaimStatus.deprecated.value, "superseded"):
        return FormationState.superseded
    if st in (ClaimStatus.archived.value, "expired") and (
        (mem.payload or {}).get("formation_state") == "expired"
        or st == "expired"
    ):
        return FormationState.expired
    if st == ClaimStatus.contradicted.value or "conflict" in (mem.quality_flags or []):
        return FormationState.conflicting
    if mem.needs_review:
        return FormationState.awaiting_review
    payload = mem.payload or {}
    if payload.get("formation_state") == FormationState.corroborating.value:
        return FormationState.corroborating
    if (payload.get("corroboration_count") or 0) > 0:
        return FormationState.corroborating
    return FormationState.candidate


def as_candidate(store: TwinStore, mem: StoreClaim) -> ClaimCandidate:
    evidence = store.get_evidence(mem.id) if hasattr(store, "get_evidence") else []
    payload = mem.payload or {}
    identity = payload.get("formation_identity") or formation_identity(
        type_=mem.type.value if hasattr(mem.type, "value") else str(mem.type),
        domain=mem.domain,
        project_id=mem.project_id,
        title=mem.title,
        summary=mem.summary,
        canonical_claim=(
            mem.canonical_claim.model_dump() if mem.canonical_claim else None
        ),
    )
    state = derive_formation_state(mem)
    policy = FORMATION_POLICY.get(
        mem.type.value if hasattr(mem.type, "value") else str(mem.type), {},
    )
    return ClaimCandidate(
        id=mem.id,
        formation_identity=identity,
        formation_state=state,
        claim=mem,
        evidence_count=len(evidence),
        interpretation_percept_ids=list(payload.get("interpretation_percept_ids") or []),
        reject_reason=str(payload.get("reject_reason") or mem.review_reason or ""),
        policy=dict(policy),
        explanation=_explain(mem, state, len(evidence), policy),
    )


def _explain(
    mem: StoreClaim, state: FormationState, evidence_n: int, policy: dict,
) -> str:
    parts = [
        f"state={state.value}",
        f"type={getattr(mem.type, 'value', mem.type)}",
        f"domain={mem.domain}",
        f"evidence={evidence_n}",
        f"confidence={mem.confidence:.2f}",
    ]
    if mem.needs_review:
        parts.append(f"review={mem.review_reason or 'flagged'}")
    if policy.get("always_review"):
        parts.append("policy=always_review")
    return "; ".join(parts)


def _record_op(
    store: TwinStore,
    operation: str,
    claim_id: str,
    before: dict,
    after: dict,
    *,
    actor: str = "user",
    undoable: bool = True,
) -> Optional[str]:
    if not hasattr(store, "insert_operation"):
        return None
    op = ClaimOperation(
        id=ids.operation_id(),
        operation=operation,
        actor=actor,
        at=now_iso(),
        inputs=[claim_id],
        output=claim_id,
        before=before,
        after=after,
        undoable=undoable,
    )
    store.insert_operation(op)
    return op.id


def apply_formation_policy(
    mem: StoreClaim, *, review_reason: Optional[str] = None,
) -> StoreClaim:
    """Annotate candidate with formation identity + policy review gates.

    Never confirms. May force ``needs_review``.
    """
    type_s = mem.type.value if hasattr(mem.type, "value") else str(mem.type)
    policy = FORMATION_POLICY.get(type_s, {})
    claim = mem.canonical_claim.model_dump() if mem.canonical_claim else None
    identity = formation_identity(
        type_=type_s,
        domain=mem.domain,
        project_id=mem.project_id,
        title=mem.title,
        summary=mem.summary,
        canonical_claim=claim,
    )
    payload = dict(mem.payload or {})
    payload["formation_identity"] = identity
    payload.setdefault("formation_state", FormationState.candidate.value)
    payload.setdefault("interpretation_percept_ids", [])
    payload.setdefault("corroboration_count", 0)
    payload["formation_policy"] = {
        k: policy.get(k) for k in ("auto_confirm", "require_review_below", "always_review", "expires")
        if k in policy
    }

    reason = review_reason or mem.review_reason
    if policy.get("always_review"):
        reason = reason or f"formation policy: {type_s} always requires review"
    threshold = policy.get("require_review_below")
    if threshold is not None and mem.confidence < float(threshold):
        reason = reason or (
            f"formation policy: confidence {mem.confidence:.2f} < {threshold}"
        )

    # Stable StoreClaim.id from formation identity (idempotent proposes).
    if payload.pop("use_deterministic_id", True):
        mem.id = claim_id_for_identity(identity)

    mem.payload = payload
    if reason:
        mem.needs_review = True
        mem.review_reason = reason
        payload["formation_state"] = FormationState.awaiting_review.value
        mem.payload = payload
    # Invariant: formation never confirms
    if mem.status == ClaimStatus.confirmed:
        mem.status = ClaimStatus.candidate
    return mem


def find_by_formation_identity(
    store: TwinStore, identity: str,
) -> Optional[StoreClaim]:
    mid = claim_id_for_identity(identity)
    mem = store.get_claim(mid)
    if mem is not None:
        return mem
    # Fallback scan for legacy rows that stored identity only in payload
    for m in store.list_claims(status=ClaimStatus.candidate.value, limit=500):
        if (m.payload or {}).get("formation_identity") == identity:
            return m
    for m in store.list_claims(status=ClaimStatus.confirmed.value, limit=500):
        if (m.payload or {}).get("formation_identity") == identity:
            return m
    return None


def propose_or_corroborate(
    store: TwinStore,
    mem: StoreClaim,
    *,
    percept_id: str,
    evidence_quote: str,
    independence_group: str = "",
    source_trust: float = 0.8,
    directness: float = 1.0,
    artifact_id: Optional[str] = None,
) -> tuple[StoreClaim, str]:
    """Insert a new candidate or corroborate an existing one.

    Returns ``(memory, action)`` where action is ``created`` | ``corroborated``.
    Never confirms.
    """
    from twin.cognize.services.evidence_text import sanitize_evidence_quote

    evidence_quote = sanitize_evidence_quote(evidence_quote)
    mem = apply_formation_policy(mem)
    identity = mem.payload["formation_identity"]
    existing = find_by_formation_identity(store, identity)
    if existing is not None:
        from .provenance import attach_corroborating_evidence
        attach_corroborating_evidence(
            store, existing.id, percept_id, evidence_quote,
            independence_group=independence_group or None,
            source_trust=source_trust,
        )
        payload = dict(existing.payload or {})
        payload["corroboration_count"] = int(payload.get("corroboration_count") or 0) + 1
        payload["formation_state"] = FormationState.corroborating.value
        pids = list(payload.get("interpretation_percept_ids") or [])
        if percept_id and percept_id not in pids:
            pids.append(percept_id)
        payload["interpretation_percept_ids"] = pids
        store.update_claim(existing.id, payload=payload)
        if existing.needs_review or "conflict" in (existing.quality_flags or []):
            pass
        reloaded = store.get_claim(existing.id)
        assert reloaded is not None
        _record_op(
            store, "formation_corroborate", existing.id,
            before={"corroboration_count": int((existing.payload or {}).get("corroboration_count") or 0)},
            after={"corroboration_count": payload["corroboration_count"], "percept_id": percept_id},
            actor="system",
            undoable=False,
        )
        return reloaded, "corroborated"

    payload = dict(mem.payload or {})
    pids = list(payload.get("interpretation_percept_ids") or [])
    if percept_id and percept_id not in pids:
        pids.append(percept_id)
    payload["interpretation_percept_ids"] = pids
    mem.payload = payload
    mem.status = ClaimStatus.candidate
    try:
        store.insert_claim(mem)
    except Exception:
        # Race: another writer inserted the same deterministic id — corroborate.
        existing = store.get_claim(mem.id)
        if existing is None:
            raise
        from .provenance import attach_corroborating_evidence
        attach_corroborating_evidence(
            store, existing.id, percept_id, evidence_quote,
            independence_group=independence_group or None,
            source_trust=source_trust,
        )
        payload = dict(existing.payload or {})
        payload["corroboration_count"] = int(payload.get("corroboration_count") or 0) + 1
        payload["formation_state"] = FormationState.corroborating.value
        store.update_claim(existing.id, payload=payload)
        reloaded = store.get_claim(existing.id)
        assert reloaded is not None
        return reloaded, "corroborated"

    store.insert_evidence(Evidence(
        id=ids.evidence_id(),
        claim_id=mem.id,
        percept_id=percept_id,
        quote=evidence_quote,
        source_trust=source_trust,
        directness=directness,
        independence_group=independence_group or None,
        artifact_id=artifact_id,
    ))
    _record_op(
        store, "formation_propose", mem.id,
        before={},
        after={"formation_identity": identity, "status": "candidate"},
        actor="system",
        undoable=False,
    )
    return mem, "created"


def confirm_candidate(
    store: TwinStore,
    claim_id: str,
    *,
    actor: str = "user",
    note: str = "",
) -> ClaimCandidate:
    mem = store.get_claim(claim_id)
    if mem is None:
        raise ValueError(f"memory {claim_id} not found")
    st = mem.status.value if hasattr(mem.status, "value") else str(mem.status)
    if st not in (
        ClaimStatus.candidate.value,
        ClaimStatus.contradicted.value,  # human may still confirm after review
    ):
        if st == ClaimStatus.confirmed.value:
            return as_candidate(store, mem)
        raise ValueError(f"memory {claim_id} is {st}, not confirmable")
    evidence = store.get_evidence(claim_id)
    if not evidence:
        raise ValueError(f"memory {claim_id} has no evidence — cannot confirm")
    before = mem.model_dump(mode="json")
    payload = dict(mem.payload or {})
    payload["formation_state"] = FormationState.confirmed.value
    if note:
        payload["confirm_note"] = note
    store.update_claim(
        claim_id,
        status=ClaimStatus.confirmed.value,
        needs_review=False,
        review_reason=None,
        reviewed_at=now_iso(),
        payload=payload,
    )
    after = store.get_claim(claim_id)
    assert after is not None
    _record_op(
        store, "formation_confirm", claim_id,
        before=before, after=after.model_dump(mode="json"), actor=actor,
    )
    return as_candidate(store, after)


def reject_candidate(
    store: TwinStore,
    claim_id: str,
    *,
    reason: str,
    actor: str = "user",
) -> ClaimCandidate:
    if not (reason or "").strip():
        raise ValueError("reject requires a non-empty reason")
    mem = store.get_claim(claim_id)
    if mem is None:
        raise ValueError(f"memory {claim_id} not found")
    st = mem.status.value if hasattr(mem.status, "value") else str(mem.status)
    if st == ClaimStatus.rejected.value:
        return as_candidate(store, mem)
    if st == ClaimStatus.confirmed.value:
        raise ValueError("refuse to reject confirmed memory without supersede/archive")
    before = mem.model_dump(mode="json")
    payload = dict(mem.payload or {})
    payload["formation_state"] = FormationState.rejected.value
    payload["reject_reason"] = reason.strip()
    store.update_claim(
        claim_id,
        status=ClaimStatus.rejected.value,
        needs_review=False,
        review_reason=reason.strip(),
        reviewed_at=now_iso(),
        payload=payload,
    )
    after = store.get_claim(claim_id)
    assert after is not None
    _record_op(
        store, "formation_reject", claim_id,
        before=before, after=after.model_dump(mode="json"), actor=actor,
    )
    return as_candidate(store, after)


def restore_candidate(
    store: TwinStore,
    claim_id: str,
    *,
    actor: str = "user",
) -> ClaimCandidate:
    """Restore a rejected candidate back to awaiting_review / candidate."""
    mem = store.get_claim(claim_id)
    if mem is None:
        raise ValueError(f"memory {claim_id} not found")
    st = mem.status.value if hasattr(mem.status, "value") else str(mem.status)
    if st != ClaimStatus.rejected.value:
        raise ValueError(f"memory {claim_id} is {st}, not rejected")
    before = mem.model_dump(mode="json")
    payload = dict(mem.payload or {})
    reason = payload.pop("reject_reason", None)
    payload["formation_state"] = FormationState.awaiting_review.value
    payload["restored_from_reject"] = True
    if reason:
        payload["prior_reject_reason"] = reason
    store.update_claim(
        claim_id,
        status=ClaimStatus.candidate.value,
        needs_review=True,
        review_reason="restored from reject — re-review required",
        reviewed_at=None,
        payload=payload,
    )
    after = store.get_claim(claim_id)
    assert after is not None
    _record_op(
        store, "formation_restore", claim_id,
        before=before, after=after.model_dump(mode="json"), actor=actor,
    )
    return as_candidate(store, after)


def edit_candidate(
    store: TwinStore,
    claim_id: str,
    *,
    title: Optional[str] = None,
    summary: Optional[str] = None,
    domain: Optional[str] = None,
    actor: str = "user",
) -> ClaimCandidate:
    mem = store.get_claim(claim_id)
    if mem is None:
        raise ValueError(f"memory {claim_id} not found")
    st = mem.status.value if hasattr(mem.status, "value") else str(mem.status)
    if st not in (ClaimStatus.candidate.value, ClaimStatus.rejected.value):
        raise ValueError(f"memory {claim_id} is {st}, not editable via formation")
    before = mem.model_dump(mode="json")
    fields: dict[str, Any] = {}
    if title is not None:
        fields["title"] = title
    if summary is not None:
        fields["summary"] = summary
    if domain is not None:
        fields["domain"] = domain
    if not fields:
        return as_candidate(store, mem)
    fields["needs_review"] = True
    fields["review_reason"] = mem.review_reason or "edited — re-review required"
    store.update_claim(claim_id, **fields)
    after = store.get_claim(claim_id)
    assert after is not None
    _record_op(
        store, "formation_edit", claim_id,
        before=before, after=after.model_dump(mode="json"), actor=actor,
    )
    return as_candidate(store, after)


def mark_conflicting(store: TwinStore, claim_id: str, *, reason: str = "") -> ClaimCandidate:
    mem = store.get_claim(claim_id)
    if mem is None:
        raise ValueError(f"memory {claim_id} not found")
    flags = list(mem.quality_flags or [])
    if "conflict" not in flags:
        flags.append("conflict")
    payload = dict(mem.payload or {})
    payload["formation_state"] = FormationState.conflicting.value
    store.update_claim(
        claim_id,
        quality_flags=flags,
        needs_review=True,
        review_reason=reason or mem.review_reason or "formation conflict",
        payload=payload,
    )
    after = store.get_claim(claim_id)
    assert after is not None
    return as_candidate(store, after)


def list_candidates(
    store: TwinStore,
    *,
    state: Optional[str] = None,
    limit: int = 100,
) -> list[ClaimCandidate]:
    rows = store.list_claims(status=ClaimStatus.candidate.value, limit=limit * 2)
    # also surface rejected awaiting restore in review queues when asked
    if state in (None, FormationState.rejected.value):
        rows = rows + store.list_claims(status=ClaimStatus.rejected.value, limit=limit)
    out: list[ClaimCandidate] = []
    for mem in rows:
        cand = as_candidate(store, mem)
        if state and cand.formation_state.value != state:
            continue
        out.append(cand)
        if len(out) >= limit:
            break
    return out


def explain_memory(store: TwinStore, claim_id: str) -> dict[str, Any]:
    mem = store.get_claim(claim_id)
    if mem is None:
        raise ValueError(f"memory {claim_id} not found")
    cand = as_candidate(store, mem)
    evidence = [
        {
            "id": e.id,
            "percept_id": e.percept_id,
            "quote": e.quote[:200],
            "supports": e.supports,
            "independence_group": e.independence_group,
        }
        for e in store.get_evidence(claim_id)
    ]
    history: list[dict[str, Any]] = []
    if hasattr(store, "list_operations_for"):
        history = [
            {"id": op.id, "operation": op.operation, "actor": op.actor, "at": op.at}
            for op in store.list_operations_for(claim_id, limit=50)  # type: ignore[attr-defined]
        ]
    elif hasattr(store, "get_operations"):
        pass
    return {
        "claim_id": claim_id,
        "formation_identity": cand.formation_identity,
        "formation_state": cand.formation_state.value,
        "status": mem.status.value if hasattr(mem.status, "value") else str(mem.status),
        "domain": mem.domain,
        "type": mem.type.value if hasattr(mem.type, "value") else str(mem.type),
        "confidence": mem.confidence,
        "needs_review": mem.needs_review,
        "review_reason": mem.review_reason,
        "evidence": evidence,
        "policy": cand.policy,
        "explanation": cand.explanation,
        "history": history,
        "provenance": {
            "interpretation_percept_ids": cand.interpretation_percept_ids,
            "extractor_version": (
                mem.extractor_version.model_dump() if mem.extractor_version else None
            ),
        },
    }
