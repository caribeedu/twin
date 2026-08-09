"""Commit, stale latch, pack floor, migrate tests."""

from __future__ import annotations

from twin.cognize.commit import CommitError, commit_narrative
from twin.cognize.migrate import backfill_from_memories
from twin.cognize.models import EpistemicStatus
from twin.cognition.context_pack import build_context_pack
from twin.memory.embeddings import HashEmbedder
from twin.memory.models import MemoryItem, MemoryStatus, MemoryType, Sensitivity
from twin.sensory.percept import Percept


def test_commit_requires_evidence_and_actor(store):
    try:
        commit_narrative(
            store,
            account="x",
            vault_id="default",
            evidence_ids=[],
            committed_by="user",
        )
        assert False, "expected CommitError"
    except CommitError:
        pass
    try:
        commit_narrative(
            store,
            account="x",
            vault_id="default",
            evidence_ids=["e1"],
            committed_by="",
        )
        assert False, "expected CommitError"
    except CommitError:
        pass


def test_commit_and_stale_on_new_percept(store):
    nar = commit_narrative(
        store,
        account="Feature A unblocked launch",
        vault_id="default",
        evidence_ids=["ev_1"],
        committed_by="edu",
        domain="technical",
    )
    eps = store.get_epistemic_state(nar.epistemic_state_id)
    assert eps.status is EpistemicStatus.fresh

    p = Percept(
        percept_type="message",
        source_sensor="slack",
        content="Actually we reverted Feature A",
        metadata={"vault_id": "default", "domain": "technical"},
    )
    assert store.insert_percept(p) == p.id
    eps2 = store.get_epistemic_state(nar.epistemic_state_id)
    assert eps2.status is EpistemicStatus.stale
    assert p.id in eps2.unseen_since


def test_pack_withholds_stale_as_fresh(store, cfg):
    nar = commit_narrative(
        store,
        account="Old world",
        vault_id="default",
        evidence_ids=["ev_1"],
        committed_by="edu",
        domain="technical",
    )
    store.mark_epistemic_stale(
        nar.epistemic_state_id, reason="test", unseen_percept_id="p_new"
    )
    pack = build_context_pack(
        store, cfg, HashEmbedder(), query="launch", target_domain="technical",
    )
    stale_entries = [n for n in pack.narratives if n["narrative_id"] == nar.id]
    assert stale_entries
    assert stale_entries[0]["epistemic_status"] == "stale"
    assert stale_entries[0]["account"] is None
    if "## Narratives" in (pack.context_pack or ""):
        fresh = (pack.context_pack or "").split("## Narratives")[-1].split("## Stale")[0]
        assert "Old world" not in fresh


def test_backfill_dry_run(store):
    from twin import ids

    mem = MemoryItem(
        id=ids.memory_id(),
        type=MemoryType.decision,
        title="Use Postgres",
        summary="Chose Postgres outbox",
        domain="technical",
        persona="developer",
        sensitivity=Sensitivity.internal,
        confidence=0.9,
        status=MemoryStatus.confirmed,
        needs_review=False,
    )
    store.insert_memory(mem)
    stats = backfill_from_memories(store, vault_id="default", dry_run=True)
    assert stats["narratives"] >= 1
    assert store.list_narratives("default") == []
    stats2 = backfill_from_memories(store, vault_id="default", dry_run=False)
    assert stats2["narratives"] >= 1
    assert store.list_narratives("default")
