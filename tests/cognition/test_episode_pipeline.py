"""episode_pipeline — brain-staged cognition orchestrator + deferral."""

from __future__ import annotations

import pytest

from twin.cognize.services import (
    BrainStage,
    run_episode_cognition,
    set_reflect_override,
    set_stage_override,
)
from twin.cognize.services.episode_pipeline import STAGE_ORDER
from twin.sense.connectors.models import (
    ConnectorInstance,
    ConnectorRecord,
    ConnectorStatus,
    OwnershipClass,
    SourceAccount,
    idempotency_key,
)


def _classify(members, cfg):
    roles = {}
    for m in members:
        t = (m.get("external_type") or "").lower()
        ex = (m.get("excerpt") or "").lower()
        if "revert" in ex or "switch to" in ex:
            kind = "decision"
        elif t == "issue":
            kind = "goal"
        elif t == "pull_request":
            kind = "decision"
        else:
            kind = "execution"
        roles[m["ref"]] = {"kind": kind, "salience": 0.7}
    return roles


def _understand(phases, quotes, cfg):
    ordered = sorted(phases, key=lambda p: p.get("order", 0))
    edges = []
    for a, b in zip(ordered, ordered[1:]):
        edges.append({
            "from_key": a["phase_key"], "to_key": b["phase_key"],
            "relation": "motivated", "confidence": 0.6, "evidence_quote": "",
        })
    decisions = [p for p in ordered if p["kind"] == "decision"]
    for earlier, later in zip(decisions, decisions[1:]):
        edges.append({
            "from_key": earlier["phase_key"], "to_key": later["phase_key"],
            "relation": "superseded", "confidence": 0.7, "evidence_quote": "",
        })
    return edges


def _sqs_reflector(brief, cfg):
    from twin.cognize.services.episode_reflect import TrajectoryClaim

    if len(brief.phases) < 2:
        return []
    return [TrajectoryClaim(
        type="decision",
        title="Changed course: Kafka → SQS",
        summary="Intended Kafka, later chose SQS.",
        valid_from=brief.valid_from,
        confidence=0.6,
        twin_influenced=True,
    )]


def _acct(store, account_id="acct_pl"):
    acc = SourceAccount(
        id=account_id, connector_type="github",
        external_account_id=account_id, owner_principal_id="p1",
        source_owner=OwnershipClass.employer,
        vault_id="vault_work_acme", org_key="acme",
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


def _seed_pivot(store, acc, inst):
    lineage = "github:acme/atlas#9"
    recs = [
        _rec(id="pl_issue", connector_id=inst.id, source_account_id=acc.id,
             external_type="issue", external_id="acme/atlas#9",
             content="Choose a queue", occurred_at="2026-07-01T09:00:00Z",
             ownership={"vault_id": acc.vault_id},
             source_metadata={"lineage_root": lineage, "repo": "acme/atlas"}),
        _rec(id="pl_d1", connector_id=inst.id, source_account_id=acc.id,
             external_type="pull_request", external_id="acme/atlas!1",
             content="Use Kafka", occurred_at="2026-07-02T09:00:00Z",
             ownership={"vault_id": acc.vault_id},
             source_metadata={"lineage_root": lineage, "repo": "acme/atlas"}),
        _rec(id="pl_d2", connector_id=inst.id, source_account_id=acc.id,
             external_type="pull_request", external_id="acme/atlas!2",
             content="Reverting Kafka; switch to SQS", occurred_at="2026-07-03T09:00:00Z",
             ownership={"vault_id": acc.vault_id},
             source_metadata={"lineage_root": lineage, "repo": "acme/atlas"}),
    ]
    for r in recs:
        store.insert_connector_record(r)


def test_pipeline_builds_arc_up_to_cortex(store, cfg, embedder):
    set_stage_override(BrainStage.amygdala, _classify)
    set_stage_override(BrainStage.cortex, _understand)
    acc, inst = _acct(store)
    _seed_pivot(store, acc, inst)

    report = run_episode_cognition(
        store, cfg, embedder, mode="full", until=BrainStage.cortex,
    )
    assert report.stages["sensory"].status.value == "ok"
    assert report.stages["amygdala"].status.value == "ok"
    assert report.stages["cortex"].status.value == "ok"
    assert report.stages["cortex"].counts.get("phases", 0) >= 2
    assert report.stages["cortex"].counts.get("edges", 0) >= 1
    # basal + bind ran structurally
    assert report.stages["basal"].status.value == "ok"
    assert report.stages["hippocampus_bind"].status.value == "ok"
    # consolidate / prefrontal did not run (stopped at cortex)
    assert "hippocampus_consolidate" not in report.stages


def test_pipeline_consolidate_creates_candidates(store, cfg, embedder):
    set_stage_override(BrainStage.amygdala, _classify)
    set_stage_override(BrainStage.cortex, _understand)
    set_reflect_override(_sqs_reflector)
    acc, inst = _acct(store, account_id="acct_con")
    _seed_pivot(store, acc, inst)

    report = run_episode_cognition(
        store, cfg, embedder, mode="full",
        until=BrainStage.hippocampus_consolidate,
    )
    assert report.stages["hippocampus_consolidate"].status.value == "ok"
    assert report.candidate_ids
    mem = store.get_claim(report.candidate_ids[0])
    assert mem is not None
    assert mem.status.value == "candidate"


def test_pipeline_defers_without_model(store, cfg, embedder):
    # echo cfg, no overrides → semantic stages defer, nothing invented.
    acc, inst = _acct(store, account_id="acct_def")
    _seed_pivot(store, acc, inst)
    report = run_episode_cognition(
        store, cfg, embedder, mode="full", until=BrainStage.cortex,
    )
    assert report.stages["amygdala"].status.value == "deferred"
    for eid in report.episode_ids:
        assert store.list_episode_phases(eid) == []


def test_pipeline_blocked_in_heuristic_mode(store, cfg, embedder):
    cfg.extractor = "heuristic"
    acc, inst = _acct(store, account_id="acct_heur")
    _seed_pivot(store, acc, inst)
    report = run_episode_cognition(
        store, cfg, embedder, mode="full", until=BrainStage.cortex,
    )
    amy = report.stages["amygdala"]
    assert amy.status.value == "blocked"
    assert "interpreting" in amy.detail


def test_until_sensory_skips_semantic_stages(store, cfg, embedder):
    set_stage_override(BrainStage.amygdala, _classify)
    acc, inst = _acct(store, account_id="acct_sens")
    _seed_pivot(store, acc, inst)
    report = run_episode_cognition(
        store, cfg, embedder, mode="full", until=BrainStage.sensory,
    )
    assert report.stages["sensory"].status.value == "ok"
    assert "amygdala" not in report.stages


def test_stage_order_is_canonical():
    assert [s.value for s in STAGE_ORDER] == [
        "sensory", "amygdala", "basal", "hippocampus_bind",
        "cortex", "hippocampus_consolidate", "prefrontal",
    ]
