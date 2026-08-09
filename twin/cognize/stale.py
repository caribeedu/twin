"""Mark Narratives stale when a relevant Percept lands."""

from __future__ import annotations

from typing import Any, Optional

from twin.cognize.models import EpistemicStatus
from twin.clock import now_iso
from twin.sensory.percept import Percept


def _vault_for_percept(percept: Percept) -> str:
    meta = percept.metadata or {}
    return str(meta.get("vault_id") or meta.get("vault") or "default")


def _domain_hint(percept: Percept) -> str:
    meta = percept.metadata or {}
    return str(meta.get("domain") or meta.get("target_domain") or "")


def mark_stale_for_new_percept(store: Any, percept: Percept) -> list[str]:
    """Mark overlapping Narratives stale; return touched narrative ids."""
    if not hasattr(store, "list_narratives") or not hasattr(store, "mark_epistemic_stale"):
        return []
    vault = _vault_for_percept(percept)
    domain = _domain_hint(percept)
    project_id = percept.project_id or ""
    touched: list[str] = []
    for nar in store.list_narratives(vault):
        if domain and nar.domain and nar.domain != domain:
            continue
        if project_id and nar.project_id and nar.project_id != project_id:
            continue
        if not nar.epistemic_state_id:
            continue
        eps = store.get_epistemic_state(nar.epistemic_state_id)
        if eps is None:
            continue
        if eps.status in (EpistemicStatus.tombstoned, EpistemicStatus.superseded):
            continue
        reason = f"new observation {percept.id} after synthesis"
        store.mark_epistemic_stale(
            nar.epistemic_state_id,
            reason=reason,
            unseen_percept_id=percept.id,
        )
        touched.append(nar.id)
    return touched


def refresh_after_resynthesis(
    store: Any,
    *,
    vault_id: str,
    domain: str = "",
    project_id: Optional[str] = None,
    except_narrative_id: Optional[str] = None,
    clear_stale_only: bool = True,
) -> list[str]:
    """Clear stale on Narratives in scope after re-commit. Returns refreshed ids."""
    if not hasattr(store, "list_narratives") or not hasattr(store, "mark_epistemic_fresh"):
        return []
    refreshed: list[str] = []
    for nar in store.list_narratives(vault_id):
        if except_narrative_id and nar.id == except_narrative_id:
            continue
        if domain and nar.domain and nar.domain != domain:
            continue
        if project_id and nar.project_id and nar.project_id != project_id:
            continue
        if not nar.epistemic_state_id:
            continue
        eps = store.get_epistemic_state(nar.epistemic_state_id)
        if eps is None:
            continue
        if clear_stale_only and eps.status is not EpistemicStatus.stale:
            continue
        if eps.status in (EpistemicStatus.tombstoned, EpistemicStatus.superseded):
            continue
        store.mark_epistemic_fresh(
            nar.epistemic_state_id,
            evidence_ids=list(eps.evidence_ids or nar.evidence_ids),
            freshness_boundary=now_iso(),
            synthesized_at=now_iso(),
        )
        refreshed.append(nar.id)
    return refreshed
