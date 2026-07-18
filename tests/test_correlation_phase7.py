"""v0.6 Phase 7 — cross-source cognition."""

from __future__ import annotations

from twin.cognition.correlation import (
    independence_group_for,
    run_correlation_pass,
)
from twin.cognition.correlation.conflicts import detect_temporal_conflicts
from twin.cognition.correlation.episodes import correlate_records, extract_github_refs
from twin.cognition.correlation.identity import (
    propose_identity_links,
    upsert_external_identity,
)
from twin.cognition.correlation.independence import evidence_directness_for
from twin.cognition.correlation.projects import link_project, resolve_project_for_record
from twin.cognition.sessions import ensure_project
from twin.connectors.models import (
    ConnectorInstance,
    ConnectorRecord,
    ConnectorStatus,
    OwnershipClass,
    SourceAccount,
    idempotency_key,
)
from twin.memory.models import FindingType
from twin.sensory.percept import Percept


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
    )
    defaults.update(kwargs)
    rec = ConnectorRecord(**defaults)
    if not rec.idempotency_key:
        rec.idempotency_key = idempotency_key(
            "test", rec.source_account_id, rec.external_type,
            rec.external_id, rec.external_revision,
        )
    return rec


def test_independence_group_shared_for_notification():
    root = "github:acme/atlas#8"
    pr = {
        "external_id": "pr",
        "source_metadata": {"lineage_root": root},
    }
    note = {
        "external_id": "mail-1",
        "source_metadata": {
            "derived": "likely_notification",
            "lineage_root": root,
            "notification_of": root,
        },
    }
    assert independence_group_for(pr) == independence_group_for(note)
    assert independence_group_for(note).startswith("lineage:")


def test_derived_evidence_lower_directness():
    p = Percept(
        percept_type="connector_issue_comment",
        source_sensor="github",
        content="bot says decided postgres",
        metadata={"source_metadata": {"derived": "likely_notification",
                                      "lineage_root": "github:r#1"}},
    )
    assert evidence_directness_for(p) < 0.5


def test_extract_github_refs():
    refs = extract_github_refs(
        "See PR #8 and https://github.com/acme/atlas/pull/9",
        default_repo="acme/atlas",
    )
    assert "github:acme/atlas#8" in refs
    assert "github:acme/atlas#9" in refs


def test_identity_email_link_not_auto_confirmed(store):
    a = upsert_external_identity(
        store, actor_id="github:edu", source_account_id="gh",
        email="edu@acme.com",
    )
    b = upsert_external_identity(
        store, actor_id="mail:edu@acme.com", source_account_id="mail",
        email="edu@acme.com",
    )
    links = propose_identity_links(store, [a, b])
    assert len(links) == 1
    assert links[0].status.value == "candidate"
    assert links[0].confidence >= 0.9
    # Name-only must not create links
    c = upsert_external_identity(
        store, actor_id="slack:T1:U1", source_account_id="sl",
        display_name="Edu",
    )
    more = propose_identity_links(store, [a, b, c])
    assert all("shared_email" in lk.signals or "same_provider" in str(lk.signals)
               for lk in more) or more == []


def test_project_resolve_from_repo(store):
    ensure_project(store, "Twin", repos=["acme/twin"])
    rec = _rec(
        external_type="pull_request",
        external_id="42",
        project_hint="twin",
        source_metadata={"repo": "acme/twin", "lineage_root": "github:acme/twin#42"},
    )
    pid, link = resolve_project_for_record(store, rec)
    assert pid is not None
    assert link is not None
    assert link.external_type == "github_repository"
    assert link.confirmed is False


def test_episode_correlates_slack_mention_of_pr(store):
    ensure_project(store, "Atlas", repos=["acme/atlas"])
    pr = _rec(
        id="rec_pr",
        external_type="pull_request",
        external_id="acme/atlas#8",
        content="# Use Redis\n\nShip Friday.",
        occurred_at="2026-07-10T10:00:00Z",
        actor_ids=["github:alice"],
        project_hint="atlas",
        thread_key="github:acme/atlas#8",
        source_metadata={
            "repo": "acme/atlas",
            "lineage_root": "github:acme/atlas#8",
        },
    )
    slack = _rec(
        id="rec_slack",
        connector_id="conn_slack",
        source_account_id="acct_slack",
        external_type="message",
        external_id="C1.100",
        content="Release postponed — see PR #8",
        occurred_at="2026-07-11T10:00:00Z",
        actor_ids=["slack:T1:U2"],
        project_hint="engineering",
        thread_key="slack:C1:100",
        source_metadata={
            "channel_id": "C1",
            "github_refs": ["github:acme/atlas#8"],
            "lineage_root": "github:acme/atlas#8",
        },
    )
    store.insert_connector_record(pr)
    store.insert_connector_record(slack)
    episodes = correlate_records(store, [pr, slack])
    assert len(episodes) == 1
    ep = episodes[0]
    assert len(ep.source_refs) == 2
    assert ep.independence_group == "lineage:github:acme/atlas#8"
    assert ep.project_id  # mapped via repo

    findings = detect_temporal_conflicts(store, ep)
    assert any(
        f.type == FindingType.cross_source_temporal_conflict for f in findings
    )


