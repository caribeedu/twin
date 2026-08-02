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
    CanonicalClaim,
    DuplicateGroup,
    FindingStatus,
    FindingType,
    INACTIVE_STATUSES,
    MemoryItem,
    QualityReport,
    ReviewFinding,
    SuggestedAction,
)
from ..memory.store.base import MemoryStore

ANALYZER_VERSION = "quality-v3"

# Per-embedder similarity thresholds (hash is lexical-ish, not semantic).
SIMILARITY_THRESHOLDS: dict[str, dict[str, float]] = {
    "hash": {"near_duplicate": 0.99, "related": 0.90, "claim_match": 0.95},
    "default": {"near_duplicate": 0.88, "related": 0.75, "claim_match": 0.82},
}

HIGH_IMPACT_TYPES = frozenset({"decision", "constraint", "belief"})
SENSITIVITY_WEIGHT = {
    "public": 0.3,
    "internal": 0.5,
    "private": 0.8,
    "restricted": 1.0,
}
SCOPE_TOKENS = ("development", "production", "dev", "prod", "local", "staging", "test")

# Altitude = consolidation height (not review urgency). Higher = more distilled.
#   ground    — atomic extract / low-level fact
#   linked    — typed durable claim without a multi-source arc
#   distilled — trajectory / cross-sense synthesis from reflect
#   stance    — governing constraint/decision/preference worth keeping as policy
ALTITUDE_ORDER = ("ground", "linked", "distilled", "stance")
ALTITUDE_QUALITY_BONUS = {
    "ground": 0.0,
    "linked": 0.12,
    "distilled": 0.28,
    "stance": 0.40,
}


def _thresholds(embedder: Embedder) -> dict[str, float]:
    name = getattr(embedder, "name", "default") or "default"
    if name in SIMILARITY_THRESHOLDS:
        return SIMILARITY_THRESHOLDS[name]
    if "hash" in name:
        return SIMILARITY_THRESHOLDS["hash"]
    return SIMILARITY_THRESHOLDS["default"]


def discover_neighbors(
    store: MemoryStore,
    embedder: Embedder,
    mem: MemoryItem,
    *,
    limit: int = 12,
) -> list[tuple[MemoryItem, float, str]]:
    text = f"{mem.title}\n{mem.summary}"
    vector = embedder.embed(text)
    related = _thresholds(embedder)["related"]
    scored: dict[str, tuple[float, str]] = {}

    for ref_id, sim in store.similar(vector, "memory", embedder.name, min_sim=related).items():
        if ref_id == mem.id:
            continue
        other = store.get_memory(ref_id)
        if other is None or other.status.value in INACTIVE_STATUSES:
            continue
        scored[ref_id] = (sim, "semantic")

    for name in mem.entities:
        ent = store.get_entity_by_name(name)
        if ent is None:
            continue
        for other in store.memories_for_entity(ent.id):
            if other.id == mem.id or other.status.value in INACTIVE_STATUSES:
                continue
            prev = scored.get(other.id, (0.0, ""))
            scored[other.id] = (max(prev[0], 0.55), "entity" if prev[0] < 0.55 else prev[1])

    for other in store.list_memories(project_id=mem.project_id, type_=mem.type.value, limit=80):
        if other.id == mem.id or other.status.value in INACTIVE_STATUSES:
            continue
        if mem.project_id and other.project_id == mem.project_id:
            prev = scored.get(other.id, (0.0, ""))
            if prev[0] < 0.4:
                scored[other.id] = (0.4, "project")

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


def memory_altitude(mem: MemoryItem) -> str:
    """Consolidation height of a memory — higher means more distilled value."""
    payload = mem.payload or {}
    mem_type = getattr(mem.type, "value", mem.type)
    trajectory = bool(payload.get("trajectory") or payload.get("source") == "episode_reflect")
    cross = bool(payload.get("cross_sense_refs") or payload.get("cross_sense"))
    if not cross and isinstance(payload.get("phase_keys"), list):
        # Multi-phase reflect claims are already above ground.
        cross = len(payload.get("phase_keys") or []) >= 2
    governing = mem_type in ("constraint", "decision", "preference", "belief")
    if trajectory and governing and (cross or mem_type == "constraint"):
        return "stance"
    if trajectory:
        return "distilled"
    if governing or mem_type in ("procedure", "relationship"):
        return "linked"
    return "ground"


def altitude_rank(altitude: str) -> int:
    try:
        return ALTITUDE_ORDER.index(altitude)
    except ValueError:
        return 0


