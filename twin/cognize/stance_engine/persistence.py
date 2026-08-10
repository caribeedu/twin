"""Serialize / deserialize judgment rows for store backends."""

from __future__ import annotations

import json
from typing import Any

from .models import (
    AppliedJudgmentEffect,
    AppliedRevisionRef,
    JudgmentConflict,
    JudgmentException,
    JudgmentItem,
    JudgmentProposal,
    JudgmentProvenance,
    JudgmentRevision,
    JudgmentScope,
    JudgmentSnapshot,
    JudgmentTrace,
    JudgmentVersion,
)


def _loads(raw: Any, default: Any):
    if raw is None or raw == "":
        return default
    return json.loads(raw) if isinstance(raw, str) else raw


def item_to_row(item: JudgmentItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind.value,
        "statement": item.statement,
        "description": item.description,
        "domain": item.domain,
        "persona": item.persona,
        "scope": json.dumps(item.scope.model_dump()),
        "strength": item.strength,
        "confidence": item.confidence,
        "stability": item.stability.value,
        "status": item.status.value,
        "valid_from": item.valid_from,
        "valid_until": item.valid_until,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "approved_at": item.approved_at,
        "approved_by": item.approved_by,
        "provenance": json.dumps(item.provenance.model_dump()),
        "exceptions": json.dumps([e.model_dump(mode="json") for e in item.exceptions]),
        "conflicts_with": json.dumps(item.conflicts_with),
        "supersedes": item.supersedes,
        "tradeoff": item.tradeoff,
        "lean": item.lean,
        "current_revision_id": item.current_revision_id,
        "revision": item.revision,
        "metadata": json.dumps(item.metadata),
    }


def row_to_item(row: Any) -> JudgmentItem:
    get = row.__getitem__ if not isinstance(row, dict) else row.get
    scope = JudgmentScope(**_loads(get("scope"), {}))
    prov = JudgmentProvenance(**_loads(get("provenance"), {}))
    exceptions = [JudgmentException(**e) for e in _loads(get("exceptions"), [])]
    return JudgmentItem(
        id=get("id"),
        kind=get("kind"),
        statement=get("statement"),
        description=get("description") or "",
        domain=get("domain") or "technical",
        persona=get("persona") or "individual",
        scope=scope,
        strength=float(get("strength") or 0.5),
        confidence=float(get("confidence") or 0.5),
        stability=get("stability") or "evolving",
        status=get("status") or "candidate",
        valid_from=get("valid_from"),
        valid_until=get("valid_until"),
        created_at=get("created_at") or "",
        updated_at=get("updated_at") or "",
        approved_at=get("approved_at"),
        approved_by=get("approved_by"),
        provenance=prov,
        exceptions=exceptions,
        conflicts_with=_loads(get("conflicts_with"), []),
        supersedes=get("supersedes"),
        tradeoff=get("tradeoff"),
        lean=float(get("lean")) if get("lean") is not None else None,
        current_revision_id=get("current_revision_id") if "current_revision_id" in (row.keys() if hasattr(row, "keys") else row) else None,
        revision=int(get("revision") or 1) if ("revision" in (row.keys() if hasattr(row, "keys") else row) or get("revision") is not None) else 1,
        metadata=_loads(get("metadata"), {}),
    )


def revision_to_row(rev: JudgmentRevision) -> dict[str, Any]:
    return {
        "id": rev.id,
        "judgment_id": rev.judgment_id,
        "revision": rev.revision,
        "payload": json.dumps(rev.payload),
        "created_at": rev.created_at,
        "actor": rev.actor,
        "reason": rev.reason,
    }


def row_to_revision(row: Any) -> JudgmentRevision:
    get = row.__getitem__ if not isinstance(row, dict) else row.get
    return JudgmentRevision(
        id=get("id"),
        judgment_id=get("judgment_id"),
        revision=int(get("revision")),
        payload=_loads(get("payload"), {}),
        created_at=get("created_at"),
        actor=get("actor") or "user",
        reason=get("reason") or "",
    )


