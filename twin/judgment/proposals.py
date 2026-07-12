"""Judgment proposal engine — observe and propose, never constitute."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any, Optional

from .. import ids
from ..clock import now_iso
from ..memory.models import MemoryItem, MemoryStatus
from ..memory.store.base import MemoryStore
from .models import (
    DURABLE_KINDS,
    JudgmentItem,
    JudgmentKind,
    JudgmentProposal,
    JudgmentProvenance,
    JudgmentScope,
    JudgmentStability,
    JudgmentStatus,
    ProposalAction,
    ProposalStatus,
)
from .versions import create_version, supersede_item


_SIMPLICITY_RE = re.compile(
    r"simpli|reversib|manuten|maintenance|overengin|mvp|local.?first|"
    r"lock.?in|infrastruct|complex",
    re.I,
)


def propose_from_memory(
    store: MemoryStore,
    memory_id: str,
    *,
    kind: Optional[str] = None,
    statement: Optional[str] = None,
) -> JudgmentProposal:
    mem = store.get_memory(memory_id)
    if mem is None:
        raise ValueError(f"memory {memory_id} not found")
    if mem.status != MemoryStatus.confirmed and mem.status.value != "confirmed":
        raise ValueError("only confirmed memories can seed judgment proposals")

    # Twin-influenced decisions get reduced independence.
    twin_influenced = bool(
        (mem.payload or {}).get("judgment_influenced")
        or (mem.payload or {}).get("twin_assisted")
    )
    mapped_kind = kind or {
        "preference": "preference",
        "belief": "belief",
        "procedure": "heuristic",
        "constraint": "constraint",
        "decision": "heuristic",
    }.get(mem.type.value, "preference")

    item = {
        "kind": mapped_kind,
        "statement": statement or mem.summary,
        "description": f"Promoted from memory {mem.id}: {mem.title}",
        "domain": mem.domain,
        "strength": 0.55 if mapped_kind == "preference" else 0.7,
        "confidence": 0.9 if not twin_influenced else 0.55,
        "stability": "evolving",
        "scope": {"domains": [mem.domain], "projects": [mem.project_id] if mem.project_id else []},
        "provenance": {
            "memory_ids": [mem.id],
            "source": "promoted_memory",
            "twin_influenced": twin_influenced,
            "independence_weight": 0.4 if twin_influenced else 1.0,
        },
    }
    proposal = JudgmentProposal(
        id=ids.judgment_proposal_id(),
        action=ProposalAction.create,
        proposed_item=item,
        reason=f"Manual promotion of confirmed memory {mem.id}",
        supporting_memory_ids=[mem.id],
        support_count=1,
        confidence=float(item["confidence"]),
        scope={"domain": mem.domain, "projects": [mem.project_id] if mem.project_id else []},
        status=ProposalStatus.pending,
        created_at=now_iso(),
    )
    store.insert_judgment_proposal(proposal)
    return proposal


def propose_from_pattern(
    store: MemoryStore,
    *,
    domain: str = "technical",
    min_evidence: int = 3,
    min_projects: int = 2,
) -> list[JudgmentProposal]:
    """Detect repeated decision rationales → heuristic proposals.

    Twin-influenced memories count at reduced weight and never alone suffice.
    """
    decisions = [
        m for m in store.list_memories(type_="decision", status="confirmed", limit=2000)
        if m.domain == domain or domain == "any"
    ]
    # group by project for independence
    buckets: dict[str, list[MemoryItem]] = defaultdict(list)
    weighted: list[tuple[MemoryItem, float]] = []
    for m in decisions:
        weight = 0.4 if (m.payload or {}).get("judgment_influenced") else 1.0
        if weight < 1.0 and not any(
            not (x.payload or {}).get("judgment_influenced") for x in decisions
        ):
            continue
        weighted.append((m, weight))
        buckets[m.project_id or m.id].append(m)

    # simplicity / reversibility cluster
    cluster = [
        (m, w) for m, w in weighted
        if _SIMPLICITY_RE.search(f"{m.title} {m.summary}")
    ]
    projects = {m.project_id or m.id for m, _ in cluster}
    independent = sum(w for _, w in cluster)
    if len(cluster) < min_evidence or len(projects) < min_projects or independent < min_evidence:
        return []

    supporting = [m.id for m, _ in cluster]
    # find contradictions: decisions that chose complexity explicitly
    contradicting = [
        m.id for m in decisions
        if m.id not in supporting
        and re.search(r"microservice|neo4j|kubernetes|distributed", f"{m.title} {m.summary}", re.I)
    ]
    item = {
        "kind": JudgmentKind.heuristic.value,
        "statement": "Prefer operational simplicity and reversible choices during early project stages.",
        "description": (
            "Observed repeated confirmed decisions favoring simplicity, "
            "maintenance cost, and reversibility. Not a deep value claim."
        ),
        "domain": domain,
        "strength": 0.72,
        "confidence": min(0.85, 0.55 + 0.05 * independent),
        "stability": JudgmentStability.evolving.value,
        "scope": {
            "domains": [domain],
            "project_stages": ["prototype", "mvp"],
            "task_profiles": ["architecture", "planning"],
        },
        "provenance": {
            "memory_ids": supporting,
            "source": "repeated_behavior",
            "twin_influenced": False,
            "independence_weight": 1.0,
        },
    }
    proposal = JudgmentProposal(
        id=ids.judgment_proposal_id(),
        action=ProposalAction.create,
        proposed_item=item,
        reason=(
            f"Repeated confirmed decisions across {len(projects)} projects "
            f"favor operational simplicity (support={len(supporting)}, "
            f"contradictions={len(contradicting)})."
        ),
        supporting_memory_ids=supporting,
        contradicting_memory_ids=contradicting,
        support_count=len(supporting),
        contradiction_count=len(contradicting),
        confidence=float(item["confidence"]),
        scope={"domain": domain},
        status=ProposalStatus.pending,
        created_at=now_iso(),
    )
    store.insert_judgment_proposal(proposal)
    return [proposal]


def compute_proposal_preview_token(proposal: JudgmentProposal, *,
                                   active_version_id: Optional[str] = None) -> str:
    payload = {
        "id": proposal.id,
        "action": proposal.action.value if hasattr(proposal.action, "value") else proposal.action,
        "proposed_item": proposal.proposed_item,
        "supporting": sorted(proposal.supporting_memory_ids),
        "contradicting": sorted(proposal.contradicting_memory_ids),
        "confidence": proposal.confidence,
        "scope": proposal.scope,
        "status": proposal.status.value if hasattr(proposal.status, "value") else proposal.status,
        "active_version_id": active_version_id or "",
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def preview_proposal(store: MemoryStore, proposal_id: str) -> dict[str, Any]:
    proposal = store.get_judgment_proposal(proposal_id)
    if proposal is None:
        raise ValueError(f"proposal {proposal_id} not found")
    version = store.get_active_judgment_version()
    token = compute_proposal_preview_token(
        proposal, active_version_id=version.id if version else None,
    )
    store.update_judgment_proposal(proposal_id, preview_token=token)
    return {
        "proposal": proposal.model_dump(mode="json"),
        "preview_token": token,
        "active_version_id": version.id if version else None,
        "requires_human_approval": True,
        "durable": proposal.proposed_item.get("kind") in {k.value for k in DURABLE_KINDS},
    }


def approve_proposal(
    store: MemoryStore,
    proposal_id: str,
    *,
    preview_token: str,
    edits: Optional[dict[str, Any]] = None,
    actor: str = "user",
    confirm_constitutional: bool = False,
) -> dict[str, Any]:
    proposal = store.get_judgment_proposal(proposal_id)
    if proposal is None:
        raise ValueError(f"proposal {proposal_id} not found")
    if proposal.status != ProposalStatus.pending:
        raise ValueError(f"proposal is {proposal.status.value}, not pending")
    preview = preview_proposal(store, proposal_id)
    if not preview_token or preview_token != preview["preview_token"]:
        raise ValueError("preview_token_mismatch")

    item_data = dict(proposal.proposed_item)
    if edits:
        item_data.update(edits)
    kind = JudgmentKind(item_data["kind"])
    stability = JudgmentStability(item_data.get("stability", "evolving"))
    if stability == JudgmentStability.constitutional and not confirm_constitutional:
        raise ValueError(
            "constitutional judgment requires confirm_constitutional=True"
        )

    now = now_iso()
    scope_raw = item_data.get("scope") or {}
    scope = JudgmentScope(**scope_raw) if isinstance(scope_raw, dict) else JudgmentScope()
    prov_raw = item_data.get("provenance") or {}
    provenance = JudgmentProvenance(**prov_raw) if isinstance(prov_raw, dict) else JudgmentProvenance()

    new_item = JudgmentItem(
        id=ids.judgment_id(),
        kind=kind,
        statement=item_data["statement"],
        description=item_data.get("description", ""),
        domain=item_data.get("domain", "technical"),
        persona=item_data.get("persona", "individual"),
        scope=scope,
        strength=float(item_data.get("strength", 0.5)),
        confidence=float(item_data.get("confidence", proposal.confidence)),
        stability=stability,
        status=JudgmentStatus.active,
        created_at=now,
        updated_at=now,
        approved_at=now,
        approved_by=actor,
        provenance=provenance,
        valid_from=now,
    )

    if proposal.action == ProposalAction.supersede and proposal.target_judgment_id:
        supersede_item(
            store, proposal.target_judgment_id, new_item,
            actor=actor, reason=proposal.reason,
        )
    else:
        store.insert_judgment_item(new_item)
        create_version(
            store,
            reason=f"approved proposal {proposal_id}",
            actor=actor,
        )

    store.update_judgment_proposal(
        proposal_id, status=ProposalStatus.approved.value,
    )
    return {
        "proposal_id": proposal_id,
        "judgment_id": new_item.id,
        "status": "approved",
    }


def reject_proposal(store: MemoryStore, proposal_id: str, *, reason: str = "") -> JudgmentProposal:
    proposal = store.get_judgment_proposal(proposal_id)
    if proposal is None:
        raise ValueError(f"proposal {proposal_id} not found")
    store.update_judgment_proposal(
        proposal_id,
        status=ProposalStatus.rejected.value,
        metadata={**(proposal.metadata or {}), "reject_reason": reason},
    )
    return store.get_judgment_proposal(proposal_id)  # type: ignore[return-value]


def defer_proposal(store: MemoryStore, proposal_id: str) -> JudgmentProposal:
    store.update_judgment_proposal(proposal_id, status=ProposalStatus.deferred.value)
    return store.get_judgment_proposal(proposal_id)  # type: ignore[return-value]


def rank_proposals(proposals: list[JudgmentProposal]) -> list[JudgmentProposal]:
    return sorted(
        proposals,
        key=lambda p: (p.confidence, p.support_count, -p.contradiction_count),
        reverse=True,
    )
