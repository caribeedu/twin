"""Commit Narrative after human review."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from twin.cognize.models import (
    EpistemicState,
    EpistemicStatus,
    Interpretation,
    InterpretationStatus,
    Narrative,
    NarrativeGrain,
    NarrativeStatus,
)
from twin.cognize.acl import sensitivity_from_evidence
from twin.clock import now_iso


class CommitError(ValueError):
    pass


_RANK = {"public": 0, "internal": 1, "private": 2, "restricted": 3}


def _pick_sensitivity(requested: str, floor: str) -> str:
    if _RANK.get(requested, 1) < _RANK.get(floor, 1):
        raise CommitError(
            f"sensitivity {requested} expands beyond evidence floor {floor}"
        )
    return requested or floor


def preview_commit_token(
    *,
    account: str,
    evidence_ids: list[str],
    vault_id: str,
    interpretation_ids: Optional[list[str]] = None,
    dissent_interpretation_ids: Optional[list[str]] = None,
    domain: str = "",
) -> str:
    """Fingerprint for commit confirm."""
    payload = {
        "account": (account or "").strip(),
        "evidence_ids": sorted(evidence_ids or []),
        "vault_id": vault_id or "default",
        "interpretation_ids": sorted(interpretation_ids or []),
        "dissent_interpretation_ids": sorted(dissent_interpretation_ids or []),
        "domain": domain or "",
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def commit_narrative(
    store: Any,
    *,
    account: str,
    vault_id: str,
    evidence_ids: list[str],
    committed_by: str,
    interpretation_ids: Optional[list[str]] = None,
    dissent_interpretation_ids: Optional[list[str]] = None,
    domain: str = "",
    persona: str = "",
    sensitivity: str = "",
    project_id: Optional[str] = None,
    grain: Optional[NarrativeGrain] = None,
    freshness_boundary: Optional[str] = None,
    supersedes_narrative_id: Optional[str] = None,
    preview_token: Optional[str] = None,
    require_preview_token: bool = False,
) -> Narrative:
    """Persist Narrative + fresh EpistemicState."""
    if not (committed_by or "").strip():
        raise CommitError("commit requires human actor (committed_by)")
    if not evidence_ids:
        raise CommitError("commit requires evidence_ids")
    if not (account or "").strip():
        raise CommitError("commit requires account text")

    from twin.cognize.acl import sensitivity_from_evidence

    derived_sens = sensitivity_from_evidence(store, evidence_ids)
    sensitivity = _pick_sensitivity(sensitivity or derived_sens, derived_sens)
    from twin.cognize.acl import evidence_source_sensors

    source_sensors = sorted(evidence_source_sensors(store, evidence_ids))

    expected = preview_commit_token(
        account=account,
        evidence_ids=evidence_ids,
        vault_id=vault_id,
        interpretation_ids=interpretation_ids,
        dissent_interpretation_ids=dissent_interpretation_ids,
        domain=domain,
    )
    if require_preview_token or preview_token is not None:
        if not preview_token or preview_token != expected:
            raise CommitError("commit preview_token mismatch — re-run preview")

    all_evidence = list(evidence_ids)
    for iid in dissent_interpretation_ids or []:
        intp = (
            store.get_cognize_interpretation(iid)
            if hasattr(store, "get_cognize_interpretation")
            else None
        )
        if intp is not None:
            for eid in intp.evidence_ids or []:
                if eid not in all_evidence:
                    all_evidence.append(eid)

    eps = EpistemicState(
        status=EpistemicStatus.fresh,
        synthesized_at=now_iso(),
        freshness_boundary=freshness_boundary or now_iso(),
        unseen_since=[],
        evidence_ids=all_evidence,
        stale_reason="",
    )
    store.upsert_epistemic_state(eps)

    nar = Narrative(
        vault_id=vault_id,
        account=account.strip(),
        grain=grain,
        status=NarrativeStatus.committed,
        epistemic_state_id=eps.id,
        evidence_ids=all_evidence,
        domain=domain,
        persona=persona,
        sensitivity=sensitivity,
        project_id=project_id,
        committed_by=committed_by.strip(),
        metadata={
            "preview_token": expected,
            "supersedes_narrative_id": supersedes_narrative_id or "",
            "source_sensors": source_sensors,
        },
    )
    store.upsert_narrative(nar)

    if supersedes_narrative_id and hasattr(store, "get_narrative"):
        prior = store.get_narrative(supersedes_narrative_id)
        if prior is not None and prior.epistemic_state_id:
            prior_eps = store.get_epistemic_state(prior.epistemic_state_id)
            if prior_eps is not None:
                store.upsert_epistemic_state(
                    prior_eps.model_copy(
                        update={
                            "status": EpistemicStatus.superseded,
                            "stale_reason": f"superseded by {nar.id}",
                        }
                    )
                )
            store.upsert_narrative(
                prior.model_copy(update={"status": NarrativeStatus.superseded})
            )

    for iid in interpretation_ids or []:
        intp = store.get_cognize_interpretation(iid)
        if intp is None:
            continue
        store.upsert_interpretation(
            intp.model_copy(
                update={
                    "status": InterpretationStatus.committed,
                    "updated_at": now_iso(),
                }
            )
        )
    for iid in dissent_interpretation_ids or []:
        intp = store.get_cognize_interpretation(iid)
        if intp is None:
            continue
        store.upsert_interpretation(
            intp.model_copy(
                update={
                    "status": InterpretationStatus.superseded,
                    "updated_at": now_iso(),
                }
            )
        )
    try:
        from twin.cognize.stages_late import draft_stance_after_commit

        draft_stance_after_commit(store, nar.id, domain=domain or None)
    except Exception:
        pass
    return nar


def resynthesize_narrative(
    store: Any,
    narrative_id: str,
    *,
    account: str,
    evidence_ids: list[str],
    committed_by: str,
    freshness_boundary: Optional[str] = None,
) -> Narrative:
    """Update account text and clear stale on an existing Narrative."""
    nar = store.get_narrative(narrative_id)
    if nar is None:
        raise CommitError(f"narrative not found: {narrative_id}")
    if not (committed_by or "").strip():
        raise CommitError("resynthesize requires human actor (committed_by)")
    if not evidence_ids:
        raise CommitError("resynthesize requires evidence_ids")
    if not nar.epistemic_state_id:
        raise CommitError("narrative missing epistemic_state_id")
    store.mark_epistemic_fresh(
        nar.epistemic_state_id,
        evidence_ids=list(evidence_ids),
        freshness_boundary=freshness_boundary or now_iso(),
        synthesized_at=now_iso(),
    )
    updated = nar.model_copy(
        update={
            "account": account.strip(),
            "evidence_ids": list(evidence_ids),
            "committed_by": committed_by.strip(),
            "status": NarrativeStatus.committed,
        }
    )
    store.upsert_narrative(updated)
    return updated
