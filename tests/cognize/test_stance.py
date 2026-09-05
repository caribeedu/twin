"""Stance alias lineage and pending-proposal mapping."""

from __future__ import annotations

from twin import ids
from twin.clock import now_iso
from twin.cognize.stance import judgment_to_stance, proposal_to_stance
from twin.cognize.stance_engine.models import (
    JudgmentItem,
    JudgmentKind,
    JudgmentProposal,
    JudgmentProvenance,
    ProposalAction,
    ProposalStatus,
)
from twin.cognize.stance_engine.proposals import propose_from_narrative
from twin.cognize.commit import commit_narrative


def test_judgment_to_stance_carries_narrative_lineage():
    item = JudgmentItem(
        id=ids.judgment_id(),
        kind=JudgmentKind.heuristic,
        statement="Prefer explicit review gates",
        provenance=JudgmentProvenance(
            narrative_ids=["nar_abc"],
            evidence_ids=["ev_1"],
            source="narrative_stance",
        ),
        metadata={"narrative_id": "nar_abc"},
        created_at=now_iso(),
        updated_at=now_iso(),
    )
    st = judgment_to_stance(item, vault_id="vault_general")
    assert st.narrative_ids == ["nar_abc"]
    assert st.evidence_ids == ["ev_1"]
    dump = st.model_dump(mode="json")
    assert dump["narrative_ids"] == ["nar_abc"]


def test_proposal_to_stance_carries_lineage():
    prop = JudgmentProposal(
        id=ids.judgment_proposal_id(),
        action=ProposalAction.create,
        status=ProposalStatus.pending,
        proposed_item={
            "kind": JudgmentKind.preference.value,
            "statement": "Ship behind a preview token",
            "provenance": {
                "narrative_ids": ["nar_xyz"],
                "evidence_ids": ["p1"],
            },
        },
        reason="test",
        created_at=now_iso(),
        metadata={"narrative_id": "nar_xyz"},
    )
    st = proposal_to_stance(prop, vault_id="vault_general")
    assert st.id == prop.id
    assert st.status.value == "pending"
    assert st.narrative_ids == ["nar_xyz"]
    assert st.evidence_ids == ["p1"]


def test_propose_from_narrative_writes_lineage(store):
    nar = commit_narrative(
        store,
        account="Feature A unblocked launch",
        vault_id="default",
        evidence_ids=["ev_lineage"],
        committed_by="edu",
        domain="technical",
    )
    prop = propose_from_narrative(store, nar.id, domain="technical")
    assert prop is not None
    st = proposal_to_stance(prop)
    assert nar.id in st.narrative_ids
    assert "ev_lineage" in st.evidence_ids
    assert (prop.proposed_item or {}).get("provenance", {}).get("narrative_ids") == [nar.id]
