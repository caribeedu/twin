"""Fade / Remarkable accessibility recommendations (Stage 12).

Recommendations enqueue review; they never silently delete Narratives.
Age alone is not Cognize deletion policy.
"""

from __future__ import annotations

from typing import Any, Optional

from twin.clock import now_iso
from twin.cognize.models import NarrativeStatus, Trace


def recommend_accessibility(
    store: Any,
    vault_id: str = "default",
    *,
    dry_run: bool = False,
    max_recs: int = 50,
) -> list[dict[str, Any]]:
    """Propose remarkable / ordinary / fading labels from Trace + Stance links.

    Does not delete or archive Narratives automatically.
    """
    if not hasattr(store, "list_narratives"):
        return []
    stance_linked: set[str] = set()
    if hasattr(store, "list_judgment_items"):
        for item in store.list_judgment_items(status="active", limit=5_000):
            meta = getattr(item, "metadata", None) or {}
            nid = meta.get("narrative_id") or (item.provenance or {}).get("narrative_id") if hasattr(item, "provenance") else None
            # JudgmentItem may store provenance differently
            prov = getattr(item, "provenance", None)
            if prov is not None and getattr(prov, "memory_ids", None) is None:
                nid = nid or (getattr(prov, "metadata", None) or {}).get("narrative_id")
            proposed = getattr(item, "statement", None)
            # Check proposed_item-like metadata on judgment proposals is separate
            mid = (getattr(item, "metadata", None) or {}).get("narrative_id")
            if mid:
                stance_linked.add(str(mid))
            # also scan description for narrative id token
            desc = getattr(item, "description", "") or ""
            if "Narrative " in desc:
                # best-effort: skip
                pass

    if hasattr(store, "list_judgment_proposals"):
        for p in store.list_judgment_proposals(status="pending", limit=2_000):
            nid = (p.metadata or {}).get("narrative_id")
            if nid:
                stance_linked.add(str(nid))
            src = (p.proposed_item or {}).get("provenance", {}).get("narrative_id")
            if src:
                stance_linked.add(str(src))

    trace_counts: dict[str, int] = {}
    if hasattr(store, "list_traces"):
        for tr in store.list_traces(vault_id, event_kind="pack_serve", limit=2_000):
            if tr.resource_kind == "narrative" and tr.resource_id:
                trace_counts[tr.resource_id] = trace_counts.get(tr.resource_id, 0) + 1

    recs: list[dict[str, Any]] = []
    for nar in store.list_narratives(vault_id):
        if len(recs) >= max_recs:
            break
        if nar.status in (NarrativeStatus.archived, NarrativeStatus.superseded):
            continue
        hits = trace_counts.get(nar.id, 0)
        if nar.id in stance_linked:
            label = NarrativeStatus.remarkable.value
            reason = "linked to pending/active Stance — pin accessibility"
        elif hits >= 3:
            label = NarrativeStatus.ordinary.value
            reason = f"retrieved {hits} times recently"
        elif hits == 0:
            label = NarrativeStatus.fading.value
            reason = "no recent pack retrieval; candidate for fade review"
        else:
            label = NarrativeStatus.ordinary.value
            reason = f"sparse retrieval ({hits})"
        current = nar.status.value if hasattr(nar.status, "value") else str(nar.status)
        if current == label:
            continue
        rec = {
            "narrative_id": nar.id,
            "from_status": current,
            "recommended": label,
            "reason": reason,
            "trace_hits": hits,
            "stance_linked": nar.id in stance_linked,
            "at": now_iso(),
        }
        recs.append(rec)
        if dry_run:
            continue
        meta = dict(nar.metadata or {})
        meta["accessibility_recommendation"] = rec
        store.upsert_narrative(nar.model_copy(update={"metadata": meta}))
        if hasattr(store, "append_trace"):
            store.append_trace(
                Trace(
                    vault_id=vault_id,
                    event_kind="fade_recommend",
                    resource_kind="narrative",
                    resource_id=nar.id,
                    metadata={"recommended": label, "reason": reason},
                )
            )
    return recs


def list_accessibility_recommendations(store: Any, vault_id: str = "default") -> list[dict]:
    out: list[dict] = []
    if not hasattr(store, "list_narratives"):
        return out
    for nar in store.list_narratives(vault_id):
        rec = (nar.metadata or {}).get("accessibility_recommendation")
        if rec:
            out.append(rec)
    return out
