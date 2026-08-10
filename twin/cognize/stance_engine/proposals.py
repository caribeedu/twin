"""Judgment proposal engine — observe and propose, never constitute."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

from twin import ids
from twin.clock import now_iso
from twin.store.models import StoreClaim, ClaimStatus
from twin.store.provenance import count_independent_sources, claim_source_keys
from twin.store.store.base import MemoryStore
from .models import (
    ACTIONS_REQUIRING_TARGET,
    DURABLE_KINDS,
    ExceptionEffect,
    JudgmentException,
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
from .revisions import commit_new_item, commit_new_revision
from .versions import create_version, supersede_item


_SIMPLICITY_RE = re.compile(
    r"simpli|reversib|manuten|maintenance|overengin|mvp|local.?first|"
    r"lock.?in|infrastruct|complex",
    re.I,
)


def propose_from_memory(
    store: MemoryStore,
    claim_id: str,
    *,
    kind: Optional[str] = None,
    statement: Optional[str] = None,
) -> JudgmentProposal:
    mem = store.get_claim(claim_id)
    if mem is None:
        raise ValueError(f"memory {claim_id} not found")
    if mem.status != ClaimStatus.confirmed and mem.status.value != "confirmed":
        raise ValueError("only confirmed memories can seed judgment proposals")

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
    independent = count_independent_sources(store, [mem])

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
            "claim_ids": [mem.id],
            "source": "promoted_memory",
            "twin_influenced": twin_influenced,
            "independence_weight": 0.4 if twin_influenced else 1.0,
            "independent_sources": independent,
            "memory_count": 1,
        },
    }
    proposal = JudgmentProposal(
        id=ids.judgment_proposal_id(),
        action=ProposalAction.create,
        proposed_item=item,
        reason=f"Manual promotion of confirmed memory {mem.id}",
        supporting_claim_ids=[mem.id],
        support_count=independent,
        confidence=float(item["confidence"]),
        scope={"domain": mem.domain, "projects": [mem.project_id] if mem.project_id else []},
        status=ProposalStatus.pending,
        created_at=now_iso(),
        metadata={"independent_sources": independent, "memory_count": 1},
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
    """Initial demonstrative detector: operational simplicity / reversibility cluster.

    Not a general-purpose pattern engine — see README.
    """
    decisions = [
        m for m in store.list_claims(type_="decision", status="confirmed", limit=2000)
        if m.domain == domain or domain == "any"
    ]
    weighted: list[tuple[StoreClaim, float]] = []
    for m in decisions:
        weight = 0.4 if (m.payload or {}).get("judgment_influenced") else 1.0
        if weight < 1.0 and not any(
            not (x.payload or {}).get("judgment_influenced") for x in decisions
        ):
            continue
        weighted.append((m, weight))

    cluster = [
        (m, w) for m, w in weighted
        if _SIMPLICITY_RE.search(f"{m.title} {m.summary}")
    ]
    projects = {m.project_id or m.id for m, _ in cluster}
    independent = sum(w for _, w in cluster)
    if len(cluster) < min_evidence or len(projects) < min_projects or independent < min_evidence:
        return []

    supporting = [m.id for m, _ in cluster]
    independent_sources = count_independent_sources(store, [m for m, _ in cluster])
    contradicting = [
        m.id for m in decisions
        if m.id not in supporting
        and re.search(r"microservice|neo4j|kubernetes|distributed", f"{m.title} {m.summary}", re.I)
        and not (m.payload or {}).get("judgment_influenced")
    ]
    item = {
        "kind": JudgmentKind.heuristic.value,
        "statement": "Prefer operational simplicity and reversible choices during early project stages.",
        "description": (
            "Observed repeated confirmed decisions favoring simplicity. "
            "Not a deep value claim. Detector: rationale_cluster/simplicity (demo)."
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
            "claim_ids": supporting,
            "source": "repeated_behavior",
            "twin_influenced": False,
            "independence_weight": 1.0,
            "independent_sources": independent_sources,
            "memory_count": len(supporting),
        },
    }
    proposal = JudgmentProposal(
        id=ids.judgment_proposal_id(),
        action=ProposalAction.create,
        proposed_item=item,
        reason=(
            f"[demo detector] Repeated decisions across {len(projects)} projects "
            f"favor operational simplicity ({independent_sources} independent "
            f"source(s) across {len(supporting)} memories, "
            f"contradictions={len(contradicting)})."
        ),
        supporting_claim_ids=supporting,
        contradicting_claim_ids=contradicting,
        support_count=independent_sources,
        contradiction_count=len(contradicting),
        confidence=float(item["confidence"]),
        scope={"domain": domain},
        status=ProposalStatus.pending,
        created_at=now_iso(),
        metadata={
            "detector": "simplicity_cluster_demo",
            "independent_sources": independent_sources,
            "memory_count": len(supporting),
        },
    )
    store.insert_judgment_proposal(proposal)
    return [proposal]


def _episode_confirmed_memories(
    store: MemoryStore, episode_id: str, *, limit: int = 2000,
) -> list[StoreClaim]:
    """Confirmed memories tied to an episode (typically from ``episode_reflect``)."""
    out: list[StoreClaim] = []
    for m in store.list_claims(status="confirmed", limit=limit):
        if (m.payload or {}).get("episode_id") == episode_id:
            out.append(m)
    return out


def propose_from_episode(
    store: MemoryStore,
    episode_id: str,
    *,
    domain: Optional[str] = None,
) -> Optional[JudgmentProposal]:
    """Seed a Judgment proposal from an episode's *confirmed* trajectory memories.

    Only fires when the episode already has human-confirmed memories (from
    reflect, or otherwise linked). Never confirms Judgment — produces a pending
    proposal for human approval. Returns ``None`` when there is nothing stable.
    """
    mems = _episode_confirmed_memories(store, episode_id)
    if not mems:
        return None
    # Prefer decision/belief trajectory claims from episode reflection.
    trajectory = [
        m for m in mems
        if (m.payload or {}).get("trajectory")
        or m.type.value in ("decision", "belief")
    ] or mems
    seed = max(trajectory, key=lambda m: m.confidence)
    dom = domain or seed.domain
    twin_influenced = bool(
        (seed.payload or {}).get("twin_influenced")
        or (seed.payload or {}).get("judgment_influenced")
    )
    claim_ids = [m.id for m in trajectory]
    # Support = distinct *independent sources*, not memory rows. Several claims
    # from one episode share one source (episode:<id>); a cross-sense corroboration
    # (Slack symptom for a GitHub fix) adds a genuine second source. This keeps
    # "2 supports from 1 episode" honest as one source with humble confidence.
    independent = count_independent_sources(store, trajectory)
    item = {
        "kind": JudgmentKind.heuristic.value,
        "statement": seed.summary or seed.title,
        "description": (
            f"Generalized from the confirmed trajectory of episode {episode_id}: "
            f"{seed.title}. Detector: episode_pattern. "
            f"Independent sources: {independent} (from {len(claim_ids)} memories)."
        ),
        "domain": dom,
        "strength": 0.6,
        "confidence": min(0.8, 0.5 + 0.05 * independent) if not twin_influenced else 0.55,
        "stability": JudgmentStability.evolving.value,
        "scope": {
            "domains": [dom],
            "projects": [seed.project_id] if seed.project_id else [],
        },
        "provenance": {
            "claim_ids": claim_ids,
            "source": "episode_pattern",
            "twin_influenced": twin_influenced,
            "independence_weight": 0.4 if twin_influenced else 1.0,
            "independent_sources": independent,
            "memory_count": len(claim_ids),
        },
    }
    proposal = JudgmentProposal(
        id=ids.judgment_proposal_id(),
        action=ProposalAction.create,
        proposed_item=item,
        reason=(
            f"Confirmed trajectory of episode {episode_id} "
            f"({independent} independent source(s) across {len(claim_ids)} "
            f"memories) suggests a durable heuristic."
        ),
        supporting_claim_ids=claim_ids,
        support_count=independent,
        confidence=float(item["confidence"]),
        scope={"domain": dom},
        status=ProposalStatus.pending,
        created_at=now_iso(),
        metadata={
            "detector": "episode_pattern",
            "episode_id": episode_id,
            "independent_sources": independent,
            "memory_count": len(claim_ids),
        },
    )
    store.insert_judgment_proposal(proposal)
    return proposal


def propose_from_narrative(
    store: MemoryStore,
    narrative_id: str,
    *,
    domain: Optional[str] = None,
    statement: Optional[str] = None,
) -> Optional[JudgmentProposal]:
    """Draft a pending Stance/Judgment from a committed Narrative. Never auto-approves."""
    if not hasattr(store, "get_narrative"):
        return None
    nar = store.get_narrative(narrative_id)
    if nar is None:
        raise ValueError(f"narrative {narrative_id} not found")
    dom = domain or nar.domain or "technical"
    text = (statement or nar.account or "").strip()
    if not text:
        return None
    item = {
        "kind": JudgmentKind.heuristic.value,
        "statement": text[:500],
        "description": (
            f"Drafted from committed Narrative {narrative_id}. "
            "Detector: narrative_stance. Pending human approve."
        ),
        "domain": dom,
        "strength": 0.55,
        "confidence": 0.55,
        "stability": JudgmentStability.evolving.value,
        "scope": {
            "domains": [dom],
            "projects": [nar.project_id] if nar.project_id else [],
        },
        "provenance": {
            "claim_ids": [],
            "source": "narrative_stance",
            "twin_influenced": True,
            "independence_weight": 0.4,
            "narrative_id": narrative_id,
        },
    }
    proposal = JudgmentProposal(
        id=ids.judgment_proposal_id(),
        action=ProposalAction.create,
        proposed_item=item,
        reason=f"Committed Narrative {narrative_id} suggests a durable evaluative stance.",
        supporting_claim_ids=[],
        support_count=1,
        confidence=0.55,
        scope={"domain": dom},
        status=ProposalStatus.pending,
        created_at=now_iso(),
        metadata={
            "detector": "narrative_stance",
            "narrative_id": narrative_id,
        },
    )
    store.insert_judgment_proposal(proposal)
    return proposal


def propose_from_episode_patterns(
    store: MemoryStore,
    *,
    domain: str = "technical",
    min_evidence: int = 2,
    min_episodes: int = 2,
) -> list[JudgmentProposal]:
    """Scan confirmed trajectory memories across episodes for a stable pattern.

    Complements :func:`propose_from_pattern`; restricted to ``episode_reflect``
    trajectory decisions so it only generalizes cross-source arcs a human has
    confirmed. Returns pending proposals (never confirms Judgment).
    """
    trajectory = [
        m for m in store.list_claims(
            type_="decision", status="confirmed", limit=2000,
        )
        if (m.payload or {}).get("source") == "episode_reflect"
        and (domain == "any" or m.domain == domain)
    ]
    episodes = {
        (m.payload or {}).get("episode_id") for m in trajectory
        if (m.payload or {}).get("episode_id")
    }
    if len(trajectory) < min_evidence or len(episodes) < min_episodes:
        return []
    supporting = [m.id for m in trajectory]
    independent = count_independent_sources(store, trajectory)
    item = {
        "kind": JudgmentKind.heuristic.value,
        "statement": (
            "Reconsiders early technical approaches when a simpler or more "
            "reversible option emerges, rather than committing to the first choice."
        ),
        "description": (
            f"Observed across {len(episodes)} episodes with confirmed pivots. "
            "Detector: episode_pattern (trajectory cluster). "
            f"Independent sources: {independent} (from {len(supporting)} memories)."
        ),
        "domain": domain,
        "strength": 0.6,
        "confidence": min(0.8, 0.5 + 0.05 * independent),
        "stability": JudgmentStability.evolving.value,
        "scope": {"domains": [domain], "task_profiles": ["architecture", "planning"]},
        "provenance": {
            "claim_ids": supporting,
            "source": "episode_pattern",
            "twin_influenced": False,
            "independence_weight": 1.0,
            "independent_sources": independent,
            "memory_count": len(supporting),
        },
    }
    proposal = JudgmentProposal(
        id=ids.judgment_proposal_id(),
        action=ProposalAction.create,
        proposed_item=item,
        reason=(
            f"[episode_pattern] Confirmed trajectory pivots across "
            f"{len(episodes)} episodes ({independent} independent source(s))."
        ),
        supporting_claim_ids=supporting,
        support_count=independent,
        confidence=float(item["confidence"]),
        scope={"domain": domain},
        status=ProposalStatus.pending,
        created_at=now_iso(),
        metadata={
            "detector": "episode_pattern",
            "independent_sources": independent,
            "memory_count": len(supporting),
        },
    )
    store.insert_judgment_proposal(proposal)
    return [proposal]


def _memory_fingerprint(store: MemoryStore, claim_id: str) -> dict[str, Any]:
    m = store.get_claim(claim_id)
    if m is None:
        return {"id": claim_id, "missing": True}
    content_hash = hashlib.sha256(f"{m.title}\n{m.summary}".encode()).hexdigest()[:16]
    evidence = store.get_evidence(claim_id) if hasattr(store, "get_evidence") else []
    ev_fp = hashlib.sha256(
        "|".join(sorted(f"{e.id}:{e.quote[:40]}" for e in evidence)).encode()
    ).hexdigest()[:16] if evidence else ""
    # Independent sources behind this one memory (episode / sense / lineage).
    sources = sorted(claim_source_keys(store, m))
    return {
        "id": m.id,
        "title": m.title,
        "type": m.type.value if hasattr(m.type, "value") else str(m.type),
        "updated_at": m.updated_at or "",
        "status": m.status.value if hasattr(m.status, "value") else str(m.status),
        "content_hash": content_hash,
        "confidence": m.confidence,
        "evidence_fingerprint": ev_fp,
        "independent_sources": sources,
    }


def merge_proposed_item(proposal: JudgmentProposal, edits: Optional[dict[str, Any]]) -> dict[str, Any]:
    final = dict(proposal.proposed_item or {})
    if edits:
        final.update(edits)
    return final


def compute_proposal_preview_token(
    store: MemoryStore,
    proposal: JudgmentProposal,
    *,
    edits: Optional[dict[str, Any]] = None,
    active_version_id: Optional[str] = None,
) -> tuple[str, dict[str, Any]]:
    final_item = merge_proposed_item(proposal, edits)
    supporting = [_memory_fingerprint(store, mid) for mid in proposal.supporting_claim_ids]
    contradicting = [_memory_fingerprint(store, mid) for mid in proposal.contradicting_claim_ids]
    # Honest support: distinct independent sources behind the supporting memories.
    independent_sources = count_independent_sources(store, proposal.supporting_claim_ids)
    target_rev = None
    target_stability = None
    target_snapshot: Optional[dict[str, Any]] = None
    if proposal.target_judgment_id:
        target = store.get_judgment_item(proposal.target_judgment_id)
        if target:
            target_rev = target.current_revision_id
            target_stability = target.stability.value
            target_snapshot = {
                "stability": target.stability.value,
                "kind": target.kind.value,
                "domain": target.domain,
                "persona": target.persona,
                "strength": target.strength,
                "confidence": target.confidence,
            }
    new_stability = final_item.get("stability", target_stability)
    payload = {
        "id": proposal.id,
        "action": proposal.action.value if hasattr(proposal.action, "value") else proposal.action,
        "proposed_item": proposal.proposed_item,
        "edits": edits or {},
        "final_item": final_item,
        "supporting": supporting,
        "contradicting": contradicting,
        "support_count": proposal.support_count,
        "independent_sources": independent_sources,
        "memory_count": len(proposal.supporting_claim_ids),
        "confidence": proposal.confidence,
        "scope": proposal.scope,
        "status": proposal.status.value if hasattr(proposal.status, "value") else proposal.status,
        "active_version_id": active_version_id or "",
        "target_judgment_id": proposal.target_judgment_id,
        "expected_revision_id": proposal.expected_revision_id or target_rev,
        "target_stability": target_stability,
        "target_snapshot": target_snapshot,
        "new_stability": new_stability,
        "stability_change": (
            target_stability is not None
            and new_stability is not None
            and str(new_stability) != str(target_stability)
        ),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:24], payload


def preview_proposal(
    store: MemoryStore,
    proposal_id: str,
    *,
    edits: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    proposal = store.get_judgment_proposal(proposal_id)
    if proposal is None:
        raise ValueError(f"proposal {proposal_id} not found")
    version = store.get_active_judgment_version()
    token, signed = compute_proposal_preview_token(
        store, proposal, edits=edits,
        active_version_id=version.id if version else None,
    )
    store.update_judgment_proposal(
        proposal_id,
        preview_token=token,
        metadata={**(proposal.metadata or {}), "last_preview": signed},
    )
    return {
        "proposal": proposal.model_dump(mode="json"),
        "edits": edits or {},
        "final_item": signed["final_item"],
        "preview_token": token,
        "signed_payload": signed,
        "active_version_id": version.id if version else None,
        "requires_human_approval": True,
        "durable": signed["final_item"].get("kind") in {k.value for k in DURABLE_KINDS},
    }


# Patchable content fields for update. Absent key → preserve; present → apply
# (including empty list / None where allowed). Lifecycle fields are excluded.
MUTABLE_JUDGMENT_FIELDS = frozenset({
    "kind", "statement", "description", "domain", "persona", "scope",
    "strength", "confidence", "stability", "valid_from", "valid_until",
    "provenance", "exceptions", "conflicts_with", "tradeoff", "lean", "metadata",
})

LIFECYCLE_IMMUTABLE_FIELDS = frozenset({
    "id", "revision", "current_revision_id", "created_at",
    "approved_at", "approved_by", "supersedes", "status", "updated_at",
})


def _build_item_from_final(final: dict[str, Any], *, actor: str) -> JudgmentItem:
    now = now_iso()
    scope_raw = final.get("scope") or {}
    scope = JudgmentScope(**scope_raw) if isinstance(scope_raw, dict) else JudgmentScope()
    prov_raw = final.get("provenance") or {}
    provenance = JudgmentProvenance(**prov_raw) if isinstance(prov_raw, dict) else JudgmentProvenance()
    exceptions = [
        JudgmentException(**e) if isinstance(e, dict) else e
        for e in (final.get("exceptions") or [])
    ]
    return JudgmentItem(
        id=final.get("id") or ids.judgment_id(),
        kind=JudgmentKind(final["kind"]),
        statement=final["statement"],
        description=final.get("description", ""),
        domain=final.get("domain", "technical"),
        persona=final.get("persona", "individual"),
        scope=scope,
        strength=float(final.get("strength", 0.5)),
        confidence=float(final.get("confidence", 0.5)),
        stability=JudgmentStability(final.get("stability", "evolving")),
        status=JudgmentStatus.active,
        created_at=now,
        updated_at=now,
        approved_at=now,
        approved_by=actor,
        provenance=provenance,
        exceptions=exceptions,
        valid_from=now,
    )


def _normalize_patch_value(key: str, value: Any) -> Any:
    if key == "kind":
        return JudgmentKind(value)
    if key == "stability":
        return JudgmentStability(value)
    if key == "scope":
        if isinstance(value, JudgmentScope):
            return value
        return JudgmentScope(**(value or {}))
    if key == "provenance":
        if isinstance(value, JudgmentProvenance):
            return value
        return JudgmentProvenance(**(value or {}))
    if key == "exceptions":
        out: list[JudgmentException] = []
        for e in value or []:
            if isinstance(e, JudgmentException):
                out.append(e)
            else:
                raw = dict(e)
                if "id" not in raw:
                    raw["id"] = ids.judgment_exception_id()
                out.append(JudgmentException(**raw))
        return out
    if key in ("strength", "confidence") and value is not None:
        return float(value)
    if key == "lean" and value is not None:
        return float(value)
    return value


def apply_judgment_patch(target: JudgmentItem, final: dict[str, Any]) -> JudgmentItem:
    """Apply only keys present in ``final`` onto a copy of ``target``.

    Absent keys are preserved. Explicit empty values (e.g. ``exceptions: []``)
    clear the field. Lifecycle identity fields are never taken from the patch.
    """
    nxt = target.model_copy(deep=True)
    for key, value in final.items():
        if key in LIFECYCLE_IMMUTABLE_FIELDS:
            continue
        if key not in MUTABLE_JUDGMENT_FIELDS:
            continue
        setattr(nxt, key, _normalize_patch_value(key, value))
    return nxt


def _require_constitutional_confirm(
    *,
    target: Optional[JudgmentItem],
    final: dict[str, Any],
    confirm_constitutional: bool,
) -> None:
    """Block constitutional create/mutate unless explicitly confirmed."""
    if confirm_constitutional:
        return
    final_stability = final.get("stability")
    if final_stability == JudgmentStability.constitutional.value or (
        isinstance(final_stability, JudgmentStability)
        and final_stability == JudgmentStability.constitutional
    ):
        raise ValueError(
            "constitutional judgment requires confirm_constitutional=True"
        )
    if target is not None and target.stability == JudgmentStability.constitutional:
        raise ValueError(
            "changing a constitutional judgment requires confirm_constitutional=True"
        )


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

    version = store.get_active_judgment_version()
    token, signed = compute_proposal_preview_token(
        store, proposal, edits=edits,
        active_version_id=version.id if version else None,
    )
    if not preview_token or preview_token != token:
        raise ValueError("preview_token_mismatch")

    final = signed["final_item"]
    action = proposal.action if isinstance(proposal.action, ProposalAction) else ProposalAction(proposal.action)
    if action in ACTIONS_REQUIRING_TARGET and not proposal.target_judgment_id:
        raise ValueError(f"action {action.value} requires target_judgment_id")

    target = None
    if proposal.target_judgment_id:
        target = store.get_judgment_item(proposal.target_judgment_id)
        if target is None and action in ACTIONS_REQUIRING_TARGET:
            raise ValueError(f"target judgment {proposal.target_judgment_id} not found")

    _require_constitutional_confirm(
        target=target if action != ProposalAction.create else None,
        final=final,
        confirm_constitutional=confirm_constitutional,
    )

    with store.transaction():
        result = _dispatch_action(
            store, proposal, action, final, actor=actor,
            confirm_constitutional=confirm_constitutional,
            expected_parent_version_id=version.id if version else None,
        )
        store.update_judgment_proposal(proposal_id, status=ProposalStatus.approved.value)
    return result


def _dispatch_action(
    store: MemoryStore,
    proposal: JudgmentProposal,
    action: ProposalAction,
    final: dict[str, Any],
    *,
    actor: str,
    confirm_constitutional: bool,
    expected_parent_version_id: Optional[str],
) -> dict[str, Any]:
    if action == ProposalAction.create:
        item = _build_item_from_final(final, actor=actor)
        item, rev = commit_new_item(store, item, actor=actor, reason=proposal.reason)
        version = create_version(
            store, reason=f"approved proposal {proposal.id}",
            actor=actor, expected_parent_version_id=expected_parent_version_id,
        )
        return {"proposal_id": proposal.id, "judgment_id": item.id,
                "revision_id": rev.id, "version_id": version.id, "status": "approved",
                "action": action.value}

    target = store.get_judgment_item(proposal.target_judgment_id)  # type: ignore[arg-type]
    if target is None:
        raise ValueError(f"target judgment {proposal.target_judgment_id} not found")
    if proposal.expected_revision_id and target.current_revision_id != proposal.expected_revision_id:
        raise ValueError("target revision changed since proposal was created")

    # Defense in depth — also enforced in approve_proposal before the transaction.
    _require_constitutional_confirm(
        target=target, final=final, confirm_constitutional=confirm_constitutional,
    )

    if action == ProposalAction.supersede:
        new_item = _build_item_from_final(final, actor=actor)
        item, version = supersede_item(
            store, target.id, new_item, actor=actor, reason=proposal.reason,
            confirm_constitutional=confirm_constitutional,
            expected_parent_version_id=expected_parent_version_id,
        )
        return {"proposal_id": proposal.id, "judgment_id": item.id,
                "revision_id": item.current_revision_id, "version_id": version.id,
                "status": "approved", "action": action.value}

    nxt = target.model_copy(deep=True)
    if action == ProposalAction.update:
        nxt = apply_judgment_patch(target, final)
    elif action == ProposalAction.weaken:
        nxt.strength = min(nxt.strength, float(final.get("strength", max(0.0, nxt.strength - 0.15))))
        if "statement" in final:
            nxt.statement = final["statement"]
    elif action == ProposalAction.strengthen:
        nxt.strength = max(nxt.strength, float(final.get("strength", min(1.0, nxt.strength + 0.15))))
    elif action == ProposalAction.add_exception:
        raw_exc = final.get("exception") or final.get("exceptions")
        if isinstance(raw_exc, list):
            for e in raw_exc:
                nxt.exceptions.append(JudgmentException(**e) if isinstance(e, dict) else e)
        elif isinstance(raw_exc, dict):
            if "id" not in raw_exc:
                raw_exc = {**raw_exc, "id": ids.judgment_exception_id()}
            nxt.exceptions.append(JudgmentException(**raw_exc))
        else:
            raise ValueError("add_exception requires exception or exceptions in final item")
    elif action == ProposalAction.deprecate:
        nxt.status = JudgmentStatus.deprecated
        nxt.valid_until = now_iso()
    else:
        raise ValueError(f"unsupported action: {action}")

    nxt.approved_at = now_iso()
    nxt.approved_by = actor
    item, rev = commit_new_revision(store, nxt, actor=actor, reason=f"{action.value}: {proposal.reason}")
    version = create_version(
        store, reason=f"approved proposal {proposal.id} ({action.value})",
        actor=actor, expected_parent_version_id=expected_parent_version_id,
    )
    return {
        "proposal_id": proposal.id,
        "judgment_id": item.id,
        "revision_id": rev.id,
        "version_id": version.id,
        "status": "approved",
        "action": action.value,
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
