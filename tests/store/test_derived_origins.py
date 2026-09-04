"""Derived percept origin resolution for Explore lineage."""

from __future__ import annotations

from twin import ids
from twin.cognize.services.correlation.models import (
    EpisodeLink,
    EpisodeLinkKind,
    EpisodeLinkStatus,
    WorkEpisode,
)
from twin.sense.sensory.percept import Percept
from twin.store.models import Evidence, EvidenceType, StoreClaim, ClaimType, ClaimStatus
from twin.store.provenance import (
    derived_source_percept_ids,
    enrich_percept_dict,
    episode_member_percept_ids,
)


def test_episode_member_and_derived_sources(store):
    observed_a = Percept(
        id="pct_obs_a",
        percept_type="pull_request",
        source_sensor="github",
        content="PR body A",
    )
    observed_b = Percept(
        id="pct_obs_b",
        percept_type="commit",
        source_sensor="github",
        content="Commit body B",
    )
    store.insert_percept(observed_a)
    store.insert_percept(observed_b)

    # Minimal connector records so episode links resolve percept ids.
    from twin.sense.connectors.models import ConnectorRecord

    rec_a = ConnectorRecord(
        id="crec_a",
        connector_id="github",
        source_account_id="acc",
        external_type="pull_request",
        external_id="repo#1",
        idempotency_key="github:pr:repo#1",
        content="PR",
        percept_id=observed_a.id,
    )
    rec_b = ConnectorRecord(
        id="crec_b",
        connector_id="github",
        source_account_id="acc",
        external_type="commit",
        external_id="abc",
        idempotency_key="github:commit:abc",
        content="Commit",
        percept_id=observed_b.id,
    )
    store.insert_connector_record(rec_a)
    store.insert_connector_record(rec_b)

    ep = WorkEpisode(
        id="episode_test_origins",
        vault_id="vault_general",
        title="origin test",
        correlation_key="test-origins",
    )
    store.insert_work_episode(ep)
    store.insert_episode_link(
        EpisodeLink(
            episode_id=ep.id,
            vault_id="vault_general",
            connector_record_id=rec_a.id,
            external_type="pull_request",
            external_id="repo#1",
            kind=EpisodeLinkKind.explicit,
            status=EpisodeLinkStatus.active,
        )
    )
    store.insert_episode_link(
        EpisodeLink(
            episode_id=ep.id,
            vault_id="vault_general",
            connector_record_id=rec_b.id,
            external_type="commit",
            external_id="abc",
            kind=EpisodeLinkKind.explicit,
            status=EpisodeLinkStatus.active,
        )
    )

    members = episode_member_percept_ids(store, ep.id)
    assert set(members) == {observed_a.id, observed_b.id}

    derived = Percept(
        id="pct_reflect_testorigin",
        percept_type="derived_episode",
        source_sensor="episode_reflect",
        content="Derived reading",
        metadata={"episode_id": ep.id},
    )
    store.insert_percept(derived)

    sources = derived_source_percept_ids(store, derived)
    assert set(sources) == {observed_a.id, observed_b.id}

    enriched = enrich_percept_dict(store, derived.model_dump(mode="json"))
    assert set(enriched["source_percept_ids"]) == {observed_a.id, observed_b.id}
    assert len(enriched["origin_percepts"]) == 2


def test_claim_evidence_fallback_for_derived_sources(store):
    observed = Percept(
        id="pct_obs_claim",
        percept_type="document",
        source_sensor="documents",
        content="Observed doc",
    )
    derived = Percept(
        id="pct_derived_claimfall",
        percept_type="derived_episode",
        source_sensor="episode_reflect",
        content="Derived",
        metadata={},
    )
    store.insert_percept(observed)
    store.insert_percept(derived)

    mem = StoreClaim(
        id="mem_origin_test",
        type=ClaimType.decision,
        title="t",
        summary="s",
        status=ClaimStatus.candidate,
    )
    store.insert_claim(mem)
    store.insert_evidence(
        Evidence(
            id=ids.evidence_id(),
            claim_id=mem.id,
            percept_id=derived.id,
            quote="derived quote",
            evidence_type=EvidenceType.verbatim,
        )
    )
    store.insert_evidence(
        Evidence(
            id=ids.evidence_id(),
            claim_id=mem.id,
            percept_id=observed.id,
            quote="observed quote",
            evidence_type=EvidenceType.verbatim,
        )
    )

    assert derived_source_percept_ids(store, derived) == [observed.id]
