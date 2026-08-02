"""Episode phases + narrative edges built by the cortex cognition stage.

Since v1.3.0 phases/edges are produced by LLM stages, not lexical rules. Tests
inject deterministic stage overrides (``amygdala`` classify, ``cortex``
understand) standing in for the model — the golden pivot fixture.
"""

from __future__ import annotations

import pytest

from twin.cognition import BrainStage, run_episode_cognition, set_stage_override
from twin.cognition.correlation.edges import confirm_edge
from twin.cognition.correlation.explain import explain_episode
from twin.cognition.correlation.models import (
    EpisodeEdgeRelation,
    EpisodeEdgeStatus,
    EpisodePhaseKind,
)
from twin.cognition.correlation.service import run_correlation_pass
from twin.connectors.models import (
    ConnectorInstance,
    ConnectorRecord,
    ConnectorStatus,
    OwnershipClass,
    SourceAccount,
    idempotency_key,
)

_OUTCOME_WORDS = ("merged", "shipped", "released", "closed", "resolved", "landed")
_PIVOT_WORDS = ("revert", "instead", "switch to", "supersed", "pivot", "abandon")


def _classify(members, cfg):
    """Stand-in amygdala: assign a role per member (simulates the LLM)."""
    roles = {}
    for m in members:
        t = (m.get("external_type") or "").lower()
        ex = (m.get("excerpt") or "").lower()
        if any(w in ex for w in _OUTCOME_WORDS):
            kind = "outcome"
        elif t in ("issue", "discussion", "epic", "story"):
            kind = "goal"
        elif t in ("pull_request", "review", "merge_request", "proposal", "rfc"):
            kind = "decision"
        elif t in ("commit", "push", "deploy", "build"):
            kind = "execution"
        else:
            kind = "other"
        roles[m["ref"]] = {"kind": kind, "salience": 0.6}
    return roles


def _understand(phases, quotes, cfg):
    """Stand-in cortex: propose narrative edges over the phase arc."""
    ordered = sorted(phases, key=lambda p: p.get("order", 0))
    edges = []
    for a, b in zip(ordered, ordered[1:]):
        rel = "continues"
        if a["kind"] in ("goal", "decision") and b["kind"] in ("decision", "execution"):
            rel = "motivated"
        edges.append({
            "from_key": a["phase_key"], "to_key": b["phase_key"],
            "relation": rel, "confidence": 0.6, "evidence_quote": a.get("summary") or "",
        })
    decisions = [p for p in ordered if p["kind"] == "decision"]
    for earlier, later in zip(decisions, decisions[1:]):
        text = (later.get("summary") or "") + " " + " ".join(
            quotes.get(r, "") for r in later.get("members", [])
        )
        if any(w in text.lower() for w in _PIVOT_WORDS):
            edges.append({
                "from_key": earlier["phase_key"], "to_key": later["phase_key"],
                "relation": "superseded", "confidence": 0.7,
                "evidence_quote": later.get("summary") or "",
            })
    for p in ordered:
        if p["kind"] != "outcome":
            continue
        for prior in ordered:
            if prior["order"] < p["order"] and prior["kind"] in ("goal", "decision"):
                edges.append({
                    "from_key": prior["phase_key"], "to_key": p["phase_key"],
                    "relation": "resolved", "confidence": 0.55,
                    "evidence_quote": p.get("summary") or "",
                })
    return edges


@pytest.fixture(autouse=True)
def _pivot_cognition(_reset_interpreter_override):
    set_stage_override(BrainStage.amygdala, _classify)
    set_stage_override(BrainStage.cortex, _understand)
    yield
    set_stage_override(BrainStage.amygdala, None)
    set_stage_override(BrainStage.cortex, None)


def _cortex(store, cfg, embedder):
    """Run sensory → cortex over the whole store (builds phases + edges)."""
    return run_episode_cognition(
        store, cfg, embedder, mode="full", until=BrainStage.cortex,
    )


def _acct(store, *, vault_id="vault_work_acme", account_id="acct_ph"):
    acc = SourceAccount(
        id=account_id,
        connector_type="github",
        external_account_id=account_id,
        owner_principal_id="p1",
        source_owner=OwnershipClass.employer,
        vault_id=vault_id,
        org_key="acme",
    )
    store.insert_source_account(acc)
    inst = ConnectorInstance(
        id=f"conn_{account_id}",
        connector_type="github",
        account_id=acc.id,
        status=ConnectorStatus.active,
    )
    store.insert_connector_instance(inst)
    return acc, inst


