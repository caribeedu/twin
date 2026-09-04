"""Backfill StoreClaim → Narrative / Interpretation."""

from __future__ import annotations

from twin.privacy.vault import FALLBACK_VAULT, resolve_vault

from typing import Any, Optional

from twin.cognize.models import (
    EpistemicState,
    EpistemicStatus,
    Interpretation,
    InterpretationStatus,
    Narrative,
    NarrativeStatus,
)
from twin.clock import now_iso
from twin.store.models import StoreClaim, ClaimStatus


def claim_to_provisional(
    mem: StoreClaim,
    *,
    vault_id: str = FALLBACK_VAULT,
) -> tuple[str, Narrative | Interpretation]:
    """Map memory to Narrative (confirmed) or Interpretation (candidate / needs_review)."""
    evidence_ids = list(getattr(mem, "source_ids", None) or [])
    if mem.needs_review or mem.status != ClaimStatus.confirmed:
        intp = Interpretation(
            vault_id=vault_id,
            explanation=(mem.summary or mem.title or "").strip() or mem.id,
            status=InterpretationStatus.competing,
            evidence_ids=evidence_ids,
            metadata={
                "claim_id": mem.id,
                "needs_review": bool(mem.needs_review),
                "memory_status": mem.status.value
                if hasattr(mem.status, "value")
                else str(mem.status),
            },
        )
        return "interpretation", intp

    eps = EpistemicState(
        status=EpistemicStatus.fresh,
        synthesized_at=mem.created_at or now_iso(),
        freshness_boundary=mem.valid_from or mem.created_at or now_iso(),
        evidence_ids=evidence_ids,
    )
    nar = Narrative(
        vault_id=vault_id,
        account=(mem.summary or mem.title or "").strip() or mem.id,
        status=NarrativeStatus.committed,
        epistemic_state_id=eps.id,
        evidence_ids=evidence_ids,
        domain=mem.domain or "",
        persona=mem.persona or "",
        sensitivity=mem.sensitivity.value
        if hasattr(mem.sensitivity, "value")
        else str(mem.sensitivity or "internal"),
        project_id=getattr(mem, "project_id", None),
        migrated_from_memory=True,
        committed_by="migration",
        metadata={"claim_id": mem.id, "eps_pending": eps.model_dump(mode="json")},
    )
    return "narrative", nar


def _existing_claim_ids(store: Any, vault_id: str) -> set[str]:
    existing: set[str] = set()
    if hasattr(store, "list_narratives"):
        for nar in store.list_narratives(vault_id):
            mid = (nar.metadata or {}).get("claim_id")
            if mid:
                existing.add(mid)
    if hasattr(store, "list_cognize_interpretations"):
        for intp in store.list_cognize_interpretations(vault_id):
            mid = (intp.metadata or {}).get("claim_id")
            if mid:
                existing.add(mid)
    return existing


def backfill_from_memories(
    store: Any,
    *,
    vault_id: str = FALLBACK_VAULT,
    dry_run: bool = True,
    limit: int = 10_000,
) -> dict[str, Any]:
    """Copy memories into Cognize entities; idempotent on ``metadata.claim_id``."""
    memories = store.list_claims() if hasattr(store, "list_claims") else []
    stats = {
        "scanned": 0,
        "narratives": 0,
        "interpretations": 0,
        "skipped": 0,
        "dry_run": dry_run,
    }
    existing_mem_ids = _existing_claim_ids(store, vault_id)

    for mem in memories[:limit]:
        stats["scanned"] += 1
        if mem.id in existing_mem_ids:
            stats["skipped"] += 1
            continue
        if mem.status in (
            ClaimStatus.rejected,
            ClaimStatus.merged,
            ClaimStatus.split,
            ClaimStatus.deleted,
            ClaimStatus.archived,
        ):
            stats["skipped"] += 1
            continue
        kind, obj = claim_to_provisional(mem, vault_id=vault_id)
        if dry_run:
            if kind == "narrative":
                stats["narratives"] += 1
            else:
                stats["interpretations"] += 1
            continue
        if kind == "narrative":
            assert isinstance(obj, Narrative)
            eps_data = (obj.metadata or {}).pop("eps_pending", None)
            if eps_data:
                eps = EpistemicState.model_validate(eps_data)
                store.upsert_epistemic_state(eps)
                obj.epistemic_state_id = eps.id
            if hasattr(store, "get_evidence"):
                try:
                    evs = store.get_evidence(mem.id)
                    obj.evidence_ids = [e.id for e in evs] or obj.evidence_ids
                    if obj.epistemic_state_id:
                        eps = store.get_epistemic_state(obj.epistemic_state_id)
                        if eps:
                            store.upsert_epistemic_state(
                                eps.model_copy(update={"evidence_ids": obj.evidence_ids})
                            )
                except Exception:
                    pass
            if not obj.evidence_ids:
                obj.metadata["migration_warning"] = "confirmed_without_evidence"
                obj.evidence_ids = [f"migrated:{mem.id}"]
                if obj.epistemic_state_id:
                    eps = store.get_epistemic_state(obj.epistemic_state_id)
                    if eps:
                        store.upsert_epistemic_state(
                            eps.model_copy(update={"evidence_ids": obj.evidence_ids})
                        )
            store.upsert_narrative(obj)
            stats["narratives"] += 1
            existing_mem_ids.add(mem.id)
        else:
            assert isinstance(obj, Interpretation)
            store.upsert_interpretation(obj)
            stats["interpretations"] += 1
            existing_mem_ids.add(mem.id)
    return stats
