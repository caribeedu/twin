"""Memory Quality Analyzer — neighborhood discovery, findings, priority.

Turns individual candidate review into reconciled-knowledge curation:

    candidate → neighborhood → quality analysis → priority → action
"""

from __future__ import annotations

import re
from typing import Optional

from .. import ids
from ..clock import now_iso
from ..memory.embeddings import Embedder
from ..memory.models import (
    FindingType,
    INACTIVE_STATUSES,
    MemoryItem,
    QualityReport,
    ReviewFinding,
    SuggestedAction,
)
from ..memory.store.base import MemoryStore

NEAR_DUP = 0.88
RELATED = 0.75
CONFLICT_HINTS = (
    ("uses ", "uses "),
    ("is ", "is not "),
    ("prefer", "prefer"),
)

HIGH_IMPACT_TYPES = frozenset({"decision", "constraint", "belief"})
SENSITIVITY_WEIGHT = {
    "public": 0.3,
    "internal": 0.5,
    "private": 0.8,
    "restricted": 1.0,
}


def discover_neighbors(
    store: MemoryStore,
    embedder: Embedder,
    mem: MemoryItem,
    *,
    limit: int = 12,
) -> list[tuple[MemoryItem, float, str]]:
    """Return (neighbor, score, reason) for related memories."""
    text = f"{mem.title}\n{mem.summary}"
    vector = embedder.embed(text)
    scored: dict[str, tuple[float, str]] = {}

    for ref_id, sim in store.similar(vector, "memory", embedder.name, min_sim=RELATED).items():
        if ref_id == mem.id:
            continue
        other = store.get_memory(ref_id)
        if other is None or other.status.value in INACTIVE_STATUSES:
            continue
        scored[ref_id] = (sim, "semantic")

    # same entities
    for name in mem.entities:
        ent = store.get_entity_by_name(name)
        if ent is None:
            continue
        for other in store.memories_for_entity(ent.id):
            if other.id == mem.id or other.status.value in INACTIVE_STATUSES:
                continue
            prev = scored.get(other.id, (0.0, ""))
            scored[other.id] = (max(prev[0], 0.55), "entity" if prev[0] < 0.55 else prev[1])

    # same project / type
    for other in store.list_memories(project_id=mem.project_id, type_=mem.type.value, limit=80):
        if other.id == mem.id or other.status.value in INACTIVE_STATUSES:
            continue
        if mem.project_id and other.project_id == mem.project_id:
            prev = scored.get(other.id, (0.0, ""))
            if prev[0] < 0.4:
                scored[other.id] = (0.4, "project")

    # existing conflict / supersede / related edges
    for rel in store.relations_for(mem.id):
        other_id = rel.object_id if rel.subject_id == mem.id else rel.subject_id
        if other_id == mem.id:
            continue
        other = store.get_memory(other_id)
        if other is None:
            continue
        boost = 0.95 if rel.predicate in ("contradicts", "supersedes") else 0.7
        prev = scored.get(other_id, (0.0, ""))
        scored[other_id] = (max(prev[0], boost), rel.predicate)

    ranked = sorted(scored.items(), key=lambda kv: kv[1][0], reverse=True)[:limit]
    out: list[tuple[MemoryItem, float, str]] = []
    for mid, (score, reason) in ranked:
        other = store.get_memory(mid)
        if other:
            out.append((other, score, reason))
    return out


def _specificity(mem: MemoryItem) -> float:
    words = len(mem.summary.split())
    if words < 6:
        return 0.25
    if words < 12:
        return 0.5
    # compound / under-fragmented: many "and"/commas with multiple tech tokens
    conjunctions = len(re.findall(r"\b(and|,|;)\b", mem.summary, flags=re.I))
    if conjunctions >= 3 and words > 20:
        return 0.35  # likely needs split
    return min(1.0, 0.55 + words / 40)


def _looks_conflict(a: MemoryItem, b: MemoryItem) -> bool:
    if a.type.value != b.type.value:
        return False
    ta, tb = a.summary.lower(), b.summary.lower()
    shared = set(x.lower() for x in a.entities) & set(x.lower() for x in b.entities)
    if not shared and a.project_id and a.project_id == b.project_id:
        shared = {"project"}
    if not shared:
        return False
    if _scope_difference(a, b):
        return False
    neg_a = bool(re.search(r"\b(not|never|no longer|instead of)\b", ta))
    neg_b = bool(re.search(r"\b(not|never|no longer|instead of)\b", tb))
    if neg_a != neg_b:
        return True
    if "uses" in ta and "uses" in tb and ta != tb:
        return True
    if a.type.value in HIGH_IMPACT_TYPES and ta != tb:
        return True
    return False


def _scope_difference(a: MemoryItem, b: MemoryItem) -> bool:
    scopes = ("development", "production", "dev", "prod", "local", "staging", "test")
    sa = {s for s in scopes if s in a.summary.lower()}
    sb = {s for s in scopes if s in b.summary.lower()}
    return bool(sa and sb and sa != sb)