def _rec(**kwargs) -> ConnectorRecord:
    defaults = dict(
        connector_id="conn_1",
        source_account_id="acct_1",
        external_type="pull_request",
        external_id="pr-1",
        external_revision="1",
        content="hello",
        actor_ids=[],
        participant_ids=[],
        source_metadata={},
        ownership={},
    )
    defaults.update(kwargs)
    rec = ConnectorRecord(**defaults)
    if not rec.idempotency_key:
        rec.idempotency_key = idempotency_key(
            "test", rec.source_account_id, rec.external_type,
            rec.external_id, rec.external_revision,
        )
    return rec


def _arc(store, acc, inst, lineage="github:acme/atlas#42"):
    """Issue → PR → commits → merge on one lineage."""
    issue = _rec(
        id="r_issue", connector_id=inst.id, source_account_id=acc.id,
        external_type="issue", external_id="acme/atlas#42",
        content="Need a durable queue for events",
        occurred_at="2026-07-01T09:00:00Z",
        ownership={"vault_id": acc.vault_id},
        source_metadata={"lineage_root": lineage, "repo": "acme/atlas"},
    )
    pr = _rec(
        id="r_pr", connector_id=inst.id, source_account_id=acc.id,
        external_type="pull_request", external_id="acme/atlas!100",
        content="# Use SQS for the queue\n\nProposing SQS.",
        occurred_at="2026-07-02T10:00:00Z",
        ownership={"vault_id": acc.vault_id},
        source_metadata={"lineage_root": lineage, "repo": "acme/atlas"},
    )
    commit = _rec(
        id="r_commit", connector_id=inst.id, source_account_id=acc.id,
        external_type="commit", external_id="abc123",
        content="wip queue wiring",
        occurred_at="2026-07-03T11:00:00Z",
        ownership={"vault_id": acc.vault_id},
        source_metadata={"lineage_root": lineage, "repo": "acme/atlas"},
    )
    merge = _rec(
        id="r_merge", connector_id=inst.id, source_account_id=acc.id,
        external_type="commit", external_id="def456",
        content="Merged: ship the queue",
        occurred_at="2026-07-04T12:00:00Z",
        ownership={"vault_id": acc.vault_id},
        source_metadata={"lineage_root": lineage, "repo": "acme/atlas"},
    )
    for r in (issue, pr, commit, merge):
        store.insert_connector_record(r)
    return [issue, pr, commit, merge]


def test_arc_yields_ordered_phases_single_episode(store, cfg, embedder):
    acc, inst = _acct(store)
    _arc(store, acc, inst)
    report = _cortex(store, cfg, embedder)
    assert len(report.episode_ids) == 1
    ep_id = report.episode_ids[0]
    phases = store.list_episode_phases(ep_id)
    kinds = [p.kind for p in phases]
    # goal (issue) → decision (PR) → … → outcome (merged)
    assert kinds[0] == EpisodePhaseKind.goal
    assert EpisodePhaseKind.decision in kinds
    assert kinds[-1] == EpisodePhaseKind.outcome
    # phases are strictly time-ordered
    starts = [p.started_at for p in phases if p.started_at]
    assert starts == sorted(starts)
    # provenance records the brain stage (no lexical method)
    assert phases[0].provenance.get("method") == "llm"
    assert phases[0].provenance.get("brain_stage") == "amygdala"