def proposal_to_row(p: JudgmentProposal) -> dict[str, Any]:
    return {
        "id": p.id,
        "action": p.action.value,
        "target_judgment_id": p.target_judgment_id,
        "expected_revision_id": p.expected_revision_id,
        "proposed_item": json.dumps(p.proposed_item),
        "reason": p.reason,
        "supporting_claim_ids": json.dumps(p.supporting_claim_ids),
        "contradicting_claim_ids": json.dumps(p.contradicting_claim_ids),
        "support_count": p.support_count,
        "contradiction_count": p.contradiction_count,
        "confidence": p.confidence,
        "scope": json.dumps(p.scope),
        "status": p.status.value,
        "created_at": p.created_at,
        "expires_at": p.expires_at,
        "preview_token": p.preview_token,
        "metadata": json.dumps(p.metadata),
    }


def row_to_proposal(row: Any) -> JudgmentProposal:
    get = row.__getitem__ if not isinstance(row, dict) else row.get
    keys = set(row.keys()) if hasattr(row, "keys") else set(row)
    return JudgmentProposal(
        id=get("id"),
        action=get("action"),
        target_judgment_id=get("target_judgment_id"),
        expected_revision_id=get("expected_revision_id") if "expected_revision_id" in keys else None,
        proposed_item=_loads(get("proposed_item"), {}),
        reason=get("reason") or "",
        supporting_claim_ids=_loads(get("supporting_claim_ids"), []),
        contradicting_claim_ids=_loads(get("contradicting_claim_ids"), []),
        support_count=int(get("support_count") or 0),
        contradiction_count=int(get("contradiction_count") or 0),
        confidence=float(get("confidence") or 0.5),
        scope=_loads(get("scope"), {}),
        status=get("status") or "pending",
        created_at=get("created_at") or "",
        expires_at=get("expires_at"),
        preview_token=get("preview_token"),
        metadata=_loads(get("metadata"), {}),
    )


def version_to_row(v: JudgmentVersion) -> dict[str, Any]:
    return {
        "id": v.id,
        "version": v.version,
        "created_at": v.created_at,
        "reason": v.reason,
        "parent_version_id": v.parent_version_id,
        "active": int(v.active),
        "revision_ids": json.dumps(v.revision_ids),
        "item_ids": json.dumps(v.item_ids),
        "actor": v.actor,
        "metadata": json.dumps(v.metadata),
    }


def row_to_version(row: Any) -> JudgmentVersion:
    get = row.__getitem__ if not isinstance(row, dict) else row.get
    keys = set(row.keys()) if hasattr(row, "keys") else set(row)
    active = get("active")
    return JudgmentVersion(
        id=get("id"),
        version=int(get("version")),
        created_at=get("created_at"),
        reason=get("reason") or "",
        parent_version_id=get("parent_version_id"),
        active=bool(active) if not isinstance(active, bool) else active,
        revision_ids=_loads(get("revision_ids"), []) if "revision_ids" in keys else [],
        item_ids=_loads(get("item_ids"), []),
        actor=get("actor") or "user",
        metadata=_loads(get("metadata"), {}),
    )


def snapshot_to_row(s: JudgmentSnapshot) -> dict[str, Any]:
    return {
        "id": s.id,
        "judgment_version_id": s.judgment_version_id,
        "item_ids": json.dumps(s.item_ids),
        "applied_revisions": json.dumps([a.model_dump(mode="json") for a in s.applied_revisions]),
        "target_domain": s.target_domain,
        "persona": s.persona,
        "task_profile": s.task_profile,
        "project_id": s.project_id,
        "audience": s.audience,
        "client": s.client,
        "project_stage": s.project_stage,
        "application_engine": s.application_engine,
        "created_at": s.created_at,
        "metadata": json.dumps(s.metadata),
    }