def review_priority(
    mem: MemoryItem,
    *,
    contradiction_risk: float = 0.0,
    source_risk: float = 0.0,
    future_reuse: float = 0.0,
) -> float:
    """priority = impact × uncertainty × contradiction × sensitivity × reuse × source × staleness."""
    impact = {"low": 0.4, "medium": 0.7, "high": 1.0}.get(mem.impact, 0.7)
    if mem.type.value in HIGH_IMPACT_TYPES:
        impact = max(impact, 0.9)
    uncertainty = max(0.15, 1.0 - mem.confidence)
    sensitivity = SENSITIVITY_WEIGHT.get(mem.sensitivity.value, 0.5)
    staleness = 0.6
    if mem.status.value == "candidate" and mem.needs_review:
        staleness = 0.85
    reuse = max(0.2, min(1.0, 0.3 + future_reuse + min(mem.retrieval_count, 20) / 20))
    src = max(0.2, source_risk) if source_risk else 0.4
    contradiction = max(0.2, contradiction_risk) if contradiction_risk else 0.25
    score = impact * uncertainty * contradiction * sensitivity * reuse * src * staleness
    # normalize roughly into 0..1
    return round(min(1.0, score * 3.2), 4)


def analyze_memory(
    store: MemoryStore,
    embedder: Embedder,
    memory_id: str,
    *,
    persist: bool = True,
) -> QualityReport:
    mem = store.get_memory(memory_id)
    if mem is None:
        raise ValueError(f"memory {memory_id} not found")

    neighbors = discover_neighbors(store, embedder, mem)
    findings: list[ReviewFinding] = []
    flags: list[str] = []
    contradiction_risk = 0.0
    suggested = SuggestedAction.none
    requires_human = False
    ts = now_iso()

    evidence = store.get_evidence(mem.id)
    if not evidence:
        findings.append(ReviewFinding(
            id=ids.finding_id(), memory_id=mem.id, type=FindingType.weak_evidence,
            confidence=0.9, reason="no evidence attached",
            suggested_action=SuggestedAction.request_more_evidence,
            requires_human_review=True, created_at=ts,
        ))
        flags.append("weak_evidence")
        requires_human = True
        suggested = SuggestedAction.request_more_evidence

    spec = _specificity(mem)
    if spec < 0.4:
        split_likely = len(re.findall(r"\b(and|,)\b", mem.summary, flags=re.I)) >= 3
        ftype = FindingType.possible_split if split_likely else FindingType.low_specificity
        findings.append(ReviewFinding(
            id=ids.finding_id(), memory_id=mem.id, type=ftype,
            confidence=0.7, reason="summary is generic or compound",
            suggested_action=SuggestedAction.split if split_likely else SuggestedAction.edit,
            requires_human_review=True, created_at=ts,
        ))
        flags.append(ftype.value)
        requires_human = True
        if split_likely:
            suggested = SuggestedAction.split

    for other, sim, reason in neighbors:
        if sim >= 0.98 and mem.title.strip().lower() == other.title.strip().lower():
            findings.append(ReviewFinding(
                id=ids.finding_id(), memory_id=mem.id, type=FindingType.exact_duplicate,
                related_memory_id=other.id, confidence=sim,
                reason=f"exact/near-identical content ({reason})",
                suggested_action=SuggestedAction.reject,
                requires_human_review=False, created_at=ts,
            ))
            flags.append("exact_duplicate")
            suggested = SuggestedAction.reject
            continue

        if sim >= NEAR_DUP:
            findings.append(ReviewFinding(
                id=ids.finding_id(), memory_id=mem.id, type=FindingType.near_duplicate,
                related_memory_id=other.id, confidence=sim,
                reason=f"near-duplicate via {reason}",
                suggested_action=SuggestedAction.merge,
                requires_human_review=True, created_at=ts,
            ))
            flags.append("near_duplicate")
            requires_human = True
            suggested = SuggestedAction.merge
            continue

        if sim >= RELATED and _scope_difference(mem, other):
            findings.append(ReviewFinding(
                id=ids.finding_id(), memory_id=mem.id, type=FindingType.scope_difference,
                related_memory_id=other.id, confidence=0.7,
                reason="similar claim with different scope — may coexist",
                suggested_action=SuggestedAction.confirm,
                requires_human_review=False, created_at=ts,
            ))
            flags.append("scope_difference")
            continue

        if sim >= RELATED and _looks_conflict(mem, other):
            # newer decision may supersede older
            if (mem.type.value == "decision" and other.type.value == "decision"
                    and (mem.valid_from or mem.created_at) > (other.valid_from or other.created_at)):
                findings.append(ReviewFinding(
                    id=ids.finding_id(), memory_id=mem.id,
                    type=FindingType.possible_supersedence,
                    related_memory_id=other.id, confidence=min(0.95, sim + 0.05),
                    reason="newer decision may supersede older",
                    suggested_action=SuggestedAction.supersede,
                    requires_human_review=True, created_at=ts,
                ))
                flags.append("possible_supersedence")
                suggested = SuggestedAction.supersede
            else:
                findings.append(ReviewFinding(
                    id=ids.finding_id(), memory_id=mem.id,
                    type=FindingType.possible_conflict,
                    related_memory_id=other.id, confidence=sim,
                    reason="possible logical conflict with related memory",
                    suggested_action=SuggestedAction.contradict,
                    requires_human_review=True, created_at=ts,
                ))
                flags.append("possible_conflict")
                suggested = SuggestedAction.contradict
            contradiction_risk = max(contradiction_risk, sim)
            requires_human = True

        if sim >= RELATED and sim < NEAR_DUP and FindingType.possible_merge.value not in flags:
            if mem.type.value == other.type.value and mem.project_id == other.project_id:
                findings.append(ReviewFinding(
                    id=ids.finding_id(), memory_id=mem.id, type=FindingType.possible_merge,
                    related_memory_id=other.id, confidence=sim,
                    reason="paraphrase candidates — merge or corroborate",
                    suggested_action=SuggestedAction.merge,
                    requires_human_review=True, created_at=ts,
                ))
                flags.append("possible_merge")
                requires_human = True

    if mem.retrieval_count >= 3:
        flags.append("high_future_reuse")

    impact = mem.impact
    if mem.type.value in HIGH_IMPACT_TYPES or mem.sensitivity.value in ("private", "restricted"):
        impact = "high"
        requires_human = True

    priority = review_priority(
        mem.model_copy(update={"impact": impact}),
        contradiction_risk=contradiction_risk or (0.9 if "possible_conflict" in flags else 0.0),
        source_risk=0.7 if mem.confidence < 0.5 else 0.35,
        future_reuse=1.0 if "high_future_reuse" in flags else 0.3,
    )
    # quality: higher when specific, evidenced, low conflict
    quality = round(
        0.35 * spec
        + 0.35 * (1.0 if evidence else 0.2)
        + 0.15 * mem.confidence
        + 0.15 * (1.0 - contradiction_risk),
        3,
    )

    if mem.type.value in ("belief",) or mem.sensitivity.value in ("private", "restricted"):
        requires_human = True

    report = QualityReport(
        memory_id=mem.id,
        quality_score=quality,
        review_priority=priority,
        impact=impact,
        issues=findings,
        suggested_action=suggested,
        requires_human_review=requires_human or mem.needs_review,
        quality_flags=sorted(set(flags)),
        neighbors=[n.id for n, _, _ in neighbors],
    )

    if persist:
        store.update_memory(
            mem.id,
            review_priority=priority,
            quality_score=quality,
            quality_flags=report.quality_flags,
            impact=impact,
            needs_review=report.requires_human_review or mem.needs_review,
            review_reason=mem.review_reason or (
                findings[0].reason if findings else None
            ),
            last_reconciled_at=ts,
        )
        if hasattr(store, "replace_findings"):
            store.replace_findings(mem.id, findings)  # type: ignore[attr-defined]
        elif hasattr(store, "insert_finding"):
            for f in findings:
                store.insert_finding(f)  # type: ignore[attr-defined]

    return report


