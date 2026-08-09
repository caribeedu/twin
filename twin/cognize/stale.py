"""Mark Narratives stale when a relevant Percept lands (deterministic)."""

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
    """Deterministic safety latch — no LLM.

    Marks EpistemicState of Narratives in the same vault (and overlapping
    domain/project when set) as ``stale`` and records the percept id in
    ``unseen_since``. Returns narrative ids touched.
    """
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
