"""Eval: stale injection floor (§9.3 #1 / Twin v2.0 gate)."""

from __future__ import annotations

from twin.cognize.commit import commit_narrative
from twin.cognize.models import EpistemicStatus
from twin.inject.context_pack import build_context_pack
from twin.store.embeddings import HashEmbedder
from twin.sense.sensory.percept import Percept


def test_eval_stale_injection(store, cfg):
    nar = commit_narrative(
        store,
        account="Launch is blocked on Feature A",
        vault_id="default",
        evidence_ids=["ev_slack_1"],
        committed_by="eval",
        domain="technical",
    )
    assert store.get_epistemic_state(nar.epistemic_state_id).status is EpistemicStatus.fresh

    newer = Percept(
        percept_type="message",
        source_sensor="slack",
        content="Feature A shipped; blocker cleared",
        metadata={"vault_id": "default", "domain": "technical"},
    )
    store.insert_percept(newer)
    eps = store.get_epistemic_state(nar.epistemic_state_id)
    assert eps.status is EpistemicStatus.stale, "Narrative not marked stale after newer Percept"
    assert newer.id in eps.unseen_since

    pack = build_context_pack(
        store, cfg, HashEmbedder(),
        query="What is the status of Feature A launch blocker?",
        target_domain="technical",
    )
    entry = next(n for n in pack.narratives if n["narrative_id"] == nar.id)
    assert entry["epistemic_status"] == "stale"
    assert entry["account"] is None
    assert entry.get("account_omitted") is True
    fresh_section = ""
    text = pack.context_pack or ""
    if "## Narratives" in text:
        fresh_section = text.split("## Narratives", 1)[1].split("## Stale", 1)[0]
    assert "Launch is blocked on Feature A" not in fresh_section
