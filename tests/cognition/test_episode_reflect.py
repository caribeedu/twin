"""episode_reflect — trajectory MemoryCandidates from an episode arc."""

from __future__ import annotations

from twin.cognition.correlation.episodes import correlate_records
from twin.cognition.episode_reflect import (
    TrajectoryClaim,
    build_episode_brief,
    reflect_episode,
)
from twin.connectors.models import (
    ConnectorInstance,
    ConnectorRecord,
    ConnectorStatus,
    OwnershipClass,
    SourceAccount,
    idempotency_key,
)
from twin.memory.models import MemoryStatus, MemoryType


def _acct(store, *, vault_id="vault_work_acme", account_id="acct_rf"):
    acc = SourceAccount(
        id=account_id, connector_type="github",
        external_account_id=account_id, owner_principal_id="p1",
        source_owner=OwnershipClass.employer, vault_id=vault_id, org_key="acme",
    )
    store.insert_source_account(acc)
    inst = ConnectorInstance(
        id=f"conn_{account_id}", connector_type="github",
        account_id=acc.id, status=ConnectorStatus.active,
    )
    store.insert_connector_instance(inst)
    return acc, inst


def _rec(**kwargs) -> ConnectorRecord:
    defaults = dict(
        connector_id="conn_1", source_account_id="acct_1",
        external_type="pull_request", external_id="pr-1", external_revision="1",
        content="hello", actor_ids=[], participant_ids=[],
        source_metadata={}, ownership={},
    )
    defaults.update(kwargs)
    rec = ConnectorRecord(**defaults)
    if not rec.idempotency_key:
        rec.idempotency_key = idempotency_key(
            "test", rec.source_account_id, rec.external_type,
            rec.external_id, rec.external_revision,
        )
    return rec


def _pivot_episode(store, acc, inst):
    lineage = "github:acme/atlas#7"
    issue = _rec(
        id="rf_issue", connector_id=inst.id, source_account_id=acc.id,
        external_type="issue", external_id="acme/atlas#7",
        content="Choose a queue technology",
        occurred_at="2026-07-01T09:00:00Z",
        ownership={"vault_id": acc.vault_id},
        source_metadata={"lineage_root": lineage, "repo": "acme/atlas"},
    )
    d1 = _rec(
        id="rf_d1", connector_id=inst.id, source_account_id=acc.id,
        external_type="pull_request", external_id="acme/atlas!1",
        content="Decided we will use Kafka for the queue",
        occurred_at="2026-07-02T09:00:00Z",
        ownership={"vault_id": acc.vault_id},
        source_metadata={"lineage_root": lineage, "repo": "acme/atlas"},
    )
    d2 = _rec(
        id="rf_d2", connector_id=inst.id, source_account_id=acc.id,
        external_type="pull_request", external_id="acme/atlas!2",
        content="Reverting Kafka; switch to SQS instead",
        occurred_at="2026-07-03T09:00:00Z",
        ownership={"vault_id": acc.vault_id},
        source_metadata={"lineage_root": lineage, "repo": "acme/atlas"},
    )
    for r in (issue, d1, d2):
        store.insert_connector_record(r)
    return correlate_records(store, [issue, d1, d2], vault_id=acc.vault_id)[0]


def test_reflect_pivot_yields_trajectory_candidate(store, cfg, embedder):
    acc, inst = _acct(store)
    ep = _pivot_episode(store, acc, inst)

    result = reflect_episode(store, cfg, embedder, ep.id)
    assert result.claims, result.skipped_reason
    mem_id = result.claims[0]["memory_id"]
    mem = store.get_memory(mem_id)
    assert mem is not None
    # candidate only — reflection never confirms
    assert mem.status == MemoryStatus.candidate
    assert mem.needs_review is True
    assert mem.review_reason == "episode_reflect"
    assert mem.type == MemoryType.decision
    # the trajectory (X→Y), not a single commit fact
    assert "SQS" in mem.summary or "SQS" in mem.title
    # valid_from tracks the decision phase, not the reflect clock
    assert mem.valid_from == "2026-07-03T09:00:00Z"
    assert mem.payload.get("episode_id") == ep.id
    assert mem.payload.get("source") == "episode_reflect"


def test_reflect_is_idempotent(store, cfg, embedder):
    acc, inst = _acct(store, account_id="acct_idem")
    ep = _pivot_episode(store, acc, inst)
    first = reflect_episode(store, cfg, embedder, ep.id)
    ids_first = {c["memory_id"] for c in first.claims}
    second = reflect_episode(store, cfg, embedder, ep.id)
    # re-reflecting corroborates rather than duplicating (same formation id)
    for c in second.claims:
        assert c["memory_id"] in ids_first
        assert c["created"] is False


def test_reflect_skips_episode_without_narrative(store, cfg, embedder):
    acc, inst = _acct(store, account_id="acct_flat")
    lineage = "github:acme/atlas#20"
    a = _rec(
        id="flat1", connector_id=inst.id, source_account_id=acc.id,
        external_type="commit", external_id="c1", content="wip",
        occurred_at="2026-07-01T09:00:00Z",
        ownership={"vault_id": acc.vault_id},
        source_metadata={"lineage_root": lineage, "repo": "acme/atlas"},
    )
    b = _rec(
        id="flat2", connector_id=inst.id, source_account_id=acc.id,
        external_type="commit", external_id="c2", content="more wip",
        occurred_at="2026-07-02T09:00:00Z",
        ownership={"vault_id": acc.vault_id},
        source_metadata={"lineage_root": lineage, "repo": "acme/atlas"},
    )
    for r in (a, b):
        store.insert_connector_record(r)
    ep = correlate_records(store, [a, b], vault_id=acc.vault_id)[0]
    result = reflect_episode(store, cfg, embedder, ep.id)
    assert result.claims == []
    assert result.skipped_reason


def test_reflect_dry_run_persists_nothing(store, cfg, embedder):
    acc, inst = _acct(store, account_id="acct_dry")
    ep = _pivot_episode(store, acc, inst)
    result = reflect_episode(store, cfg, embedder, ep.id, dry_run=True)
    assert result.claims
    assert all(c["memory_id"] is None for c in result.claims)
    assert store.list_memories(status="candidate", limit=50) == []


def test_reflect_override(store, cfg, embedder):
    acc, inst = _acct(store, account_id="acct_over")
    ep = _pivot_episode(store, acc, inst)

    def _fake(brief, _cfg):
        return [TrajectoryClaim(
            type="belief",
            title="Prefers managed queues over self-hosted",
            summary="Across the episode Edu leaned to managed services.",
            valid_from="2026-07-03T09:00:00Z",
            confidence=0.7,
            twin_influenced=True,
        )]

    result = reflect_episode(store, cfg, embedder, ep.id, reflector=_fake)
    assert len(result.claims) == 1
    mem = store.get_memory(result.claims[0]["memory_id"])
    assert mem.type == MemoryType.belief
    assert mem.payload.get("twin_influenced") is True


def test_build_brief_has_phase_and_edges(store, cfg, embedder):
    acc, inst = _acct(store, account_id="acct_brief")
    ep = _pivot_episode(store, acc, inst)
    brief = build_episode_brief(store, ep.id)
    assert brief is not None
    assert len(brief.phases) >= 2
    assert any(e["relation"] == "superseded" for e in brief.edges)
