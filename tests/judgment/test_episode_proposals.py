"""Judgment proposals seeded from episode trajectory patterns."""

from __future__ import annotations

from twin import ids
from twin.cognize.stance_engine.proposals import (
    propose_from_episode,
    propose_from_episode_patterns,
)
from twin.store.models import CanonicalClaim, StoreClaim, ClaimStatus, ClaimType


def _confirmed_trajectory_memory(store, *, episode_id, title, summary,
                                 project_id=None, domain="technical"):
    mem = StoreClaim(
        id=ids.claim_id(),
        type=ClaimType.decision,
        title=title,
        summary=summary,
        domain=domain,
        confidence=0.7,
        status=ClaimStatus.confirmed,
        valid_from="2026-07-03T09:00:00Z",
        project_id=project_id,
        payload={
            "episode_id": episode_id,
            "source": "episode_reflect",
            "trajectory": True,
        },
        canonical_claim=CanonicalClaim(
            subject=project_id or title, predicate="changed_approach_to",
            object="SQS",
        ),
    )
    store.insert_claim(mem)
    return mem


def test_propose_from_episode_requires_confirmed(store):
    # no confirmed memories → nothing to generalize
    assert propose_from_episode(store, "episode_missing") is None


def test_propose_from_episode_creates_pending_proposal(store):
    ep = "episode_abc"
    m = _confirmed_trajectory_memory(
        store, episode_id=ep,
        title="Changed course: Kafka → SQS",
        summary="Intended Kafka, later chose SQS for the queue.",
        project_id="proj_atlas",
    )
    proposal = propose_from_episode(store, ep)
    assert proposal is not None
    assert proposal.status.value == "pending"
    assert m.id in proposal.supporting_claim_ids
    assert proposal.proposed_item["provenance"]["source"] == "episode_pattern"
    assert proposal.metadata.get("episode_id") == ep


def test_propose_from_episode_support_counts_independent_sources(store):
    # two confirmed trajectory claims from the SAME episode → one source,
    # not "support=2" (the memory count is surfaced separately).
    ep = "episode_shared"
    _confirmed_trajectory_memory(
        store, episode_id=ep, title="Kafka → SQS",
        summary="pivoted the queue", project_id="proj_atlas",
    )
    _confirmed_trajectory_memory(
        store, episode_id=ep, title="Chose SQS for cost",
        summary="reasoned on operational cost", project_id="proj_atlas",
    )
    proposal = propose_from_episode(store, ep)
    assert proposal is not None
    assert proposal.support_count == 1
    assert proposal.metadata.get("memory_count") == 2
    assert proposal.metadata.get("independent_sources") == 1


def test_propose_from_episode_patterns_needs_multiple_episodes(store):
    _confirmed_trajectory_memory(
        store, episode_id="ep1", title="A → B",
        summary="pivoted once", project_id="p1",
    )
    # one episode only → below min_episodes
    assert propose_from_episode_patterns(store) == []

    _confirmed_trajectory_memory(
        store, episode_id="ep2", title="C → D",
        summary="pivoted again", project_id="p2",
    )
    proposals = propose_from_episode_patterns(store)
    assert len(proposals) == 1
    assert proposals[0].metadata.get("detector") == "episode_pattern"
    assert proposals[0].support_count == 2
