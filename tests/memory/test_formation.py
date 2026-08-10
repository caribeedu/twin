"""Memory formation — deterministic identity, corroborate, confirm/reject/restore."""

from twin.clock import now_iso
from twin.memory.formation import (
    FormationState,
    as_candidate,
    confirm_candidate,
    formation_identity,
    memory_id_for_identity,
    propose_or_corroborate,
    reject_candidate,
    restore_candidate,
)
from twin.memory.models import Evidence, MemoryItem, MemoryStatus, MemoryType
from twin.sense.sensory.percept import Percept


def _seed_percept(store, text="We decided to use SQLite for local store."):
    p = Percept(
        percept_type="note",
        source_sensor="test",
        occurred_at=now_iso(),
        ingested_at=now_iso(),
        content=text,
        source_trust=0.9,
        source_scope="technical",
    )
    p.seal()
    store.insert_percept(p)
    return p


def test_formation_identity_stable():
    a = formation_identity(
        type_="decision", domain="technical", project_id="p1",
        title="Use SQLite", summary="Local store is SQLite",
    )
    b = formation_identity(
        type_="decision", domain="technical", project_id="p1",
        title="Use SQLite", summary="Local store is SQLite",
    )
    c = formation_identity(
        type_="decision", domain="technical", project_id="p1",
        title="Use Postgres", summary="Local store is Postgres",
    )
    assert a == b
    assert a != c
    assert memory_id_for_identity(a).startswith("mem_f")


def test_propose_idempotent_corroborates(store):
    p1 = _seed_percept(store, "Decision: use SQLite.")
    p2 = _seed_percept(store, "Again: we use SQLite locally.")
    mem = MemoryItem(
        id="tmp",
        type=MemoryType.decision,
        title="Use SQLite",
        summary="Local store is SQLite",
        domain="technical",
        confidence=0.9,
    )
    first, action1 = propose_or_corroborate(
        store, mem, percept_id=p1.id, evidence_quote="use SQLite",
    )
    second, action2 = propose_or_corroborate(
        store, mem.model_copy(deep=True), percept_id=p2.id,
        evidence_quote="use SQLite locally",
    )
    assert action1 == "created"
    assert action2 == "corroborated"
    assert first.id == second.id
    assert (second.payload or {}).get("corroboration_count") == 1
    assert len(store.get_evidence(first.id)) == 2
    assert as_candidate(store, second).formation_state == FormationState.corroborating


def test_confirm_requires_evidence(store):
    mem = MemoryItem(
        id="mem_noev",
        type=MemoryType.fact,
        title="No evidence",
        summary="Should not confirm",
        domain="technical",
        status=MemoryStatus.candidate,
        confidence=0.9,
    )
    store.insert_memory(mem)
    try:
        confirm_candidate(store, mem.id)
        assert False, "expected error"
    except ValueError as exc:
        assert "no evidence" in str(exc)


def test_confirm_reject_restore_with_reason(store):
    p = _seed_percept(store)
    mem = MemoryItem(
        id="tmp",
        type=MemoryType.fact,
        title="Twin uses hash embedder in tests",
        summary="Offline tests use hash embedder",
        domain="technical",
        confidence=0.9,
    )
    created, _ = propose_or_corroborate(
        store, mem, percept_id=p.id, evidence_quote=p.content,
    )
    confirmed = confirm_candidate(store, created.id, note="looks good")
    assert confirmed.formation_state == FormationState.confirmed
    assert confirmed.memory.status == MemoryStatus.confirmed

    # cannot reject confirmed via formation reject
    try:
        reject_candidate(store, created.id, reason="nope")
        assert False
    except ValueError:
        pass

    # fresh candidate → reject with reason → restore
    p2 = _seed_percept(store, "Belief: purple is best.")
    belief = MemoryItem(
        id="tmp2",
        type=MemoryType.belief,
        title="Purple is best",
        summary="User likes purple themes",
        domain="technical",
        confidence=0.95,
    )
    b, _ = propose_or_corroborate(
        store, belief, percept_id=p2.id, evidence_quote=p2.content,
    )
    assert b.needs_review  # belief policy always_review
    rejected = reject_candidate(store, b.id, reason="not a durable belief")
    assert rejected.formation_state == FormationState.rejected
    assert rejected.reject_reason == "not a durable belief"
    restored = restore_candidate(store, b.id)
    assert restored.formation_state == FormationState.awaiting_review
    assert restored.memory.status == MemoryStatus.candidate


def test_belief_never_auto_confirmed_by_formation(store):
    p = _seed_percept(store, "I believe we should always write tests.")
    mem = MemoryItem(
        id="tmp",
        type=MemoryType.belief,
        title="Always write tests",
        summary="Team belief about testing",
        domain="technical",
        confidence=0.99,
    )
    out, action = propose_or_corroborate(
        store, mem, percept_id=p.id, evidence_quote=p.content,
    )
    assert action == "created"
    assert out.status == MemoryStatus.candidate
    assert out.needs_review
