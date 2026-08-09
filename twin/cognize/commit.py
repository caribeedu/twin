"""Commit Narrative after human review (Stage 9)."""

from __future__ import annotations

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
from twin.clock import now_iso


class CommitError(ValueError):
    pass


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
    sensitivity: str = "internal",
    project_id: Optional[str] = None,
    grain: Optional[NarrativeGrain] = None,
    freshness_boundary: Optional[str] = None,
) -> Narrative:
    """Persist Narrative + fresh EpistemicState. Human actor required."""
    if not (committed_by or "").strip():
        raise CommitError("commit requires human actor (committed_by)")
    if not evidence_ids:
        raise CommitError("commit requires evidence_ids")
    if not (account or "").strip():
        raise CommitError("commit requires account text")

    all_evidence = list(evidence_ids)
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
    )
    store.upsert_narrative(nar)

    for iid in interpretation_ids or []:
        intp = store.get_interpretation(iid)
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
        intp = store.get_interpretation(iid)
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
    return nar
