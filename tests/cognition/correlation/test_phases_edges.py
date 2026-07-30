"""Episode phases, narrative edges, and incremental correlation parity."""

from __future__ import annotations

from twin.cognition.correlation.edges import confirm_edge, reject_edge
from twin.cognition.correlation.episodes import correlate_records
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


def test_arc_yields_ordered_phases_single_episode(store):
    acc, inst = _acct(store)
    recs = _arc(store, acc, inst)
    eps = correlate_records(store, recs, vault_id=acc.vault_id)
    assert len(eps) == 1
    ep = eps[0]
    phases = store.list_episode_phases(ep.id)
    kinds = [p.kind for p in phases]
    # goal (issue) → decision (PR) → … → outcome (merged)
    assert kinds[0] == EpisodePhaseKind.goal
    assert EpisodePhaseKind.decision in kinds
    assert kinds[-1] == EpisodePhaseKind.outcome
    # phases are strictly time-ordered
    starts = [p.started_at for p in phases if p.started_at]
    assert starts == sorted(starts)


def test_decision_pivot_splits_and_supersedes(store):
    acc, inst = _acct(store, account_id="acct_pivot")
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
    eps = correlate_records(store, [issue, d1, d2], vault_id=acc.vault_id)
    ep = eps[0]
    phases = store.list_episode_phases(ep.id)
    decisions = [p for p in phases if p.kind == EpisodePhaseKind.decision]
    # the reversal keeps the two decisions as separate phases
    assert len(decisions) == 2
    edges = store.list_episode_edges(ep.id)
    rels = {e.relation for e in edges}
    assert EpisodeEdgeRelation.superseded in rels


def test_edge_confirm_reject_survives_rebuild(store):
    acc, inst = _acct(store, account_id="acct_edge")
    recs = _arc(store, acc, inst)
    ep = correlate_records(store, recs, vault_id=acc.vault_id)[0]
    edges = store.list_episode_edges(ep.id)
    assert edges
    target = edges[0]
    confirm_edge(store, target.id)
    # re-correlate (rebuild) — human decision must persist
    correlate_records(store, recs, vault_id=acc.vault_id)
    again = store.get_episode_edge(target.id)
    assert again is not None
    assert again.status == EpisodeEdgeStatus.confirmed


def test_explain_episode_includes_phases_and_edges(store):
    acc, inst = _acct(store, account_id="acct_expl")
    recs = _arc(store, acc, inst)
    ep = correlate_records(store, recs, vault_id=acc.vault_id)[0]
    out = explain_episode(store, ep.id)
    assert out["phases"]
    assert "edges" in out
    assert out["phases"][0]["kind"] == "goal"


def test_incremental_matches_full_membership_and_phases(store):
    acc, inst = _acct(store, account_id="acct_inc")
    recs = _arc(store, acc, inst)
    # dirty index is populated by the commit path; simulate it here
    for r in recs:
        store.mark_correlation_dirty(r.id, vault_id=acc.vault_id, reason="commit")

    inc = run_correlation_pass(store, mode="incremental")
    assert inc.episodes >= 1
    inc_ep = store.list_work_episodes(vault_id=acc.vault_id)[0]
    inc_members = {
        (r["external_type"], r["external_id"]) for r in inc_ep.source_refs
    }
    inc_phases = [(p.kind.value, p.phase_key) for p in
                  store.list_episode_phases(inc_ep.id)]
    # dirty cleared after a successful pass
    assert store.list_correlation_dirty() == []

    # a full pass must agree on membership + phase structure (stable ids)
    run_correlation_pass(store, mode="full")
    full_ep = store.get_work_episode(inc_ep.id)
    full_members = {
        (r["external_type"], r["external_id"]) for r in full_ep.source_refs
    }
    full_phases = [(p.kind.value, p.phase_key) for p in
                   store.list_episode_phases(full_ep.id)]
    assert inc_members == full_members
    assert inc_phases == full_phases


def test_incremental_noop_when_clean(store):
    acc, inst = _acct(store, account_id="acct_clean")
    _arc(store, acc, inst)
    # nothing marked dirty → incremental is a cheap no-op
    report = run_correlation_pass(store, mode="incremental")
    assert report.episodes == 0
    assert report.records_scanned == 0
