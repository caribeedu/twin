"""Native pack extras include v2 epistemic contract."""

from __future__ import annotations

from twin.cognize.commit import commit_narrative
from twin.cognize.models import EpistemicStatus
from twin.cognition.context_pack import build_context_pack
from twin.interfaces.native.service import _pack_extras
from twin.memory.embeddings import HashEmbedder
from twin.sensory.percept import Percept


def test_native_pack_extras_include_epistemic_fields(store, cfg):
    nar = commit_narrative(
        store,
        account="Native pack must carry epistemic status",
        vault_id="default",
        evidence_ids=["ev_n1"],
        committed_by="tester",
        domain="technical",
    )
    pack = build_context_pack(
        store, cfg, HashEmbedder(),
        query="status",
        target_domain="technical",
    )
    extras = _pack_extras(pack)
    assert "narratives" in extras
    assert "derived_confidence" in extras
    assert "epistemic" in extras
    entry = next(n for n in extras["narratives"] if n["narrative_id"] == nar.id)
    assert entry["epistemic_status"] == "fresh"

    newer = Percept(
        percept_type="message",
        source_sensor="slack",
        content="contradiction arrives",
        metadata={"vault_id": "default", "domain": "technical"},
    )
    store.insert_percept(newer)
    assert store.get_epistemic_state(nar.epistemic_state_id).status is EpistemicStatus.stale

    pack2 = build_context_pack(
        store, cfg, HashEmbedder(),
        query="status",
        target_domain="technical",
    )
    extras2 = _pack_extras(pack2)
    entry2 = next(n for n in extras2["narratives"] if n["narrative_id"] == nar.id)
    assert entry2["epistemic_status"] == "stale"
    assert entry2.get("account") is None
