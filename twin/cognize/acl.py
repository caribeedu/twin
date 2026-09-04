"""ACL intersection and revoke tombstones for Narratives."""

from __future__ import annotations

from twin.privacy.vault import FALLBACK_VAULT, iter_vault_ids, resolve_vault

from typing import Any, Optional

from twin.cognize.models import EpistemicStatus, Trace
from twin.clock import now_iso


_RANK = {"public": 0, "internal": 1, "private": 2, "restricted": 3}


def intersect_sensitivity(values: list[str]) -> str:
    if not values:
        return "internal"
    return max(values, key=lambda v: _RANK.get(str(v), 1))


def sensitivity_from_evidence(
    store: Any,
    evidence_ids: list[str],
) -> str:
    """Highest confidentiality among contributing percepts / evidence anchors."""
    levels: list[str] = []
    for eid in evidence_ids:
        if eid.startswith("migrated:"):
            continue
        if hasattr(store, "get_percept"):
            p = store.get_percept(eid)
            if p is not None:
                levels.append(getattr(p, "source_confidentiality", None) or "internal")
                continue
        # Evidence anchor by id
        if hasattr(store, "list_evidence_anchors"):
            found = False
            for vault in (iter_vault_ids(store) or [FALLBACK_VAULT]):
                for anc in store.list_evidence_anchors(vault):
                    if anc.id == eid or anc.percept_id == eid:
                        p = (
                            store.get_percept(anc.percept_id)
                            if hasattr(store, "get_percept")
                            else None
                        )
                        if p is not None:
                            levels.append(
                                getattr(p, "source_confidentiality", None) or "internal"
                            )
                            found = True
                            break
                if found:
                    break
    return intersect_sensitivity(levels)


def evidence_source_sensors(store: Any, evidence_ids: list[str]) -> set[str]:
    sensors: set[str] = set()
    for eid in evidence_ids:
        if not hasattr(store, "get_percept"):
            break
        p = store.get_percept(eid)
        if p is None and hasattr(store, "list_evidence_anchors"):
            for vid in (iter_vault_ids(store) or [FALLBACK_VAULT]):
                for anc in store.list_evidence_anchors(vid):
                    if anc.id == eid or anc.percept_id == eid:
                        p = store.get_percept(anc.percept_id)
                        break
                if p is not None:
                    break
        if p is not None:
            sensors.add((getattr(p, "source_sensor", None) or "").lower())
    return {s for s in sensors if s}


def narrative_visible_to_access(nar: Any, access: Any) -> bool:
    """Fail closed for private/restricted Narratives and source-sensor ACL.

    Access may carry:
    - ``audience`` — self/owner may see private; others may not
    - ``allowed_source_sensors`` / ``metadata['allowed_source_sensors']`` —
      if present, Narrative evidence sensors must be a subset
    - ``principal_id`` denied via ``metadata['denied_principals']`` on Narrative
    """
    sens = getattr(nar, "sensitivity", None) or "internal"
    if hasattr(sens, "value"):
        sens = sens.value
    audience = getattr(access, "audience", None) or "self"
    if sens in ("private", "restricted") and audience not in ("self", "owner"):
        return False

    meta = getattr(nar, "metadata", None) or {}
    denied = set(meta.get("denied_principals") or [])
    principal = getattr(access, "principal_id", None) or ""
    if principal and principal in denied:
        return False

    allowed_sensors = getattr(access, "allowed_source_sensors", None)
    if allowed_sensors is None and isinstance(getattr(access, "metadata", None), dict):
        allowed_sensors = access.metadata.get("allowed_source_sensors")
    if allowed_sensors is not None:
        required = set(meta.get("source_sensors") or [])
        if required and not required.issubset(set(allowed_sensors)):
            return False
    return True


def tombstone_narratives_for_percept(
    store: Any,
    percept_id: str,
    *,
    reason: str = "source revoked",
    vault_id: str = FALLBACK_VAULT,
) -> list[str]:
    """Synchronously tombstone Narratives whose evidence includes this percept."""
    if not hasattr(store, "list_narratives"):
        return []
    touched: list[str] = []
    for nar in store.list_narratives(vault_id):
        evid = set(nar.evidence_ids or [])
        if percept_id not in evid:
            # also check anchors targeting this narrative
            if hasattr(store, "list_evidence_anchors"):
                hit = False
                for anc in store.list_evidence_anchors(
                    vault_id, target_kind="narrative", target_id=nar.id
                ):
                    if anc.percept_id == percept_id:
                        hit = True
                        break
                if not hit:
                    continue
            else:
                continue
        if not nar.epistemic_state_id:
            continue
        eps = store.get_epistemic_state(nar.epistemic_state_id)
        if eps is None:
            continue
        if eps.status is EpistemicStatus.tombstoned:
            continue
        store.upsert_epistemic_state(
            eps.model_copy(
                update={
                    "status": EpistemicStatus.tombstoned,
                    "stale_reason": reason,
                }
            )
        )
        if hasattr(store, "append_trace"):
            store.append_trace(
                Trace(
                    vault_id=vault_id,
                    event_kind="tombstone",
                    resource_kind="narrative",
                    resource_id=nar.id,
                    metadata={"percept_id": percept_id, "reason": reason},
                )
            )
        touched.append(nar.id)
    return touched