def row_to_snapshot(row: Any) -> JudgmentSnapshot:
    get = row.__getitem__ if not isinstance(row, dict) else row.get
    keys = set(row.keys()) if hasattr(row, "keys") else set(row)
    return JudgmentSnapshot(
        id=get("id"),
        judgment_version_id=get("judgment_version_id"),
        item_ids=_loads(get("item_ids"), []),
        applied_revisions=[
            AppliedRevisionRef(**a) for a in _loads(get("applied_revisions"), [])
        ] if "applied_revisions" in keys else [],
        target_domain=get("target_domain") or "technical",
        persona=get("persona") or "individual",
        task_profile=get("task_profile") or "general",
        project_id=get("project_id"),
        audience=get("audience") if "audience" in keys else None,
        client=get("client") if "client" in keys else None,
        project_stage=get("project_stage") if "project_stage" in keys else None,
        application_engine=(get("application_engine") if "application_engine" in keys else None) or "judgment-app-v2",
        created_at=get("created_at") or "",
        metadata=_loads(get("metadata"), {}),
    )


def conflict_to_row(c: JudgmentConflict) -> dict[str, Any]:
    return {
        "id": c.id,
        "judgment_id": c.judgment_id,
        "claim_ids": json.dumps(c.claim_ids),
        "other_judgment_id": c.other_judgment_id,
        "type": c.type.value,
        "confidence": c.confidence,
        "status": c.status.value,
        "suggested_resolution": c.suggested_resolution,
        "reason": c.reason,
        "created_at": c.created_at,
        "resolved_at": c.resolved_at,
        "resolution_operation_id": c.resolution_operation_id,
        "proposal_id": c.proposal_id,
        "analyzer_version": c.analyzer_version,
        "evidence_fingerprint": c.evidence_fingerprint,
        "metadata": json.dumps(c.metadata),
    }


def row_to_conflict(row: Any) -> JudgmentConflict:
    get = row.__getitem__ if not isinstance(row, dict) else row.get
    keys = set(row.keys()) if hasattr(row, "keys") else set(row)
    return JudgmentConflict(
        id=get("id"),
        judgment_id=get("judgment_id"),
        claim_ids=_loads(get("claim_ids"), []),
        other_judgment_id=get("other_judgment_id"),
        type=get("type"),
        confidence=float(get("confidence") or 0.5),
        status=get("status") or "open",
        suggested_resolution=get("suggested_resolution") or "",
        reason=get("reason") or "",
        created_at=get("created_at") or "",
        resolved_at=get("resolved_at"),
        resolution_operation_id=get("resolution_operation_id") if "resolution_operation_id" in keys else None,
        proposal_id=get("proposal_id") if "proposal_id" in keys else None,
        analyzer_version=(get("analyzer_version") if "analyzer_version" in keys else None) or "conflict-v1",
        evidence_fingerprint=(get("evidence_fingerprint") if "evidence_fingerprint" in keys else None) or "",
        metadata=_loads(get("metadata"), {}),
    )


def trace_to_row(t: JudgmentTrace) -> dict[str, Any]:
    return {
        "id": t.id,
        "query": t.query,
        "snapshot_id": t.snapshot_id,
        "applied_items": json.dumps([a.model_dump(mode="json") for a in t.applied_items]),
        "blocked_options": json.dumps(t.blocked_options),
        "exceptions_used": json.dumps(t.exceptions_used),
        "result": json.dumps(t.result),
        "created_at": t.created_at,
        "metadata": json.dumps(t.metadata),
    }


def row_to_trace(row: Any) -> JudgmentTrace:
    get = row.__getitem__ if not isinstance(row, dict) else row.get
    return JudgmentTrace(
        id=get("id"),
        query=get("query") or "",
        snapshot_id=get("snapshot_id"),
        applied_items=[AppliedJudgmentEffect(**a) for a in _loads(get("applied_items"), [])],
        blocked_options=_loads(get("blocked_options"), []),
        exceptions_used=_loads(get("exceptions_used"), []),
        result=_loads(get("result"), {}),
        created_at=get("created_at") or "",
        metadata=_loads(get("metadata"), {}),
    )


def item_payload(item: JudgmentItem) -> dict[str, Any]:
    """Frozen content for a revision (excludes mutable head pointers)."""
    data = item.model_dump(mode="json")
    data.pop("current_revision_id", None)
    return data
