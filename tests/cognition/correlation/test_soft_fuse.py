"""PR-lineage singletons + Slack↔GitHub soft-fuse."""
from __future__ import annotations

from twin.cognize.services.correlation.episodes import correlate_records
from twin.cognize.services.correlation.projects import link_project
from twin.cognize.services.sessions import ensure_project
from twin.sense.connectors.models import (
    ConnectorInstance,
    ConnectorRecord,
    ConnectorStatus,
    OwnershipClass,
    SourceAccount,
    idempotency_key,
)


def _acct(store, *, vault_id: str, account_id: str, connector_type: str):
    acc = SourceAccount(
        id=account_id,
        connector_type=connector_type,
        external_account_id=account_id,
        owner_principal_id="p1",
        source_owner=OwnershipClass.personal,
        vault_id=vault_id,
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
        connector_id="conn_x",
        source_account_id="acct_x",
        external_type="commit",
        external_id="sha1",
        external_revision="1",
        content="hello",
        actor_ids=[],
        ownership={"vault_id": "vault_dogfood"},
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


def test_merge_commit_alone_opens_pr_episode(store):
    """A 'Merge pull request #N' commit opens an episode without the PR record."""
    acc, inst = _acct(
        store, vault_id="vault_dogfood", account_id="gh1", connector_type="github",
    )
    commit = _rec(
        id="cm_pr11",
        connector_id=inst.id,
        source_account_id=acc.id,
        external_type="commit",
        external_id="b14435ee1cc1deadbeef001122334455667788",
        content="Merge pull request #11 from caribeedu/v1.1.0-presets",
        occurred_at="2026-08-01T01:24:17Z",
        ownership={"vault_id": "vault_dogfood"},
        source_metadata={"repo": "caribeedu/dogwalker"},
    )
    store.insert_connector_record(commit)
    eps = correlate_records(store, [commit], vault_id="vault_dogfood")
    assert len(eps) == 1
    assert "presets" in (eps[0].title or "").lower() or "#11" in (eps[0].title or "")


def test_slack_soft_fuses_into_pr_merge_episode(store):
    """Same project + lexical overlap + time window → Slack joins the PR episode."""
    proj = ensure_project(store, "Dogwalker", repos=["caribeedu/dogwalker"])
    gh_acc, gh_inst = _acct(
        store, vault_id="vault_dogfood", account_id="gh2", connector_type="github",
    )
    sl_acc, sl_inst = _acct(
        store, vault_id="vault_dogfood", account_id="sl2", connector_type="slack",
    )
    link_project(
        store, project_id=proj.id,
        external_type="github_repository", external_id="caribeedu/dogwalker",
        confirmed=True,
    )
    link_project(
        store, project_id=proj.id,
        external_type="slack_channel", external_id="C0BM8DT14S2",
        confirmed=True,
    )
    commit = _rec(
        id="cm_fuse",
        connector_id=gh_inst.id,
        source_account_id=gh_acc.id,
        external_type="commit",
        external_id="a3bb49ba1eaddeadbeef001122334455667788",
        content=(
            "Merge pull request #11 from caribeedu/v1.1.0\n\n"
            "feat: manage roles and walker presets"
        ),
        occurred_at="2026-08-01T01:24:17Z",
        ownership={"vault_id": "vault_dogfood"},
        source_metadata={"repo": "caribeedu/dogwalker"},
    )
    slack = _rec(
        id="sl_fuse",
        connector_id=sl_inst.id,
        source_account_id=sl_acc.id,
        external_type="message",
        external_id="C0BM8DT14S2:1722475604.0001",
        content=(
            "Slack message in #product by John:\n"
            "@Edu Dogwalker needs to have presets and roles implemented "
            "in order to be launched. Can you do it?"
        ),
        occurred_at="2026-08-01T01:26:44Z",
        ownership={"vault_id": "vault_dogfood"},
        source_metadata={
            "channel": "C0BM8DT14S2", "team_id": "T0BMCA2G1S5",
            "author_kind": "human", "ts": "1722475604.0001",
        },
        project_hint="C0BM8DT14S2",
    )
    for r in (commit, slack):
        store.insert_connector_record(r)
    eps = correlate_records(store, [commit, slack], vault_id="vault_dogfood")
    assert eps, "expected a fused episode"
    # Prefer the multi-sense episode
    multi = [e for e in eps if (e.metadata or {}).get("cross_sense_soft_fuse")]
    assert multi, f"expected soft-fuse metadata; got {[e.metadata for e in eps]}"
    ext = {
        lk.external_id
        for ep in multi
        for lk in store.list_episode_links(ep.id)
    }
    assert commit.external_id in ext
    assert slack.external_id in ext


def test_soft_fuse_ignores_non_pr_commits(store):
    """Lexical overlap with a random feature commit must not fuse Slack."""
    proj = ensure_project(store, "Dogwalker", repos=["caribeedu/dogwalker"])
    gh_acc, gh_inst = _acct(
        store, vault_id="vault_dogfood", account_id="gh3", connector_type="github",
    )
    sl_acc, sl_inst = _acct(
        store, vault_id="vault_dogfood", account_id="sl3", connector_type="slack",
    )
    link_project(
        store, project_id=proj.id,
        external_type="github_repository", external_id="caribeedu/dogwalker",
        confirmed=True,
    )
    link_project(
        store, project_id=proj.id,
        external_type="slack_channel", external_id="C0BM8DT14S2",
        confirmed=True,
    )
    noisy = _rec(
        id="cm_noisy",
        connector_id=gh_inst.id,
        source_account_id=gh_acc.id,
        external_type="commit",
        external_id="22f448d1eaddeadbeef00112233445566778899",
        content="feat: order presets and roles UI polish",
        occurred_at="2026-07-22T12:00:00Z",
        ownership={"vault_id": "vault_dogfood"},
        source_metadata={"repo": "caribeedu/dogwalker"},
    )
    slack = _rec(
        id="sl_noisy",
        connector_id=sl_inst.id,
        source_account_id=sl_acc.id,
        external_type="message",
        external_id="C0BM8DT14S2:1722475604.0002",
        content=(
            "Slack message in #product by John:\n"
            "@Edu Dogwalker needs to have presets and roles implemented "
            "in order to be launched."
        ),
        occurred_at="2026-08-01T01:26:44Z",
        ownership={"vault_id": "vault_dogfood"},
        source_metadata={
            "channel": "C0BM8DT14S2", "team_id": "T0BMCA2G1S5",
            "author_kind": "human", "ts": "1722475604.0002",
        },
        project_hint="C0BM8DT14S2",
    )
    for r in (noisy, slack):
        store.insert_connector_record(r)
    eps = correlate_records(store, [noisy, slack], vault_id="vault_dogfood")
    multi = [e for e in eps if (e.metadata or {}).get("cross_sense_soft_fuse")]
    assert not multi, "non-PR commit must not soft-fuse with Slack"


def test_soft_fuse_prefers_matching_pr_over_unrelated_pr(store):
    """Among PR targets, attach Slack to the lexically best match (#11)."""
    proj = ensure_project(store, "Dogwalker", repos=["caribeedu/dogwalker"])
    gh_acc, gh_inst = _acct(
        store, vault_id="vault_dogfood", account_id="gh4", connector_type="github",
    )
    sl_acc, sl_inst = _acct(
        store, vault_id="vault_dogfood", account_id="sl4", connector_type="slack",
    )
    link_project(
        store, project_id=proj.id,
        external_type="github_repository", external_id="caribeedu/dogwalker",
        confirmed=True,
    )
    link_project(
        store, project_id=proj.id,
        external_type="slack_channel", external_id="C0BM8DT14S2",
        confirmed=True,
    )
    launch = _rec(
        id="cm_launch5",
        connector_id=gh_inst.id,
        source_account_id=gh_acc.id,
        external_type="commit",
        external_id="bbbbbbbb1eaddeadbeef001122334455667788",
        content="Merge pull request #5 from caribeedu/launch-gate",
        occurred_at="2026-07-28T10:00:00Z",
        ownership={"vault_id": "vault_dogfood"},
        source_metadata={"repo": "caribeedu/dogwalker"},
    )
    presets = _rec(
        id="cm_pr11b",
        connector_id=gh_inst.id,
        source_account_id=gh_acc.id,
        external_type="commit",
        external_id="cccccccc1eaddeadbeef001122334455667788",
        content=(
            "Merge pull request #11 from caribeedu/v1.1.0\n\n"
            "feat: manage roles and walker presets"
        ),
        occurred_at="2026-08-01T01:24:17Z",
        ownership={"vault_id": "vault_dogfood"},
        source_metadata={"repo": "caribeedu/dogwalker"},
    )
    slack = _rec(
        id="sl_prefer",
        connector_id=sl_inst.id,
        source_account_id=sl_acc.id,
        external_type="message",
        external_id="C0BM8DT14S2:1722475604.0003",
        content=(
            "Slack message in #product by John:\n"
            "@Edu Dogwalker needs to have presets and roles implemented "
            "in order to be launched. Can you do it?"
        ),
        occurred_at="2026-08-01T01:26:44Z",
        ownership={"vault_id": "vault_dogfood"},
        source_metadata={
            "channel": "C0BM8DT14S2", "team_id": "T0BMCA2G1S5",
            "author_kind": "human", "ts": "1722475604.0003",
        },
        project_hint="C0BM8DT14S2",
    )
    for r in (launch, presets, slack):
        store.insert_connector_record(r)
    eps = correlate_records(store, [launch, presets, slack], vault_id="vault_dogfood")
    multi = [e for e in eps if (e.metadata or {}).get("cross_sense_soft_fuse")]
    assert len(multi) == 1
    members = {
        lk.external_id
        for lk in store.list_episode_links(multi[0].id)
    }
    assert presets.external_id in members
    assert slack.external_id in members
    assert launch.external_id not in members


def test_soft_fuse_prefers_temporally_nearest_pr(store):
    """Same lexical overlap → attach to the PR merged nearest the Slack ask."""
    proj = ensure_project(store, "Dogwalker", repos=["caribeedu/dogwalker"])
    gh_acc, gh_inst = _acct(
        store, vault_id="vault_dogfood", account_id="gh5", connector_type="github",
    )
    sl_acc, sl_inst = _acct(
        store, vault_id="vault_dogfood", account_id="sl5", connector_type="slack",
    )
    link_project(
        store, project_id=proj.id,
        external_type="github_repository", external_id="caribeedu/dogwalker",
        confirmed=True,
    )
    link_project(
        store, project_id=proj.id,
        external_type="slack_channel", external_id="C0BM8DT14S2",
        confirmed=True,
    )
    near = _rec(
        id="cm_near11",
        connector_id=gh_inst.id,
        source_account_id=gh_acc.id,
        external_type="commit",
        external_id="dddddddd1eaddeadbeef001122334455667788",
        content=(
            "Merge pull request #11 from caribeedu/v1.1.0\n\n"
            "feat: manage roles and walker presets"
        ),
        occurred_at="2026-08-01T01:24:17Z",
        ownership={"vault_id": "vault_dogfood"},
        source_metadata={"repo": "caribeedu/dogwalker"},
    )
    later = _rec(
        id="cm_later13",
        connector_id=gh_inst.id,
        source_account_id=gh_acc.id,
        external_type="commit",
        external_id="eeeeeeee1eaddeadbeef001122334455667788",
        content=(
            "Merge pull request #13 from caribeedu/hardening\n\n"
            "feat: harden role and preset management for local presets and roles"
        ),
        occurred_at="2026-08-01T03:11:27Z",
        ownership={"vault_id": "vault_dogfood"},
        source_metadata={"repo": "caribeedu/dogwalker"},
    )
    slack = _rec(
        id="sl_near",
        connector_id=sl_inst.id,
        source_account_id=sl_acc.id,
        external_type="message",
        external_id="C0BM8DT14S2:1722475604.0004",
        content=(
            "Slack message in #product by John:\n"
            "@Edu Dogwalker needs to have presets and roles implemented "
            "in order to be launched. Can you do it?"
        ),
        occurred_at="2026-08-01T01:26:44Z",
        ownership={"vault_id": "vault_dogfood"},
        source_metadata={
            "channel": "C0BM8DT14S2", "team_id": "T0BMCA2G1S5",
            "author_kind": "human", "ts": "1722475604.0004",
        },
        project_hint="C0BM8DT14S2",
    )
    for r in (near, later, slack):
        store.insert_connector_record(r)
    eps = correlate_records(store, [near, later, slack], vault_id="vault_dogfood")
    multi = [e for e in eps if (e.metadata or {}).get("cross_sense_soft_fuse")]
    assert len(multi) == 1
    members = {lk.external_id for lk in store.list_episode_links(multi[0].id)}
    assert near.external_id in members
    assert slack.external_id in members
    assert later.external_id not in members
