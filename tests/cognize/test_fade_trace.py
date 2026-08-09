"""Fade recommendations + pack Trace ledger."""

from __future__ import annotations

from twin.cognize.commit import commit_narrative
from twin.cognize.fade import recommend_accessibility
from twin.cognize.models import NarrativeStatus
from twin.cognition.context_pack import build_context_pack
from twin.judgment.proposals import propose_from_narrative
from twin.memory.embeddings import HashEmbedder


def test_pack_serve_writes_trace(store, cfg):
    nar = commit_narrative(
        store,
        account="Tracked narrative",
        vault_id="default",
        evidence_ids=["ev_t1"],
        committed_by="tester",
        domain="technical",
    )
    build_context_pack(
        store, cfg, HashEmbedder(),
        query="tracked",
        target_domain="technical",
    )
    traces = store.list_traces("default", event_kind="pack_serve", resource_id=nar.id)
    assert traces
    assert traces[0].resource_kind == "narrative"


def test_fade_recommends_remarkable_when_stance_linked(store):
    nar = commit_narrative(
        store,
        account="Prefer reversible infra",
        vault_id="default",
        evidence_ids=["ev_f1"],
        committed_by="tester",
        domain="technical",
    )
    propose_from_narrative(store, nar.id)
    recs = recommend_accessibility(store, vault_id="default", dry_run=False)
    hit = next(r for r in recs if r["narrative_id"] == nar.id)
    assert hit["recommended"] == NarrativeStatus.remarkable.value
    assert hit["stance_linked"] is True
    loaded = store.get_narrative(nar.id)
    assert (loaded.metadata or {}).get("accessibility_recommendation")
    assert loaded.status is NarrativeStatus.committed  # not silently archived
