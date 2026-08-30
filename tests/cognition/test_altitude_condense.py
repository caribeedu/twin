"""Altitude scoring + near-duplicate condensation."""
from __future__ import annotations

from twin import ids
from twin.cognize.services.condense import condense_near_duplicates
from twin.cognize.services.interpreter.reflect_prompt import _coerce_claim_type
from twin.cognize.services.quality import analyze_claim, claim_altitude
from twin.store.models import FindingType, StoreClaim, ReviewFinding


def _mem(store, embedder, **kw):
    base = dict(
        id=ids.claim_id(), type="fact", title="t", summary="s",
        domain="technical", confidence=0.9, status="candidate",
        needs_review=True, project_id="proj_x",
    )
    base.update(kw)
    mem = StoreClaim(**base)
    store.insert_claim(mem)
    store.store_embedding(
        mem.id, "claim", embedder.name,
        embedder.embed(f"{mem.title}\n{mem.summary}"),
    )
    return mem


def test_trajectory_constraint_is_stance():
    mem = StoreClaim(
        id="m1", type="constraint", title="launch gate",
        summary="Must have presets to launch; resolved by PR #11.",
        domain="technical",
        payload={"trajectory": True, "source": "episode_reflect",
                 "phase_keys": ["goal:a", "execution:b"]},
    )
    assert claim_altitude(mem) == "stance"


def test_atomic_fact_is_ground():
    mem = StoreClaim(
        id="m2", type="fact", title="sha abc",
        summary="Commit landed.", domain="technical", payload={},
    )
    assert claim_altitude(mem) == "ground"


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
    rg = analyze_claim(store, embedder, ground.id)
    rs = analyze_claim(store, embedder, stance.id)
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
        id=ids.finding_id(), claim_id=a.id,
        type=FindingType.near_duplicate, related_claim_id=b.id,
        confidence=0.92, reason="near dup",
    )])
    store.replace_findings(b.id, [ReviewFinding(
        id=ids.finding_id(), claim_id=b.id,
        type=FindingType.near_duplicate, related_claim_id=a.id,
        confidence=0.92, reason="near dup",
    )])
    a.quality_flags = ["near_duplicate"]
    b.quality_flags = ["near_duplicate"]
    store.update_claim(a.id, quality_flags=["near_duplicate"])
    store.update_claim(b.id, quality_flags=["near_duplicate"])

    report = condense_near_duplicates(
        store, embedder, claim_ids=[a.id, b.id],
    )
    assert report.merged == 1
    assert len(report.survivor_ids) == 1
    survivor = store.get_claim(report.survivor_ids[0])
    assert survivor is not None
    assert survivor.status.value == "candidate"
    assert store.get_claim(a.id).status.value == "merged"
    assert store.get_claim(b.id).status.value == "merged"
