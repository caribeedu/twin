"""Altitude scoring + near-duplicate condensation."""
from __future__ import annotations

from twin import ids
from twin.cognition.condense import condense_near_duplicates
from twin.cognition.interpreter.reflect_prompt import _coerce_claim_type
from twin.cognition.quality import analyze_memory, memory_altitude
from twin.store.models import FindingType, MemoryItem, ReviewFinding


def _mem(store, embedder, **kw):
    base = dict(
        id=ids.memory_id(), type="fact", title="t", summary="s",
        domain="technical", confidence=0.9, status="candidate",
        needs_review=True, project_id="proj_x",
    )
    base.update(kw)
    mem = MemoryItem(**base)
    store.insert_memory(mem)
    store.store_embedding(
        mem.id, "memory", embedder.name,
        embedder.embed(f"{mem.title}\n{mem.summary}"),
    )
    return mem


def test_trajectory_constraint_is_stance():
    mem = MemoryItem(
        id="m1", type="constraint", title="launch gate",
        summary="Must have presets to launch; resolved by PR #11.",
        domain="technical",
        payload={"trajectory": True, "source": "episode_reflect",
                 "phase_keys": ["goal:a", "execution:b"]},
    )
    assert memory_altitude(mem) == "stance"


def test_atomic_fact_is_ground():
    mem = MemoryItem(
        id="m2", type="fact", title="sha abc",
        summary="Commit landed.", domain="technical", payload={},
    )
    assert memory_altitude(mem) == "ground"


def test_stance_outscores_ground_quality(store, embedder):
    ground = _mem(
        store, embedder,
        title="Commit note", summary="A commit message about presets.",
        type="fact", confidence=0.95,
    )
    stance = _mem(
        store, embedder,
        title="Presets are a launch gate — resolved by PR #11",
        summary=(
            "Slack required presets and roles before launch; "
            "PR #11 delivered the management panels."
        ),
        type="constraint", confidence=0.87,
        payload={"trajectory": True, "source": "episode_reflect",
                 "phase_keys": ["goal:m", "execution:pr"]},
    )
    rg = analyze_memory(store, embedder, ground.id)
    rs = analyze_memory(store, embedder, stance.id)
    assert rs.altitude == "stance"
    assert rg.altitude == "ground"
    assert rs.quality_score > rg.quality_score


def test_coerce_fulfilled_requirement_not_decision():
    assert _coerce_claim_type(
        "decision",
        title="presets requirement fulfilled: launch blocker resolved",
        summary="Slack required presets; PR #15 cleared the launch gate.",
    ) in ("event", "constraint")


def test_condense_merges_near_duplicates(store, embedder):
    a = _mem(
        store, embedder,
        title="Launch gate: presets required",
        summary="Dogwalker needs presets and roles before launch.",
        type="constraint",
        payload={"trajectory": True, "source": "episode_reflect"},
    )
    b = _mem(
        store, embedder,
        title="Presets/roles are a hard launch gate",
        summary="Dogwalker needs presets and roles before launch.",
        type="constraint",
        payload={"trajectory": True, "source": "episode_reflect"},
    )
    # Seed findings as the quality analyzer would.
    store.replace_findings(a.id, [ReviewFinding(
        id=ids.finding_id(), memory_id=a.id,
        type=FindingType.near_duplicate, related_memory_id=b.id,
        confidence=0.92, reason="near dup",
    )])
    store.replace_findings(b.id, [ReviewFinding(
        id=ids.finding_id(), memory_id=b.id,
        type=FindingType.near_duplicate, related_memory_id=a.id,
        confidence=0.92, reason="near dup",
    )])
    a.quality_flags = ["near_duplicate"]
    b.quality_flags = ["near_duplicate"]
    store.update_memory(a.id, quality_flags=["near_duplicate"])
    store.update_memory(b.id, quality_flags=["near_duplicate"])

    report = condense_near_duplicates(
        store, embedder, memory_ids=[a.id, b.id],
    )
    assert report.merged == 1
    assert len(report.survivor_ids) == 1
    survivor = store.get_memory(report.survivor_ids[0])
    assert survivor is not None
    assert survivor.status.value == "candidate"
    assert store.get_memory(a.id).status.value == "merged"
    assert store.get_memory(b.id).status.value == "merged"
