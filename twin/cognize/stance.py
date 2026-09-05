"""Stance as public name for Judgment (alias layer)."""

from __future__ import annotations

from typing import Any, Optional

from twin.cognize.models import Stance, StanceStatus
from twin.cognize.stance_engine.models import (
    JudgmentItem,
    JudgmentProposal,
    JudgmentStability,
    JudgmentStatus,
)


def _lineage_from_mapping(raw: Any) -> tuple[list[str], list[str]]:
    nids: list[str] = []
    evid: list[str] = []
    if raw is None:
        return nids, evid
    if hasattr(raw, "narrative_ids"):
        nids.extend(str(x) for x in (raw.narrative_ids or []) if x)
        evid.extend(str(x) for x in (getattr(raw, "evidence_ids", None) or []) if x)
        return nids, evid
    if isinstance(raw, dict):
        nid = raw.get("narrative_id")
        if nid:
            nids.append(str(nid))
        nids.extend(str(x) for x in (raw.get("narrative_ids") or []) if x)
        evid.extend(str(x) for x in (raw.get("evidence_ids") or []) if x)
    return nids, evid


def _dedupe(ids: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for i in ids:
        if not i or i in seen:
            continue
        seen.add(i)
        out.append(i)
    return out


def stance_lineage(
    item: JudgmentItem | None = None,
    *,
    metadata: Optional[dict[str, Any]] = None,
    provenance: Any = None,
    proposed_item: Optional[dict[str, Any]] = None,
) -> tuple[list[str], list[str]]:
    nids: list[str] = []
    evid: list[str] = []
    meta = dict(metadata or {})
    if item is not None:
        meta.update(item.metadata or {})
        extra_n, extra_e = _lineage_from_mapping(item.provenance)
        nids.extend(extra_n)
        evid.extend(extra_e)
    nid = meta.get("narrative_id")
    if nid:
        nids.append(str(nid))
    extra_n, extra_e = _lineage_from_mapping(provenance)
    nids.extend(extra_n)
    evid.extend(extra_e)
    if proposed_item:
        extra_n, extra_e = _lineage_from_mapping(proposed_item.get("provenance"))
        nids.extend(extra_n)
        evid.extend(extra_e)
        if proposed_item.get("narrative_id"):
            nids.append(str(proposed_item["narrative_id"]))
    return _dedupe(nids), _dedupe(evid)


def judgment_to_stance(item: JudgmentItem, *, vault_id: str = "") -> Stance:
    status_map = {
        JudgmentStatus.candidate: StanceStatus.pending,
        JudgmentStatus.active: StanceStatus.active,
        JudgmentStatus.rejected: StanceStatus.deprecated,
        JudgmentStatus.superseded: StanceStatus.deprecated,
        JudgmentStatus.deprecated: StanceStatus.deprecated,
    }
    st = status_map.get(item.status, StanceStatus.pending)
    nids, evid = stance_lineage(item)
    return Stance(
        id=item.id,
        vault_id=vault_id,
        kind=item.kind.value if hasattr(item.kind, "value") else str(item.kind),
        statement=item.statement,
        status=st,
        strength=float(item.strength or 0.5),
        domain=item.domain or "",
        persona=item.persona or "",
        constitutional=item.stability is JudgmentStability.constitutional,
        narrative_ids=nids,
        evidence_ids=evid,
        created_at=item.created_at or "",
        updated_at=item.updated_at or "",
        metadata={"judgment_id": item.id, **(item.metadata or {})},
    )


def proposal_to_stance(proposal: JudgmentProposal, *, vault_id: str = "") -> Stance:
    item = proposal.proposed_item or {}
    nids, evid = stance_lineage(
        metadata=proposal.metadata,
        provenance=item.get("provenance") if isinstance(item, dict) else None,
        proposed_item=item if isinstance(item, dict) else None,
    )
    st_raw = proposal.status.value if hasattr(proposal.status, "value") else str(proposal.status)
    status = StanceStatus.pending
    if st_raw in ("approved", "applied"):
        status = StanceStatus.approved
    statement = ""
    if isinstance(item, dict):
        statement = str(item.get("statement") or "")
    if not statement:
        statement = str(proposal.reason or "Pending Stance")
    kind = "heuristic"
    if isinstance(item, dict) and item.get("kind"):
        kind = str(item.get("kind"))
    return Stance(
        id=proposal.id,
        vault_id=vault_id,
        kind=kind,
        statement=statement,
        status=status,
        strength=float((item or {}).get("strength") or 0.55) if isinstance(item, dict) else 0.55,
        domain=str((item or {}).get("domain") or "") if isinstance(item, dict) else "",
        persona=str((item or {}).get("persona") or "") if isinstance(item, dict) else "",
        narrative_ids=nids,
        evidence_ids=evid,
        created_at=proposal.created_at or "",
        updated_at=proposal.created_at or "",
        metadata={
            "proposal_id": proposal.id,
            **(proposal.metadata or {}),
        },
    )


def list_stances(store: Any, *, vault_id: str = "") -> list[Stance]:
    if not hasattr(store, "list_judgment_items"):
        return []
    items = store.list_judgment_items()
    return [judgment_to_stance(i, vault_id=vault_id) for i in items]


def list_pending_stance_proposals(store: Any, *, vault_id: str = "") -> list[Stance]:
    if not hasattr(store, "list_judgment_proposals"):
        return []
    try:
        props = store.list_judgment_proposals(status="pending", limit=500)
    except TypeError:
        props = store.list_judgment_proposals(limit=500)
    out = []
    for p in props or []:
        st = proposal_to_stance(p, vault_id=vault_id)
        out.append(st)
    return out
