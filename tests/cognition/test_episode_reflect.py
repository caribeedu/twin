"""hippocampus_consolidate — trajectory MemoryCandidates from an episode arc.

Phases/edges are built by the cortex stage (deterministic overrides here) and
the reflect stage is a chat model — simulated by ``set_reflect_override``. No
lexical fallback: without a reflector the stage defers.
"""

from __future__ import annotations

import pytest

from twin.cognize.services import (
    BrainStage,
    run_episode_cognition,
    set_reflect_override,
    set_stage_override,
)
from twin.cognize.services.episode_reflect import (
    TrajectoryClaim,
    build_episode_brief,
    reflect_episode,
)
from twin.sense.connectors.models import (
    ConnectorInstance,
    ConnectorRecord,
    ConnectorStatus,
    OwnershipClass,
    SourceAccount,
    idempotency_key,
)
from twin.store.models import MemoryStatus, MemoryType

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


def test_reflect_near_duplicate_arc_still_asks_model(store, cfg, embedder):
    """≥2 phases always reach the reflector — the model may return no claims."""
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
    seen = {"called": False}

    def _empty(brief_in, _cfg):
        seen["called"] = True
        assert len(brief_in.phases) >= 2
        return []

    result = reflect_episode(
        store, cfg, embedder, report.episode_ids[0], reflector=_empty,
    )
    assert seen["called"] is True
    assert result.claims == []
    assert "no claims" in result.skipped_reason


def test_reflect_surfaces_model_failure_reason(store, cfg, embedder):
    """A raising reflector (bad model id, transport, overflow) must not vanish:
    the cause is surfaced in ``skipped_reason`` and never crashes the caller."""
    acc, inst = _acct(store, account_id="acct_fail")
    lineage = "github:acme/atlas#7"
    pr = _rec(
        id="prf", connector_id=inst.id, source_account_id=acc.id,
        external_type="pull_request", external_id="acme/atlas!7",
        content="GitHub pull request acme/atlas!7: harden retry path.",
        source_metadata={"repo": "acme/atlas", "lineage_root": lineage},
    )
    commit = _rec(
        id="cmf", connector_id=inst.id, source_account_id=acc.id,
        external_type="commit", external_id="deadbeef7",
        content="Merge pull request #7 from acme/retry\n\nharden retry path",
        source_metadata={"repo": "acme/atlas"},
    )
    for r in (pr, commit):
        store.insert_connector_record(r)
    report = run_episode_cognition(
        store, cfg, embedder, mode="full", until=BrainStage.cortex,
    )

    def _boom(_brief, _cfg):
        raise RuntimeError("anthropic HTTP 404: model: claude-opus-4-8 not found")

    result = reflect_episode(
        store, cfg, embedder, report.episode_ids[0], reflector=_boom,
    )
    assert result.claims == []
    assert "reflect model failed" in result.skipped_reason
    assert "claude-opus-4-8" in result.skipped_reason


def test_reflect_allows_divergent_pr_commit_pair(store, cfg, embedder):
    """PR framing A + commit landing on B can yield a durable stance."""
    acc, inst = _acct(store, account_id="acct_diverge")
    lineage = "github:acme/atlas#42"
    pr = _rec(
        id="prd", connector_id=inst.id, source_account_id=acc.id,
        external_type="pull_request", external_id="acme/atlas!42",
        content=(
            "GitHub pull request acme/atlas!42: Implement parallel memory spine.\n"
            "state: MERGED\n"
            "Add workspace ticks and daily consolidation without confirming Memory."
        ),
        occurred_at="2026-07-01T09:00:00Z",
        ownership={"vault_id": acc.vault_id},
        source_metadata={"lineage_root": lineage, "repo": "acme/atlas"},
    )
    commit = _rec(
        id="cd", connector_id=inst.id, source_account_id=acc.id,
        external_type="commit", external_id="def999",
        content=(
            "Commit def999 in acme/atlas by Edu:\n"
            "Address PR blockers: retrieval score and operational idempotency.\n"
            "Tighten tests and persist consolidation window runs."
        ),
        occurred_at="2026-07-02T09:00:00Z",
        ownership={"vault_id": acc.vault_id},
        source_metadata={"lineage_root": lineage, "repo": "acme/atlas"},
    )
    for r in (pr, commit):
        store.insert_connector_record(r)
    report = run_episode_cognition(
        store, cfg, embedder, mode="full", until=BrainStage.cortex,
    )
    ep_id = report.episode_ids[0]
    brief = build_episode_brief(store, ep_id)
    assert brief is not None
    assert any("idempotency" in q for q in brief.quotes_by_ref.values())
    assert any("workspace ticks" in q for q in brief.quotes_by_ref.values())

    def _fake(brief_in, _cfg):
        assert brief_in.related_memories is not None
        return [TrajectoryClaim(
            type="constraint",
            domain="technical",
            title="Merge gates before spine expansion",
            summary=(
                "Edu requires retrieval-score accuracy and operational "
                "idempotency before expanding the parallel memory spine."
            ),
            valid_from="2026-07-02T09:00:00Z",
            twin_influenced=True,
        )]

    result = reflect_episode(store, cfg, embedder, ep_id, reflector=_fake)
    assert result.claims, result.skipped_reason
    mem = store.get_memory(result.claims[0]["memory_id"])
    assert mem is not None
    assert mem.type == MemoryType.constraint
    assert "idempotency" in mem.summary