def _specificity(mem: MemoryItem) -> float:
    words = len(mem.summary.split())
    if words < 6:
        return 0.25
    if words < 12:
        return 0.5
    conjunctions = len(re.findall(r"\b(and|,|;)\b", mem.summary, flags=re.I))
    if conjunctions >= 3 and words > 20:
        return 0.35
    return min(1.0, 0.55 + words / 40)


def _claim_of(mem: MemoryItem) -> Optional[CanonicalClaim]:
    if mem.canonical_claim and (mem.canonical_claim.subject or mem.canonical_claim.predicate):
        return mem.canonical_claim
    return None


def _scope_tokens(text: str) -> set[str]:
    low = text.lower()
    return {s for s in SCOPE_TOKENS if s in low}


def _scope_difference(a: MemoryItem, b: MemoryItem) -> bool:
    sa = _scope_tokens(f"{a.title} {a.summary}")
    sb = _scope_tokens(f"{b.title} {b.summary}")
    ca, cb = _claim_of(a), _claim_of(b)
    if ca and cb:
        qa = {str(k).lower(): str(v).lower() for k, v in (ca.qualifiers or {}).items()}
        qb = {str(k).lower(): str(v).lower() for k, v in (cb.qualifiers or {}).items()}
        for key in set(qa) & set(qb):
            if qa[key] != qb[key]:
                return True
    return bool(sa and sb and sa.isdisjoint(sb))


def _normalize_tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9_]{3,}", text.lower())}


def _looks_conflict(a: MemoryItem, b: MemoryItem, *, sim: float, claim_match: float) -> str | None:
    """Return finding type or None. Only comparable claims can conflict."""
    if a.type.value != b.type.value:
        return None

    ca, cb = _claim_of(a), _claim_of(b)
    if ca and cb:
        if ca.subject.lower() != cb.subject.lower():
            return None
        if ca.predicate.lower() != cb.predicate.lower():
            return None
        if _scope_difference(a, b):
            return FindingType.scope_difference.value
        if ca.object.lower() != cb.object.lower():
            return FindingType.possible_conflict.value
        return None

    # Heuristic fallback: require high similarity + shared entities, not mere text difference
    if sim < claim_match:
        return FindingType.possibly_related.value if sim >= claim_match - 0.1 else None

    shared = set(x.lower() for x in a.entities) & set(x.lower() for x in b.entities)
    if not shared:
        return None
    if _scope_difference(a, b):
        return FindingType.scope_difference.value

    ta, tb = a.summary.lower(), b.summary.lower()
    neg_a = bool(re.search(r"\b(not|never|no longer|instead of)\b", ta))
    neg_b = bool(re.search(r"\b(not|never|no longer|instead of)\b", tb))
    if neg_a != neg_b:
        return FindingType.possible_conflict.value

    # Same "uses X" pattern with different object tokens and high overlap otherwise
    m_a = re.search(r"\buses?\s+([a-z0-9_.+-]+)", ta)
    m_b = re.search(r"\buses?\s+([a-z0-9_.+-]+)", tb)
    if m_a and m_b and m_a.group(1) != m_b.group(1):
        # require the surrounding claim context to be similar
        toks_a = _normalize_tokens(ta) - {m_a.group(1)}
        toks_b = _normalize_tokens(tb) - {m_b.group(1)}
        if not toks_a or not toks_b:
            return FindingType.possibly_related.value
        overlap = len(toks_a & toks_b) / max(1, len(toks_a | toks_b))
        if overlap >= 0.45:
            return FindingType.possible_conflict.value
        return FindingType.possibly_related.value

    # High-impact + different text alone is NOT a conflict
    if a.type.value in HIGH_IMPACT_TYPES and ta != tb:
        return FindingType.possibly_related.value
    return None


