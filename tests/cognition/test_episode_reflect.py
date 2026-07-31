"""hippocampus_consolidate — trajectory MemoryCandidates from an episode arc.

Phases/edges are built by the cortex stage (deterministic overrides here) and
the reflect stage is a chat model — simulated by ``set_reflect_override``. No
lexical fallback: without a reflector the stage defers.
"""

from __future__ import annotations

import pytest

from twin.cognition import (
    BrainStage,
    run_episode_cognition,
    set_reflect_override,
    set_stage_override,
)
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

_OUTCOME_WORDS = ("merged", "shipped", "released", "closed", "resolved")
_PIVOT_WORDS = ("revert", "instead", "switch to", "supersed", "pivot")


def _classify(members, cfg):
    roles = {}
    for m in members:
        t = (m.get("external_type") or "").lower()
        ex = (m.get("excerpt") or "").lower()
        if any(w in ex for w in _OUTCOME_WORDS):
            kind = "outcome"
        elif t in ("issue", "discussion"):
            kind = "goal"
        elif t in ("pull_request", "review"):
            kind = "decision"
        elif t in ("commit", "push"):
            kind = "execution"
        else:
            kind = "other"
        roles[m["ref"]] = {"kind": kind, "salience": 0.6}
    return roles


def _understand(phases, quotes, cfg):
    ordered = sorted(phases, key=lambda p: p.get("order", 0))
    edges = []
    for a, b in zip(ordered, ordered[1:]):
        rel = "motivated" if a["kind"] in ("goal", "decision") else "continues"
        edges.append({
            "from_key": a["phase_key"], "to_key": b["phase_key"],
            "relation": rel, "confidence": 0.6, "evidence_quote": "",
        })
    decisions = [p for p in ordered if p["kind"] == "decision"]
    for earlier, later in zip(decisions, decisions[1:]):
        text = (later.get("summary") or "") + " " + " ".join(
            quotes.get(r, "") for r in later.get("members", [])
        )
        if any(w in text.lower() for w in _PIVOT_WORDS):
            edges.append({
                "from_key": earlier["phase_key"], "to_key": later["phase_key"],
                "relation": "superseded", "confidence": 0.7, "evidence_quote": "",
            })
    return edges


def _sqs_reflector(brief, cfg):
    for e in brief.edges:
        if e["relation"] != "superseded":
            continue
        to_phase = next(
            (p for p in brief.phases if p["phase_key"] == e["to_key"]), None
        )
        vf = (to_phase or {}).get("started_at") or brief.valid_from
        return [TrajectoryClaim(
            type="decision",
            title="Changed course: Kafka → SQS",
            summary="Intended Kafka, later chose SQS for the queue.",
            valid_from=vf,
            confidence=0.6,
            phase_keys=[e["from_key"], e["to_key"]],
            edge_ids=[e["id"]],
            twin_influenced=True,
        )]
    return []


@pytest.fixture(autouse=True)
def _cognition(_reset_interpreter_override):
    set_stage_override(BrainStage.amygdala, _classify)
    set_stage_override(BrainStage.cortex, _understand)
    set_reflect_override(_sqs_reflector)
    yield
    set_stage_override(BrainStage.amygdala, None)
    set_stage_override(BrainStage.cortex, None)
    set_reflect_override(None)


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


def _pivot_episode(store, cfg, embedder, acc, inst):
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
    report = run_episode_cognition(
        store, cfg, embedder, mode="full", until=BrainStage.cortex,
    )
    return store.get_work_episode(report.episode_ids[0])


