"""Cross-source correlation — vault partition, episodes, identity, conflicts."""

from __future__ import annotations

from twin.cognize.services.correlation import (
    independence_group_for,
    run_correlation_pass,
)
from twin.cognize.services.correlation.conflicts import detect_temporal_conflicts
from twin.cognize.services.correlation.episodes import correlate_records, extract_github_refs
from twin.cognize.services.correlation.identity import (
    confirm_identity_link,
    propose_identity_links,
    upsert_external_identity,
)
from twin.cognize.services.correlation.independence import evidence_directness_for
from twin.cognize.services.correlation.models import EpisodeLinkStatus
from twin.cognize.services.correlation.projects import link_project, resolve_project_for_record
from twin.cognize.services.sessions import ensure_project
from twin.sense.connectors.models import (
    ConnectorInstance,
    ConnectorRecord,
    ConnectorStatus,
    OwnershipClass,
    SourceAccount,
    idempotency_key,
)
from twin.store.models import FindingType
from twin.sense.sensory.percept import Percept


def _acct(store, *, vault_id: str, account_id: str, connector_type: str = "github"):
    acc = SourceAccount(
        id=account_id,
        connector_type=connector_type,
        external_account_id=account_id,
        owner_principal_id="p1",
        source_owner=OwnershipClass.employer if "work" in vault_id else OwnershipClass.personal,
        vault_id=vault_id,
        org_key="acme" if "work" in vault_id else None,
    )
    store.insert_source_account(acc)
    inst = ConnectorInstance(
        id=f"conn_{account_id}",
        connector_type=connector_type,
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


def test_independence_group_shared_for_notification():
    root = "github:acme/atlas#8"
    pr = {"external_id": "pr", "source_metadata": {"lineage_root": root}}
    note = {
        "external_id": "mail-1",
        "source_metadata": {
            "derived": "likely_notification",
            "lineage_root": root,
            "notification_of": root,
        },
    }
    assert independence_group_for(pr) == independence_group_for(note)


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


def test_extract_github_refs_merge_squash_closing():
    """The forms Git/GitHub actually emit must link a commit to its PR:
    merge-commit subjects, squash-merge ``(#N)`` suffixes and closing keywords.
    A bare unrelated ``#N`` must NOT match (avoid fusing distinct work)."""
    repo = "caribeedu/dogwalker"
    assert extract_github_refs(
        "Merge pull request #8 from caribeedu/v1.1.0", default_repo=repo,
    ) == ["github:caribeedu/dogwalker#8"]
    assert extract_github_refs(
        "fix: apply role context on walker assign (#12)", default_repo=repo,
    ) == ["github:caribeedu/dogwalker#12"]
    for kw in ("closes #5", "fixed #5", "resolves #5"):
        assert extract_github_refs(kw, default_repo=repo) == [
            "github:caribeedu/dogwalker#5"
        ], kw
    # A bare number that is not a recognized PR reference stays unlinked.
    assert extract_github_refs("bumped limit to #99 items", default_repo=repo) == []


def test_pr_fuses_with_merge_commit_sha(store):
    """A merged PR carrying ``merge_commit_sha`` fuses with the commit of that
    sha structurally — no PR reference in the commit message required."""
    acc, inst = _acct(store, vault_id="vault_work_acme", account_id="acct_msha")
    sha = "abc123def456abc123def456abc123def456abcd"
    pr = _rec(
        id="pr_msha",
        connector_id=inst.id,
        source_account_id=acc.id,
        external_type="pull_request",
        external_id="acme/atlas#42",
        content="GitHub pull request acme/atlas#42: ship the thing",
        ownership={"vault_id": "vault_work_acme"},
        source_metadata={
            "lineage_root": "github:acme/atlas#42",
            "repo": "acme/atlas",
            "merge_commit_sha": sha,
        },
    )
    commit = _rec(
        id="cm_msha",
        connector_id=inst.id,
        source_account_id=acc.id,
        external_type="commit",
        external_id=sha,  # commit external_id is the sha
        content="ship the thing\n\nno PR number mentioned anywhere",
        ownership={"vault_id": "vault_work_acme"},
        source_metadata={"repo": "acme/atlas"},
    )
    for r in (pr, commit):
        store.insert_connector_record(r)
    eps = correlate_records(store, [pr, commit], vault_id="vault_work_acme")
    assert eps, "PR and its merge commit should form one episode"
    ext_ids = {
        lk.external_id for ep in eps for lk in store.list_episode_links(ep.id)
    }
    assert "acme/atlas#42" in ext_ids
    assert sha in ext_ids


def test_identity_email_link_same_vault_only(store):
    a = upsert_external_identity(
        store, actor_id="github:edu", source_account_id="gh",
        email="edu@acme.com", vault_id="vault_work_acme",
    )
    b = upsert_external_identity(
        store, actor_id="mail:edu@acme.com", source_account_id="mail",
        email="edu@acme.com", vault_id="vault_work_acme",
    )
    personal = upsert_external_identity(
        store, actor_id="mail:edu@acme.com", source_account_id="personal",
        email="edu@acme.com", vault_id="vault_personal",
    )
    links = propose_identity_links(store, [a, b, personal])
    assert len(links) == 1
    assert links[0].vault_id == "vault_work_acme"
    assert links[0].cross_domain is False
    # Confirm cross-vault refused
    cross = propose_identity_links(store, [a, personal])
    assert cross == [] or all(lk.vault_id != "" for lk in cross)
    # Explicit: no link between work github and personal mail
    assert store.find_identity_link(a.id, personal.id) is None


def test_confirm_identity_cross_vault_rejected(store):
    a = upsert_external_identity(
        store, actor_id="github:x", source_account_id="a1",
        email="x@acme.com", vault_id="vault_work_acme",
    )
    b = upsert_external_identity(
        store, actor_id="mail:x@acme.com", source_account_id="a2",
        email="x@acme.com", vault_id="vault_personal",
    )
    # Manually insert a cross-domain candidate (policy path)
    from twin.cognize.services.correlation.models import IdentityLink, IdentityStatus
    link = IdentityLink(
        left_identity_id=min(a.id, b.id),
        right_identity_id=max(a.id, b.id),
        vault_id="",
        cross_domain=True,
        status=IdentityStatus.candidate,
        signals=["manual_cross_domain"],
    )
    store.insert_identity_link(link)
    try:
        confirm_identity_link(store, link.id)
        assert False, "expected cross-vault confirm to fail"
    except ValueError as exc:
        assert "cross-vault" in str(exc).lower()


def test_project_resolve_from_repo(store):
    acc, inst = _acct(store, vault_id="vault_work_acme", account_id="acct_proj")
    ensure_project(store, "Twin", repos=["acme/twin"])
    rec = _rec(
        connector_id=inst.id,
        source_account_id=acc.id,
        external_type="pull_request",
        external_id="42",
        project_hint="twin",
        ownership={"vault_id": "vault_work_acme"},
        source_metadata={"repo": "acme/twin", "lineage_root": "github:acme/twin#42"},
    )
    pid, link = resolve_project_for_record(store, rec)
    assert pid is not None
    assert link.vault_id == "vault_work_acme"


def test_no_cross_vault_episode(store):
    work, winst = _acct(store, vault_id="vault_work_acme", account_id="acct_w")
    personal, pinst = _acct(
        store, vault_id="vault_personal", account_id="acct_p",
        connector_type="calendar",
    )
    root = "evt_shared_123"
    a = _rec(
        id="r_work",
        connector_id=winst.id,
        source_account_id=work.id,
        external_type="calendar_event",
        external_id="work-evt",
        content="Architecture sync",
        ownership={"vault_id": "vault_work_acme"},
        source_metadata={"calendar_event_id": root},
        occurred_at="2026-07-10T15:00:00Z",
    )
    b = _rec(
        id="r_pers",
        connector_id=pinst.id,
        source_account_id=personal.id,
        external_type="calendar_event",
        external_id="pers-evt",
        content="Architecture sync",
        ownership={"vault_id": "vault_personal"},
        source_metadata={"calendar_event_id": root},
        occurred_at="2026-07-10T15:00:00Z",
    )
    store.insert_connector_record(a)
    store.insert_connector_record(b)
    report = run_correlation_pass(store)
    episodes = store.list_work_episodes()
    # Same calendar_event_id must not fuse across vaults.
    assert all(ep.vault_id in ("vault_work_acme", "vault_personal", "vault_unknown")
               for ep in episodes)
    for ep in episodes:
        vaults = {r.get("vault_id") for r in ep.source_refs if r.get("vault_id")}
        assert len(vaults) <= 1


def test_episode_correlates_slack_mention_of_pr(store):
    acc, inst = _acct(store, vault_id="vault_work_acme", account_id="acct_ep")
    ensure_project(store, "Atlas", repos=["acme/atlas"])
    pr = _rec(
        id="rec_pr",
        connector_id=inst.id,
        source_account_id=acc.id,
        external_type="pull_request",
        external_id="acme/atlas#8",
        content="# Use Redis\n\nShip Friday.",
        occurred_at="2026-07-10T10:00:00Z",
        actor_ids=["github:alice"],
        ownership={"vault_id": "vault_work_acme"},
        project_hint="atlas",
        thread_key="github:acme/atlas#8",
        source_metadata={
            "repo": "acme/atlas",
            "lineage_root": "github:acme/atlas#8",
        },
    )
    slack = _rec(
        id="rec_slack",
        connector_id=inst.id,
        source_account_id=acc.id,
        external_type="message",
        external_id="C1.100",
        content="Release postponed — see PR #8",
        occurred_at="2026-07-11T10:00:00Z",
        actor_ids=["slack:T1:U2"],
        ownership={"vault_id": "vault_work_acme"},
        project_hint="engineering",
        thread_key="slack:C1:100",
        source_metadata={
            "channel_id": "C1",
            "github_refs": ["github:acme/atlas#8"],
            "lineage_root": "github:acme/atlas#8",
            "repo": "acme/atlas",
        },
    )
    store.insert_connector_record(pr)
    store.insert_connector_record(slack)
    episodes = correlate_records(
        store, [pr, slack], vault_id="vault_work_acme",
    )
    assert len(episodes) == 1
    ep = episodes[0]
    assert ep.vault_id == "vault_work_acme"
    assert ep.correlation_key
    assert len(ep.source_refs) == 2
    findings = detect_temporal_conflicts(store, ep)
    assert any(f.type == FindingType.cross_source_temporal_conflict for f in findings)


def test_fingerprint_idempotent(store):
    acc, inst = _acct(
        store, vault_id="vault_work_acme", account_id="acct_fp",
        connector_type="calendar",
    )
    fp = "calmeet:2026-07-15T15:00Z:abcd1234"
    cal = _rec(
        id="cal1",
        connector_id=inst.id,
        source_account_id=acc.id,
        external_type="calendar_event",
        external_id="evt1",
        content="Architecture sync",
        ownership={"vault_id": "vault_work_acme"},
        source_metadata={"correlation_fingerprint": fp},
        occurred_at="2026-07-15T15:00:00Z",
    )
    meet = _rec(
        id="meet1",
        connector_id=inst.id,
        source_account_id=acc.id,
        external_type="meeting_manifest",
        external_id="m1",
        content="Architecture sync transcript",
        ownership={"vault_id": "vault_work_acme"},
        source_metadata={"correlation_fingerprint": fp},
        occurred_at="2026-07-15T15:05:00Z",
    )
    store.insert_connector_record(cal)
    store.insert_connector_record(meet)
    r1 = run_correlation_pass(store, connector_ids=[inst.id])
    r2 = run_correlation_pass(store, connector_ids=[inst.id])
    eps = [e for e in store.list_work_episodes(vault_id="vault_work_acme")
           if e.status.value != "closed"]
    assert len(eps) == 1
    assert r2.episodes_created == 0


def test_single_record_ship_postpone_no_cross_source_finding(store):
    acc, inst = _acct(store, vault_id="vault_work_acme", account_id="acct_one")
    a = _rec(
        id="alone",
        connector_id=inst.id,
        source_account_id=acc.id,
        external_id="x1",
        content="We planned to ship Friday, but it was postponed.",
        ownership={"vault_id": "vault_work_acme"},
        source_metadata={"lineage_root": "github:acme/atlas#1", "repo": "acme/atlas"},
    )
    b = _rec(
        id="other",
        connector_id=inst.id,
        source_account_id=acc.id,
        external_id="x2",
        content="Unrelated note about the PR #1",
        ownership={"vault_id": "vault_work_acme"},
        source_metadata={"lineage_root": "github:acme/atlas#1", "repo": "acme/atlas"},
    )
    store.insert_connector_record(a)
    store.insert_connector_record(b)
    eps = correlate_records(store, [a, b], vault_id="vault_work_acme")
    assert eps
    findings = detect_temporal_conflicts(store, eps[0])
    # ship and postpone live on the same source only → not cross-source
    assert not any(
        "ship_vs_postpone" in str((f.metadata or {}).get("finding_key") or "")
        for f in findings
    )


def test_finding_idempotent_across_passes(store):
    acc, inst = _acct(store, vault_id="vault_work_acme", account_id="acct_find")
    pr = _rec(
        id="f1",
        connector_id=inst.id,
        source_account_id=acc.id,
        external_id="acme/atlas#9",
        content="Ship Friday",
        ownership={"vault_id": "vault_work_acme"},
        source_metadata={"lineage_root": "github:acme/atlas#9", "repo": "acme/atlas"},
        occurred_at="2026-07-10T10:00:00Z",
    )
    slack = _rec(
        id="f2",
        connector_id=inst.id,
        source_account_id=acc.id,
        external_type="message",
        external_id="C.9",
        content="Release postponed — PR #9",
        ownership={"vault_id": "vault_work_acme"},
        source_metadata={"lineage_root": "github:acme/atlas#9", "repo": "acme/atlas"},
        occurred_at="2026-07-11T10:00:00Z",
    )
    store.insert_connector_record(pr)
    store.insert_connector_record(slack)
    run_correlation_pass(store, connector_ids=[inst.id])
    run_correlation_pass(store, connector_ids=[inst.id])
    ep = store.list_work_episodes(vault_id="vault_work_acme")[0]
    findings = store.get_findings(f"episode:{ep.id}", unresolved_only=False)
    open_f = [f for f in findings if f.status.value == "open"]
    keys = {(f.metadata or {}).get("finding_key") for f in open_f}
    assert len(keys) == len(open_f)  # unique keys
    assert len(open_f) <= 2  # ship_vs_postpone (+ maybe dates)


def test_tombstone_removes_membership(store):
    acc, inst = _acct(store, vault_id="vault_work_acme", account_id="acct_tomb")
    pr = _rec(
        id="t1",
        connector_id=inst.id,
        source_account_id=acc.id,
        external_id="acme/atlas#10",
        content="Ship Monday",
        ownership={"vault_id": "vault_work_acme"},
        source_metadata={"lineage_root": "github:acme/atlas#10", "repo": "acme/atlas"},
        occurred_at="2026-07-10T10:00:00Z",
        actor_ids=["github:alice"],
    )
    slack = _rec(
        id="t2",
        connector_id=inst.id,
        source_account_id=acc.id,
        external_type="message",
        external_id="C.10",
        content="Release postponed — PR #10",
        ownership={"vault_id": "vault_work_acme"},
        source_metadata={"lineage_root": "github:acme/atlas#10", "repo": "acme/atlas"},
        occurred_at="2026-07-11T10:00:00Z",
        actor_ids=["slack:T:U"],
    )
    store.insert_connector_record(pr)
    store.insert_connector_record(slack)
    run_correlation_pass(store, connector_ids=[inst.id])
    ep = store.list_work_episodes(vault_id="vault_work_acme")[0]
    assert len(ep.source_refs) == 2

    # Reconcile with slack removed (tombstone)
    correlate_records(
        store, [pr], vault_id="vault_work_acme",
        deleted_record_ids={slack.id},
    )
    ep = store.get_work_episode(ep.id)
    active = [
        lk for lk in store.list_episode_links(ep.id)
        if lk.status == EpisodeLinkStatus.active
    ]
    assert len(active) == 1
    assert active[0].external_id == "acme/atlas#10"
    assert "slack:T:U" not in ep.participant_actor_ids


def test_soft_links_alone_do_not_merge(store):
    acc, inst = _acct(store, vault_id="vault_work_acme", account_id="acct_soft")
    a = _rec(
        id="a", connector_id=inst.id, source_account_id=acc.id,
        external_id="1", content="hello",
        ownership={"vault_id": "vault_work_acme"},
        occurred_at="2026-07-10T10:00:00Z",
        actor_ids=["github:a"],
        source_metadata={},
    )
    b = _rec(
        id="b", connector_id=inst.id, source_account_id=acc.id,
        external_id="2", content="world",
        ownership={"vault_id": "vault_work_acme"},
        occurred_at="2026-07-10T10:05:00Z",
        actor_ids=["github:b"],
        source_metadata={},
    )
    assert correlate_records(store, [a, b], vault_id="vault_work_acme") == []


def test_confirmed_project_link(store):
    proj = ensure_project(store, "Twin", repos=[])
    link = link_project(
        store, project_id=proj.id,
        external_type="slack_channel", external_id="C123",
        confirmed=True,
    )
    assert link.confirmed is True
