"""Post-reflect condensation — collapse near-duplicate candidates into one.

Keeps the highest-altitude survivor's title/summary and merges evidence via
``merge_memories``. Runs after hippocampus_consolidate so meditate doesn't
leave five paraphrases of the same launch-gate claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from twin.store.lifecycle import merge_memories
from twin.store.models import FindingType, INACTIVE_STATUSES, StoreClaim
from .quality import altitude_rank, claim_altitude


@dataclass
class CondenseReport:
    groups_seen: int = 0
    merged: int = 0
    survivor_ids: list[str] = field(default_factory=list)
    absorbed_ids: list[str] = field(default_factory=list)
    skipped: int = 0
    detail: str = ""


def _is_active_candidate(mem: Optional[StoreClaim]) -> bool:
    if mem is None:
        return False
    status = getattr(mem.status, "value", mem.status)
    if status in INACTIVE_STATUSES or status in ("merged", "split", "deleted"):
        return False
    return status == "candidate"


def _cluster_key_members(
    store,
    seeds: list[StoreClaim],
) -> list[list[StoreClaim]]:
    """Union-find clusters from near_duplicate / possible_merge findings."""
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

    by_id = {m.id: m for m in seeds}
    for mem in seeds:
        parent.setdefault(mem.id, mem.id)
        if not hasattr(store, "get_findings"):
            continue
        for f in store.get_findings(mem.id):
            ftype = getattr(f.type, "value", f.type)
            if ftype not in (
                FindingType.near_duplicate.value,
                FindingType.possible_merge.value,
                FindingType.exact_duplicate.value,
            ):
                continue
            other_id = f.related_claim_id
            if not other_id or other_id not in by_id:
                continue
            other = by_id[other_id]
            if (mem.project_id or "") != (other.project_id or ""):
                continue
            if (mem.domain or "") != (other.domain or ""):
                continue
            if getattr(mem.type, "value", mem.type) != getattr(
                other.type, "value", other.type
            ):
                continue
            union(mem.id, other_id)

    clusters: dict[str, list[StoreClaim]] = {}
    for mem in seeds:
        if mem.id not in parent:
            continue
        clusters.setdefault(find(mem.id), []).append(mem)
    return [ms for ms in clusters.values() if len(ms) >= 2]


def _pick_survivor(members: list[StoreClaim]) -> StoreClaim:
    def key(m: StoreClaim) -> tuple:
        alt = claim_altitude(m)
        return (
            -altitude_rank(alt),
            -float(m.quality_score or 0),
            -float(m.confidence or 0),
            m.created_at or "",
        )

    return sorted(members, key=key)[0]


def condense_near_duplicates(
    store,
    embedder=None,
    *,
    claim_ids: Optional[list[str]] = None,
    limit: int = 200,
    dry_run: bool = False,
) -> CondenseReport:
    """Merge near-duplicate candidate clusters into one survivor each."""
    report = CondenseReport()
    seeds: list[StoreClaim] = []
    if claim_ids:
        for mid in claim_ids:
            mem = store.get_claim(mid)
            if _is_active_candidate(mem):
                seeds.append(mem)  # type: ignore[arg-type]
    else:
        pool = store.list_claims(status="candidate", needs_review=True, limit=limit)
        for mem in pool:
            flags = set(mem.quality_flags or [])
            if flags & {"near_duplicate", "possible_merge", "exact_duplicate"}:
                seeds.append(mem)
            elif (mem.payload or {}).get("source") == "episode_reflect":
                seeds.append(mem)

    seen: set[str] = set()
    uniq: list[StoreClaim] = []
    for m in seeds:
        if m.id in seen:
            continue
        seen.add(m.id)
        uniq.append(m)
    seeds = uniq

    clusters = _cluster_key_members(store, seeds)
    report.groups_seen = len(clusters)
    if not clusters:
        report.detail = "no near-duplicate clusters"
        return report

    for members in clusters:
        survivor = _pick_survivor(members)
        # Primary = survivor so merge inherits trajectory / altitude payload.
        ids = [survivor.id] + [m.id for m in members if m.id != survivor.id]
        if dry_run:
            report.merged += 1
            report.survivor_ids.append(survivor.id)
            report.absorbed_ids.extend(i for i in ids if i != survivor.id)
            continue
        try:
            from .interpreter.reflect_prompt import _coerce_claim_type

            claim = survivor.canonical_claim
            out_type = getattr(survivor.type, "value", survivor.type)
            out_type = _coerce_claim_type(
                str(out_type),
                title=survivor.title or "",
                summary=survivor.summary or "",
            )
            result = merge_memories(
                store,
                ids,
                title=survivor.title,
                summary=survivor.summary,
                actor="system:condense",
                embedder=embedder,
                output_type=out_type,
                output_domain=survivor.domain,
                output_project_id=survivor.project_id,
                output_canonical_claim=(
                    claim.model_dump() if claim is not None
                    and hasattr(claim, "model_dump") else claim
                ),
            )
        except Exception:
            report.skipped += 1
            continue
        new_id = result.extras.get("merged_id") or result.subject_id
        report.merged += 1
        if new_id:
            report.survivor_ids.append(new_id)
            merged_mem = store.get_claim(new_id)
            if merged_mem is not None:
                payload = dict(merged_mem.payload or {})
                # Recompute on the merge product (inherits trajectory payload).
                payload["altitude"] = claim_altitude(merged_mem)
                payload["condensed"] = True
                store.update_claim(
                    new_id,
                    payload=payload,
                    needs_review=True,
                    review_reason="condensed near-duplicates — confirm",
                    # Surface above ordinary candidates in the review queue.
                    review_priority=0.97,
                )
        report.absorbed_ids.extend(i for i in ids if i != new_id)

    report.detail = f"condensed {report.merged} cluster(s)"
    return report