def test_reflect_gathers_related_including_rejected(store, cfg, embedder):
    """Consolidate retrieves confirmed/candidate/rejected neighbors."""
    from twin import ids
    from twin.cognize.services.episode_reflect import gather_related_memories
    from twin.store.models import MemoryItem

    acc, inst = _acct(store, account_id="acct_rel")
    ep = _pivot_episode(store, cfg, embedder, acc, inst)

    confirmed = MemoryItem(
        id=ids.memory_id(), type="preference",
        title="Prefers managed queues",
        summary="Edu prefers SQS over self-hosted Kafka for ops cost.",
        domain="technical", confidence=0.9, status="confirmed",
    )
    rejected = MemoryItem(
        id=ids.memory_id(), type="decision",
        title="Keep Kafka forever",
        summary="Rejected: keep self-hosted Kafka as the queue.",
        domain="technical", confidence=0.5, status="rejected",
    )
    for mem in (confirmed, rejected):
        store.insert_memory(mem)
        store.store_embedding(
            mem.id, "memory", embedder.name,
            embedder.embed(f"{mem.title}\n{mem.summary}"),
        )

    brief = build_episode_brief(store, ep.id)
    assert brief is not None
    related = gather_related_memories(store, embedder, brief, limit=10)
    ids_hit = {r["id"] for r in related}
    assert confirmed.id in ids_hit
    assert rejected.id in ids_hit
    statuses = {r["id"]: r["status"] for r in related}
    assert statuses[rejected.id] == "rejected"

    seen: dict = {}

    def _fake(brief_in, _cfg):
        seen["related"] = list(brief_in.related_memories)
        return [TrajectoryClaim(
            type="preference",
            domain="technical",
            title="Managed queues over self-hosted",
            summary="Chose SQS; rejected keeping Kafka forever.",
            related_memory_ids=[rejected.id],
            twin_influenced=True,
        )]

    result = reflect_episode(store, cfg, embedder, ep.id, reflector=_fake)
    assert result.claims, result.skipped_reason
    assert any(r["id"] == rejected.id for r in seen["related"])
    mem = store.get_memory(result.claims[0]["memory_id"])
    assert mem.payload.get("related_memory_ids") == [rejected.id]


def test_reflect_gathers_open_session_artifacts(store, cfg, embedder):
    """Open-session observe notes surface before vault neighbors."""
    from twin.cognize.services.episode_reflect import gather_related_memories
    from twin.cognize.services.sessions import observe_session, start_session

    acc, inst = _acct(store, account_id="acct_sesart")
    ep = _pivot_episode(store, cfg, embedder, acc, inst)
    started = start_session(
        store, cfg, embedder,
        query="Kafka vs SQS queue choice",
        domain="technical",
        task_profile="architecture",
    )
    observe_session(store, started.session.id, {
        "kind": "decision",
        "note": "Prefer SQS over Kafka for ops cost on this queue work",
        "ref": "dogfood-intent",
    })

    brief = build_episode_brief(store, ep.id)
    assert brief is not None
    related = gather_related_memories(
        store, embedder, brief, limit=12, session_id=started.session.id,
    )
    arts = [r for r in related if r["status"] == "session_artifact"]
    assert arts, related
    assert "Prefer SQS" in arts[0]["summary"]
    assert related[0]["status"] == "session_artifact"

    seen: dict = {}

    def _fake(brief_in, _cfg):
        seen["related"] = list(brief_in.related_memories)
        return [TrajectoryClaim(
            type="preference",
            domain="technical",
            title="Prefer managed SQS",
            summary="Open-session intent: SQS over Kafka for ops cost.",
            related_memory_ids=[arts[0]["id"]],
            twin_influenced=True,
        )]

    result = reflect_episode(
        store, cfg, embedder, ep.id,
        reflector=_fake, session_id=started.session.id,
    )
    assert result.claims, result.skipped_reason
    assert any(r["status"] == "session_artifact" for r in seen["related"])


def test_llm_reflector_defers_on_model_error(store, cfg, embedder):
    """An overflowing/garbled model reply must defer, never crash the caller.

    Reproduces the CLI traceback where ``complete_json`` raised JSONDecodeError
    on empty model content and propagated out of ``twin episode reflect``.
    """
    import json

    from twin.cognize.services.episode_reflect import _make_llm_reflector

    acc, inst = _acct(store, account_id="acct_boom")
    ep = _pivot_episode(store, cfg, embedder, acc, inst)

    class _Boom:
        def complete_json(self, **_kwargs):
            raise json.JSONDecodeError("no JSON object in model content", "", 0)

    reflector = _make_llm_reflector(_Boom())
    result = reflect_episode(store, cfg, embedder, ep.id, reflector=reflector)
    assert result.claims == []
    assert result.skipped_reason  # deferred, not raised


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