def _pivot_records(store, acc, inst):
    lineage = "github:acme/atlas#7"
    issue = _rec(
        id="p_issue", connector_id=inst.id, source_account_id=acc.id,
        external_type="issue", external_id="acme/atlas#7",
        content="Choose a queue",
        occurred_at="2026-07-01T09:00:00Z",
        ownership={"vault_id": acc.vault_id},
        source_metadata={"lineage_root": lineage, "repo": "acme/atlas"},
    )
    d1 = _rec(
        id="p_d1", connector_id=inst.id, source_account_id=acc.id,
        external_type="pull_request", external_id="acme/atlas!1",
        content="Decided we will use Kafka for the queue",
        occurred_at="2026-07-02T09:00:00Z",
        ownership={"vault_id": acc.vault_id},
        source_metadata={"lineage_root": lineage, "repo": "acme/atlas"},
    )
    d2 = _rec(
        id="p_d2", connector_id=inst.id, source_account_id=acc.id,
        external_type="pull_request", external_id="acme/atlas!2",
        content="Reverting Kafka; switch to SQS instead",
        occurred_at="2026-07-03T09:00:00Z",
        ownership={"vault_id": acc.vault_id},
        source_metadata={"lineage_root": lineage, "repo": "acme/atlas"},
    )
    for r in (issue, d1, d2):
        store.insert_connector_record(r)
    return [issue, d1, d2]


def test_decision_pivot_splits_and_supersedes(store, cfg, embedder):
    acc, inst = _acct(store, account_id="acct_pivot")
    _pivot_records(store, acc, inst)
    report = _cortex(store, cfg, embedder)
    ep_id = report.episode_ids[0]
    phases = store.list_episode_phases(ep_id)
    decisions = [p for p in phases if p.kind == EpisodePhaseKind.decision]
    # the two decisions stay separate phases (decision is non-mergeable)
    assert len(decisions) == 2
    edges = store.list_episode_edges(ep_id)
    rels = {e.relation for e in edges}
    assert EpisodeEdgeRelation.superseded in rels
    assert all(e.provenance.get("brain_stage") == "cortex" for e in edges)


def test_edge_confirm_reject_survives_rebuild(store, cfg, embedder):
    acc, inst = _acct(store, account_id="acct_edge")
    _arc(store, acc, inst)
    report = _cortex(store, cfg, embedder)
    ep_id = report.episode_ids[0]
    edges = store.list_episode_edges(ep_id)
    assert edges
    target = edges[0]
    confirm_edge(store, target.id)
    # re-run cortex — the human decision must persist across rebuild
    _cortex(store, cfg, embedder)
    again = store.get_episode_edge(target.id)
    assert again is not None
    assert again.status == EpisodeEdgeStatus.confirmed


def test_explain_episode_includes_phases_and_edges(store, cfg, embedder):
    acc, inst = _acct(store, account_id="acct_expl")
    _arc(store, acc, inst)
    report = _cortex(store, cfg, embedder)
    out = explain_episode(store, report.episode_ids[0])
    assert out["phases"]
    assert "edges" in out
    assert out["phases"][0]["kind"] == "goal"


def test_deferred_without_model_builds_no_arc(store, cfg, embedder):
    # No stage overrides + echo (no model) → cortex defers, no phases invented.
    set_stage_override(BrainStage.amygdala, None)
    set_stage_override(BrainStage.cortex, None)
    acc, inst = _acct(store, account_id="acct_defer")
    _arc(store, acc, inst)
    report = run_episode_cognition(
        store, cfg, embedder, mode="full", until=BrainStage.cortex,
    )
    assert report.stages["amygdala"].status.value == "deferred"
    for eid in report.episode_ids:
        assert store.list_episode_phases(eid) == []


def test_incremental_matches_full_membership(store, cfg, embedder):
    acc, inst = _acct(store, account_id="acct_inc")
    recs = _arc(store, acc, inst)
    for r in recs:
        store.mark_correlation_dirty(r.id, vault_id=acc.vault_id, reason="commit")

    inc = run_correlation_pass(store, mode="incremental")
    assert inc.episodes >= 1
    inc_ep = store.list_work_episodes(vault_id=acc.vault_id)[0]
    inc_members = {
        (r["external_type"], r["external_id"]) for r in inc_ep.source_refs
    }
    assert store.list_correlation_dirty() == []

    run_correlation_pass(store, mode="full")
    full_ep = store.get_work_episode(inc_ep.id)
    full_members = {
        (r["external_type"], r["external_id"]) for r in full_ep.source_refs
    }
    assert inc_members == full_members


def test_incremental_noop_when_clean(store, cfg, embedder):
    acc, inst = _acct(store, account_id="acct_clean")
    _arc(store, acc, inst)
    report = run_correlation_pass(store, mode="incremental")
    assert report.episodes == 0
    assert report.records_scanned == 0