def review_priority(
    mem: MemoryItem,
    *,
    contradiction_risk: float = 0.0,
    source_risk: float = 0.0,
    future_reuse: float = 0.0,
    possible_supersedence: bool = False,
) -> float:
    """Weighted sum with critical floors — conflicts are never buried by confidence."""
    impact = {"low": 0.35, "medium": 0.55, "high": 0.85}.get(mem.impact, 0.55)
    if mem.type.value in HIGH_IMPACT_TYPES:
        impact = max(impact, 0.8)
    uncertainty = max(0.1, 1.0 - mem.confidence)
    sensitivity = SENSITIVITY_WEIGHT.get(mem.sensitivity.value, 0.5)
    reuse = max(0.15, min(1.0, 0.25 + future_reuse + min(mem.retrieval_count, 20) / 25))
    src = max(0.15, source_risk) if source_risk else 0.35
    contradiction = contradiction_risk

    base = (
        0.28 * impact
        + 0.18 * uncertainty
        + 0.22 * contradiction
        + 0.14 * sensitivity
        + 0.10 * reuse
        + 0.08 * src
    )

    if contradiction_risk >= 0.8:
        base = max(base, 0.9)
    if possible_supersedence and mem.type.value in HIGH_IMPACT_TYPES:
        base = max(base, 0.85)
    if mem.sensitivity.value == "restricted":
        base = max(base, 0.8)
    if mem.sensitivity.value == "private":
        base = max(base, 0.65)
    if "exact_duplicate" in mem.quality_flags and contradiction_risk < 0.3:
        # batchable — keep visible but not panic-high
        base = min(base, 0.55)

    return round(min(1.0, base), 4)


def select_canonical_survivor(memories: list[MemoryItem], store: MemoryStore) -> MemoryItem:
    """Pick one survivor from an exact-duplicate group."""
    def sort_key(m: MemoryItem) -> tuple:
        evidence = store.get_evidence(m.id)
        groups = {e.independence_group or e.artifact_id or e.percept_id for e in evidence}
        avg_trust = (
            sum(e.source_trust for e in evidence) / len(evidence) if evidence else 0.0
        )
        # Ascending key: better survivors first.
        return (
            0 if m.status.value == "confirmed" else 1,
            -len(evidence),
            -len(groups),
            -avg_trust,
            -m.confidence,
            m.created_at or "9999",  # older first
        )

    return sorted(memories, key=sort_key)[0]


