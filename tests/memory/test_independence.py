"""Independent-source counting — the honest 'support' behind a claim.

Two evidences from the same episode collapse to one source; a cross-sense
neighbor (a Slack symptom next to a GitHub fix) is a genuine second source.
"""

from __future__ import annotations

from twin.clock import now_iso
from twin.memory.formation import propose_or_corroborate
from twin.memory.models import MemoryItem, MemoryType
from twin.memory.provenance import (
    attach_corroborating_evidence,
    count_independent_sources,
    memory_source_keys,
)
from twin.sensory.percept import Percept


def _percept(store, text, sensor="test"):
    p = Percept(
        percept_type="note",
        source_sensor=sensor,
        occurred_at=now_iso(),
        ingested_at=now_iso(),
        content=text,
        source_trust=0.9,
        source_scope="technical",
    )
    p.seal()
    store.insert_percept(p)
    return p


def _mem(title):
    return MemoryItem(
        id="tmp",
        type=MemoryType.decision,
        title=title,
        summary=title,
        domain="technical",
        confidence=0.6,
    )


def test_same_episode_counts_as_one_source(store):
    p1 = _percept(store, "PR: add webhook idempotency")
    p2 = _percept(store, "commit: idempotency key on webhook")
    mem, action = propose_or_corroborate(
        store, _mem("Webhook idempotency"),
        percept_id=p1.id, evidence_quote="add idempotency",
        independence_group="episode:EP1",
    )
    assert action == "created"
    # a second evidence from the *same* episode is not a new source
    attach_corroborating_evidence(
        store, mem.id, p2.id, "idempotency key",
        independence_group="episode:EP1",
    )
    assert count_independent_sources(store, [mem.id]) == 1


def test_cross_sense_counts_as_two_sources(store):
    p_gh = _percept(store, "PR: fix double charge", sensor="github")
    p_slack = _percept(store, "ops: customers double charged", sensor="slack")
    mem, _ = propose_or_corroborate(
        store, _mem("Double-charge fix"),
        percept_id=p_gh.id, evidence_quote="fix double charge",
        independence_group="episode:EP2",
    )
    # a genuinely different sense/record → a real second source
    attach_corroborating_evidence(
        store, mem.id, p_slack.id, "double charged",
        independence_group="xsense:slack:rec1",
    )
    assert count_independent_sources(store, [mem.id]) == 2
    keys = memory_source_keys(store, mem.id)
    assert any(k.startswith("xsense:") for k in keys)


def test_counting_accepts_ids_and_objects(store):
    p = _percept(store, "some decision")
    mem, _ = propose_or_corroborate(
        store, _mem("Decision"), percept_id=p.id,
        evidence_quote="decision", independence_group="episode:EP3",
    )
    reloaded = store.get_memory(mem.id)
    assert count_independent_sources(store, [mem.id]) == 1
    assert count_independent_sources(store, [reloaded]) == 1


def test_fallback_to_episode_when_no_evidence_groups(store):
    # a memory with no evidence rows falls back to its own episode origin
    mem = _mem("No-evidence claim")
    mem.id = "mem_noevidence"
    mem.payload = {"episode_id": "EP_fallback"}
    store.insert_memory(mem)
    assert memory_source_keys(store, "mem_noevidence") == {"episode:EP_fallback"}
    assert count_independent_sources(store, ["mem_noevidence"]) == 1