def analyze_candidates(
    store: MemoryStore,
    embedder: Embedder,
    *,
    limit: int = 200,
) -> list[QualityReport]:
    queue = store.list_memories(status="candidate", needs_review=True, limit=limit)
    if not queue:
        queue = store.list_memories(status="candidate", limit=limit)
    return [analyze_memory(store, embedder, m.id) for m in queue]


def review_queue(
    store: MemoryStore,
    *,
    project_id: Optional[str] = None,
    domain: Optional[str] = None,
    type_: Optional[str] = None,
    sensitivity: Optional[str] = None,
    min_priority: float = 0.0,
    conflicts_only: bool = False,
    limit: int = 100,
) -> list[MemoryItem]:
    """Priority-ordered review queue."""
    memories = store.list_memories(
        status="candidate", needs_review=True, project_id=project_id,
        domain=domain, type_=type_, limit=limit * 3,
    )
    if not memories:
        memories = store.list_memories(status="candidate", project_id=project_id,
                                      domain=domain, type_=type_, limit=limit * 3)
    out: list[MemoryItem] = []
    for m in memories:
        if sensitivity and m.sensitivity.value != sensitivity:
            continue
        if m.review_priority < min_priority:
            continue
        if conflicts_only and "possible_conflict" not in m.quality_flags:
            continue
        out.append(m)
    out.sort(key=lambda m: (m.review_priority, -m.confidence), reverse=True)
    return out[:limit]