def test_reflect_pivot_yields_trajectory_candidate(store, cfg, embedder):
    acc, inst = _acct(store)
    ep = _pivot_episode(store, cfg, embedder, acc, inst)

    result = reflect_episode(store, cfg, embedder, ep.id)
    assert result.claims, result.skipped_reason
    mem_id = result.claims[0]["memory_id"]
    mem = store.get_memory(mem_id)
    assert mem is not None
    assert mem.status == MemoryStatus.candidate
    assert mem.needs_review is True
    assert mem.review_reason == "episode_reflect"
    assert mem.type == MemoryType.decision
    assert "SQS" in mem.summary or "SQS" in mem.title
    assert mem.valid_from == "2026-07-03T09:00:00Z"
    assert mem.payload.get("episode_id") == ep.id
    assert mem.payload.get("source") == "episode_reflect"
    assert mem.payload.get("brain_stage") == "hippocampus_consolidate"


def test_reflect_is_idempotent(store, cfg, embedder):
    acc, inst = _acct(store, account_id="acct_idem")
    ep = _pivot_episode(store, cfg, embedder, acc, inst)
    first = reflect_episode(store, cfg, embedder, ep.id)
    ids_first = {c["memory_id"] for c in first.claims}
    second = reflect_episode(store, cfg, embedder, ep.id)
    for c in second.claims:
        assert c["memory_id"] in ids_first
        assert c["created"] is False


def test_reflect_skips_episode_without_arc(store, cfg, embedder):
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
    report = run_episode_cognition(
        store, cfg, embedder, mode="full", until=BrainStage.cortex,
    )
    ep_id = report.episode_ids[0]
    # two commits collapse into one execution phase → no arc
    result = reflect_episode(store, cfg, embedder, ep_id)
    assert result.claims == []
    assert result.skipped_reason


def test_reflect_skips_structural_pr_commit_pair(store, cfg, embedder):
    """PR → commit with only a motivated edge is membership noise, not trajectory."""
    acc, inst = _acct(store, account_id="acct_prpair")
    lineage = "github:acme/atlas#99"
    pr = _rec(
        id="pr99", connector_id=inst.id, source_account_id=acc.id,
        external_type="pull_request", external_id="acme/atlas!99",
        content="Implement the queue",
        occurred_at="2026-07-01T09:00:00Z",
        ownership={"vault_id": acc.vault_id},
        source_metadata={"lineage_root": lineage, "repo": "acme/atlas"},
    )
    commit = _rec(
        id="c99", connector_id=inst.id, source_account_id=acc.id,
        external_type="commit", external_id="abc999",
        content="Implement the queue",
        occurred_at="2026-07-02T09:00:00Z",
        ownership={"vault_id": acc.vault_id},
        source_metadata={"lineage_root": lineage, "repo": "acme/atlas"},
    )
    for r in (pr, commit):
        store.insert_connector_record(r)
    report = run_episode_cognition(
        store, cfg, embedder, mode="full", until=BrainStage.cortex,
    )
    result = reflect_episode(store, cfg, embedder, report.episode_ids[0])
    assert result.claims == []
    assert "structural only" in result.skipped_reason


def test_reflect_dry_run_persists_nothing(store, cfg, embedder):
    acc, inst = _acct(store, account_id="acct_dry")
    ep = _pivot_episode(store, cfg, embedder, acc, inst)
    result = reflect_episode(store, cfg, embedder, ep.id, dry_run=True)
    assert result.claims
    assert all(c["memory_id"] is None for c in result.claims)
    assert store.list_memories(status="candidate", limit=50) == []


def test_reflect_deferred_without_reflector(store, cfg, embedder):
    acc, inst = _acct(store, account_id="acct_nomodel")
    ep = _pivot_episode(store, cfg, embedder, acc, inst)
    set_reflect_override(None)  # echo has no model → defer, never fabricate
    result = reflect_episode(store, cfg, embedder, ep.id)
    assert result.claims == []
    assert "deferred" in result.skipped_reason.lower()


def test_reflect_override(store, cfg, embedder):
    acc, inst = _acct(store, account_id="acct_over")
    ep = _pivot_episode(store, cfg, embedder, acc, inst)

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
    ep = _pivot_episode(store, cfg, embedder, acc, inst)
    brief = build_episode_brief(store, ep.id)
    assert brief is not None
    assert len(brief.phases) >= 2
    assert any(e["relation"] == "superseded" for e in brief.edges)