def test_notification_does_not_split_independence_group(store):
    root = "github:acme/atlas#1"
    human = _rec(
        id="rec_human",
        external_type="issue_comment",
        external_id="c1",
        content="We decided PostgreSQL.",
        source_metadata={"lineage_root": root, "repo": "acme/atlas"},
        actor_ids=["github:alice"],
    )
    bot = _rec(
        id="rec_bot",
        external_type="issue_comment",
        external_id="c2",
        content="[bot] We decided PostgreSQL.",
        source_metadata={
            "lineage_root": root,
            "derived": "likely_notification",
            "notification_of": root,
            "repo": "acme/atlas",
        },
        actor_ids=["github:release-bot[bot]"],
        confidentiality={"source_trust": 0.5},
    )
    g_human = independence_group_for({
        "source_metadata": human.source_metadata,
        "external_id": human.external_id,
    })
    g_bot = independence_group_for({
        "source_metadata": bot.source_metadata,
        "external_id": bot.external_id,
    })
    assert g_human == g_bot


def test_run_correlation_pass_end_to_end(store):
    ensure_project(store, "Atlas", repos=["acme/atlas"])

    acc = SourceAccount(
        id="acct_gh",
        connector_type="github",
        external_account_id="edu",
        owner_principal_id="p1",
        source_owner=OwnershipClass.employer,
        vault_id="vault_work_acme",
        org_key="acme",
    )
    store.insert_source_account(acc)
    inst = ConnectorInstance(
        id="conn_gh",
        connector_type="github",
        account_id=acc.id,
        status=ConnectorStatus.active,
    )
    store.insert_connector_instance(inst)

    pr = _rec(
        id="r1",
        connector_id=inst.id,
        source_account_id=acc.id,
        external_id="acme/atlas#3",
        content="Implement caching. Due 2026-07-18.",
        actor_ids=["github:alice", "mail:alice@acme.com"],
        source_metadata={
            "repo": "acme/atlas",
            "lineage_root": "github:acme/atlas#3",
        },
        occurred_at="2026-07-10T10:00:00Z",
    )
    slack = _rec(
        id="r2",
        connector_id=inst.id,
        source_account_id=acc.id,
        external_type="message",
        external_id="C.200",
        content="Deadline moved to 2026-07-25 — PR #3",
        actor_ids=["slack:T:U"],
        source_metadata={
            "lineage_root": "github:acme/atlas#3",
            "repo": "acme/atlas",
        },
        occurred_at="2026-07-12T10:00:00Z",
    )
    store.insert_connector_record(pr)
    store.insert_connector_record(slack)

    report = run_correlation_pass(store, connector_ids=[inst.id])
    assert report.records_scanned == 2
    assert report.identities >= 2
    assert report.episodes >= 1
    assert report.conflicts >= 1


def test_soft_links_alone_do_not_merge(store):
    a = _rec(
        id="a", external_id="1", content="hello",
        occurred_at="2026-07-10T10:00:00Z",
        actor_ids=["github:a"],
        source_metadata={},
    )
    b = _rec(
        id="b", external_id="2", content="world",
        occurred_at="2026-07-10T10:05:00Z",
        actor_ids=["github:b"],
        source_metadata={},
    )
    episodes = correlate_records(store, [a, b])
    assert episodes == []


def test_confirmed_project_link(store):
    proj = ensure_project(store, "Twin", repos=[])
    link = link_project(
        store, project_id=proj.id,
        external_type="slack_channel", external_id="C123",
        confirmed=True,
    )
    assert link.confirmed is True
    found = store.find_project_link(
        external_type="slack_channel", external_id="C123",
    )
    assert found is not None
    assert found.project_id == proj.id