def build_duplicate_groups(
    store: MemoryStore,
    candidates: list[MemoryItem],
) -> list[DuplicateGroup]:
    """Union-find exact-duplicate clusters from quality flags / findings."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for mem in candidates:
        if "exact_duplicate" not in mem.quality_flags:
            continue
        findings = []
        if hasattr(store, "get_findings"):
            findings = store.get_findings(mem.id)  # type: ignore[attr-defined]
        related = [
            f.related_memory_id for f in findings
            if f.type == FindingType.exact_duplicate and f.related_memory_id
        ]
        if not related:
            # fall back: other candidates with same flag + near-identical title
            for other in candidates:
                if other.id == mem.id:
                    continue
                if other.title.strip().lower() == mem.title.strip().lower():
                    related.append(other.id)
        for rid in related:
            union(mem.id, rid)

    clusters: dict[str, list[str]] = {}
    for mem in candidates:
        if "exact_duplicate" not in mem.quality_flags and mem.id not in parent:
            continue
        if mem.id not in parent:
            continue
        root = find(mem.id)
        clusters.setdefault(root, []).append(mem.id)

    groups: list[DuplicateGroup] = []
    ts = now_iso()
    for members in clusters.values():
        if len(members) < 2:
            continue
        objs = [store.get_memory(m) for m in members]
        objs = [m for m in objs if m]
        if len(objs) < 2:
            continue
        survivor = select_canonical_survivor(objs, store)
        groups.append(DuplicateGroup(
            id=ids.new_id("dup"),
            memory_ids=[m.id for m in objs],
            canonical_memory_id=survivor.id,
            reason="exact duplicate cluster",
            created_at=ts,
        ))
    return groups


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

    thr = _thresholds(embedder)
    neighbors = discover_neighbors(store, embedder, mem)
    findings: list[ReviewFinding] = []
    flags: list[str] = []
    contradiction_risk = 0.0
    possible_supersedence = False
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
            analyzer_version=ANALYZER_VERSION,
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
            analyzer_version=ANALYZER_VERSION,
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
                analyzer_version=ANALYZER_VERSION,
            ))
            flags.append("exact_duplicate")
            suggested = SuggestedAction.reject
            continue

        if sim >= thr["near_duplicate"]:
            findings.append(ReviewFinding(
                id=ids.finding_id(), memory_id=mem.id, type=FindingType.near_duplicate,
                related_memory_id=other.id, confidence=sim,
                reason=f"near-duplicate via {reason}",
                suggested_action=SuggestedAction.merge,
                requires_human_review=True, created_at=ts,
                analyzer_version=ANALYZER_VERSION,
            ))
            flags.append("near_duplicate")
            requires_human = True
            suggested = SuggestedAction.merge
            continue

        kind = _looks_conflict(mem, other, sim=sim, claim_match=thr["claim_match"])
        if kind == FindingType.scope_difference.value:
            findings.append(ReviewFinding(
                id=ids.finding_id(), memory_id=mem.id, type=FindingType.scope_difference,
                related_memory_id=other.id, confidence=0.7,
                reason="similar claim with different scope — may coexist",
                suggested_action=SuggestedAction.confirm,
                requires_human_review=False, created_at=ts,
                analyzer_version=ANALYZER_VERSION,
            ))
            flags.append("scope_difference")
            continue

        if kind == FindingType.possible_conflict.value:
            newer = (mem.valid_from or mem.created_at) > (other.valid_from or other.created_at)
            if mem.type.value == "decision" and other.type.value == "decision" and newer:
                findings.append(ReviewFinding(
                    id=ids.finding_id(), memory_id=mem.id,
                    type=FindingType.possible_supersedence,
                    related_memory_id=other.id, confidence=min(0.95, sim + 0.05),
                    reason="newer decision may supersede older comparable claim",
                    suggested_action=SuggestedAction.supersede,
                    requires_human_review=True, created_at=ts,
                    analyzer_version=ANALYZER_VERSION,
                ))
                flags.append("possible_supersedence")
                suggested = SuggestedAction.supersede
                possible_supersedence = True
            else:
                findings.append(ReviewFinding(
                    id=ids.finding_id(), memory_id=mem.id,
                    type=FindingType.possible_conflict,
                    related_memory_id=other.id, confidence=sim,
                    reason="comparable claims with incompatible values",
                    suggested_action=SuggestedAction.contradict,
                    requires_human_review=True, created_at=ts,
                    analyzer_version=ANALYZER_VERSION,
                ))
                flags.append("possible_conflict")
                suggested = SuggestedAction.contradict
            contradiction_risk = max(contradiction_risk, sim)
            requires_human = True
            continue

        if kind == FindingType.possibly_related.value:
            findings.append(ReviewFinding(
                id=ids.finding_id(), memory_id=mem.id, type=FindingType.possibly_related,
                related_memory_id=other.id, confidence=sim,
                reason="related but not established as conflict",
                suggested_action=SuggestedAction.defer,
                requires_human_review=False, created_at=ts,
                analyzer_version=ANALYZER_VERSION,
            ))
            flags.append("possibly_related")
            continue

        if thr["related"] <= sim < thr["near_duplicate"] and mem.type.value == other.type.value:
            if mem.project_id == other.project_id:
                findings.append(ReviewFinding(
                    id=ids.finding_id(), memory_id=mem.id, type=FindingType.possible_merge,
                    related_memory_id=other.id, confidence=sim,
                    reason="paraphrase candidates — merge or corroborate",
                    suggested_action=SuggestedAction.merge,
                    requires_human_review=True, created_at=ts,
                    analyzer_version=ANALYZER_VERSION,
                ))
                flags.append("possible_merge")
                requires_human = True

    if mem.retrieval_count >= 3:
        flags.append("high_future_reuse")

    impact = mem.impact
    if mem.type.value in HIGH_IMPACT_TYPES or mem.sensitivity.value in ("private", "restricted"):
        impact = "high"
        requires_human = True

    altitude = memory_altitude(mem)
    priority = review_priority(
        mem.model_copy(update={"impact": impact, "quality_flags": flags}),
        contradiction_risk=contradiction_risk,
        source_risk=0.7 if mem.confidence < 0.5 else 0.35,
        future_reuse=1.0 if "high_future_reuse" in flags else 0.3,
        possible_supersedence=possible_supersedence,
    )
    # quality_score = how distilled/useful the memory is (altitude-aware).
    # review_priority = how urgently a human should look (risk-aware).
    quality = round(
        min(
            1.0,
            0.30 * spec
            + 0.25 * (1.0 if evidence else 0.2)
            + 0.15 * mem.confidence
            + 0.10 * (1.0 - contradiction_risk)
            + ALTITUDE_QUALITY_BONUS.get(altitude, 0.0),
        ),
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
        altitude=altitude,
    )

    if persist:
        payload = dict(mem.payload or {})
        payload["altitude"] = altitude
        store.update_memory(
            mem.id,
            review_priority=priority,
            quality_score=quality,
            quality_flags=report.quality_flags,
            impact=impact,
            payload=payload,
            needs_review=report.requires_human_review or mem.needs_review,
            review_reason=mem.review_reason or (findings[0].reason if findings else None),
            last_reconciled_at=ts,
        )
        if hasattr(store, "replace_findings"):
            # preserve dismissed findings — only replace open/obsolete of this analyzer
            store.replace_findings(mem.id, findings)  # type: ignore[attr-defined]

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
