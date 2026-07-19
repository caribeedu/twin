"""v0.6 correlation-depth slice — lifecycle, confidence downgrade, explain."""

from __future__ import annotations

from twin.cognition.correlation.episodes import (
    _rebuild_episode_from_active_links,
    correlate_records,
)
from twin.cognition.correlation.explain import (
    explain_episode,
    explain_identity_link,
    explain_project_link,
)
from twin.cognition.correlation.identity import (
    confirm_identity_link,
    propose_identity_links,
    reject_identity_link,
    unconfirm_identity_link,
    upsert_external_identity,
)
from twin.cognition.correlation.models import (
    EpisodeLinkKind,
    EpisodeLinkStatus,
    EpisodeStatus,
    IdentityStatus,
    ProjectLinkStatus,
    WorkEpisode,
)
from twin.cognition.correlation.projects import (
    archive_project_link,
    link_project,
    reject_project_link,
    resolve_project_for_record,
)
from twin.cognition.sessions import ensure_project
from twin.connectors.models import ConnectorRecord, idempotency_key


def _rec(**kwargs) -> ConnectorRecord:
    defaults = dict(
        connector_id="conn_x",
        source_account_id="acc_x",
        external_type="issue",
        external_id="1",
        external_revision="1",
        content="hello",
        ownership={"vault_id": "vault_work_acme", "source_owner": "employer"},
        actor_ids=["github:alice"],
        source_metadata={"lineage_root": "github:acme/atlas#1", "repo": "acme/atlas"},
        occurred_at="2026-07-10T10:00:00Z",
    )
    defaults.update(kwargs)
    rec = ConnectorRecord(**defaults)
    if not rec.idempotency_key:
        rec.idempotency_key = idempotency_key(
            "test", rec.source_account_id, rec.external_type,
            rec.external_id, rec.external_revision,
        )
    return rec


def test_project_link_lifecycle_historical_not_attachable(store):
    proj = ensure_project(store, "Atlas", repos=["acme/atlas"])
    link = link_project(
        store, project_id=proj.id,
        external_type="github_repository", external_id="acme/atlas",
        confirmed=True,
    )
    assert link.status == ProjectLinkStatus.confirmed
    assert link.confirmed is True

    archive_project_link(store, link.id)
    link = store.get_project_link(link.id)
    assert link.status == ProjectLinkStatus.historical
    assert link.confirmed is False

    rec = _rec()
    project_id, resolved = resolve_project_for_record(store, rec)
    assert project_id is None
    assert resolved is not None
    assert resolved.status == ProjectLinkStatus.historical


def test_project_link_rejected_not_attachable(store):
    proj = ensure_project(store, "Atlas", repos=["acme/atlas"])
    link = link_project(
        store, project_id=proj.id,
        external_type="github_repository", external_id="acme/atlas",
        confirmed=True,
    )
    reject_project_link(store, link.id)
    project_id, resolved = resolve_project_for_record(store, _rec())
    assert project_id is None
    assert resolved.status == ProjectLinkStatus.rejected


def test_legacy_confirmed_bool_migrates_to_status(store):
    from twin.cognition.correlation.models import ProjectLink
    raw = ProjectLink.model_validate({
        "project_id": "p1",
        "external_type": "github_repository",
        "external_id": "acme/x",
        "confirmed": True,
        "confidence": 1.0,
    })
    assert raw.status == ProjectLinkStatus.confirmed
    assert raw.confirmed is True


def test_identity_unconfirm_and_reject(store):
    a = upsert_external_identity(
        store, actor_id="mail:a@acme.test", vault_id="vault_work_acme",
        source_account_id="acc1", email="a@acme.test",
    )
    b = upsert_external_identity(
        store, actor_id="github:alice", vault_id="vault_work_acme",
        source_account_id="acc1", email="a@acme.test",
    )
    links = propose_identity_links(store, [a, b])
    assert links
    link = confirm_identity_link(store, links[0].id, entity_id="entity_alice")
    assert link.status == IdentityStatus.confirmed
    left = store.get_external_identity(a.id)
    assert left.confirmed is True

    unconfirm_identity_link(store, link.id)
    link = store.get_identity_link(link.id)
    assert link.status == IdentityStatus.candidate
    left = store.get_external_identity(a.id)
    assert left.confirmed is False
    assert left.linked_entity_id is None

    reject_identity_link(store, link.id)
    assert store.get_identity_link(link.id).status == IdentityStatus.rejected


def test_episode_confidence_downgrades_when_membership_shrinks(store):
    from twin.cognition.correlation.models import EpisodeLink

    ep = WorkEpisode(
        vault_id="vault_work_acme",
        correlation_key="vault_work_acme:lineage:github:acme/atlas#1",
        title="test",
        confidence=0.95,
        status=EpisodeStatus.active,
    )
    store.insert_work_episode(ep)
    strong = EpisodeLink(
        episode_id=ep.id, vault_id=ep.vault_id,
        external_type="issue", external_id="1",
        kind=EpisodeLinkKind.explicit, confidence=0.95,
        status=EpisodeLinkStatus.active,
        independence_group="lineage:github:acme/atlas#1",
    )
    weak = EpisodeLink(
        episode_id=ep.id, vault_id=ep.vault_id,
        external_type="message", external_id="2",
        kind=EpisodeLinkKind.soft, confidence=0.40,
        status=EpisodeLinkStatus.active,
    )
    store.insert_episode_link(strong)
    store.insert_episode_link(weak)

    ep = _rebuild_episode_from_active_links(store, ep)
    assert ep.confidence == 0.95

    strong.status = EpisodeLinkStatus.removed
    store.update_episode_link(strong)
    ep = _rebuild_episode_from_active_links(store, store.get_work_episode(ep.id))
    assert ep.confidence == 0.40

    weak.status = EpisodeLinkStatus.removed
    store.update_episode_link(weak)
    ep = _rebuild_episode_from_active_links(store, store.get_work_episode(ep.id))
    assert ep.confidence == 0.0
    assert ep.status == EpisodeStatus.closed


def test_explain_episode_and_links(store):
    ensure_project(store, "Atlas", repos=["acme/atlas"])
    a = _rec(id="r1", external_id="1", content="ship it")
    b = _rec(
        id="r2", external_id="2", external_type="message",
        content="postpone the ship",
        source_metadata={
            "lineage_root": "github:acme/atlas#1",
            "repo": "acme/atlas",
        },
        actor_ids=["slack:U1"],
        occurred_at="2026-07-10T11:00:00Z",
    )
    # Persist records so rebuild can load them
    store.insert_connector_record(a)
    store.insert_connector_record(b)
    eps = correlate_records(store, [a, b], vault_id="vault_work_acme")
    assert eps
    explanation = explain_episode(store, eps[0].id)
    assert explanation["episode_id"] == eps[0].id
    assert explanation["vault_id"] == "vault_work_acme"
    assert "confidence_basis" in explanation
    assert explanation["active_links"] >= 1

    proj_links = store.list_project_links()
    if proj_links:
        pe = explain_project_link(store, proj_links[0].id)
        assert pe["link_id"] == proj_links[0].id
        assert "attachable_to_episode" in pe

    idents = [
        upsert_external_identity(
            store, actor_id="mail:x@acme.test", vault_id="vault_work_acme",
            email="x@acme.test",
        ),
        upsert_external_identity(
            store, actor_id="github:x", vault_id="vault_work_acme",
            email="x@acme.test",
        ),
    ]
    links = propose_identity_links(store, [i for i in idents if i])
    if links:
        ie = explain_identity_link(store, links[0].id)
        assert ie["signals"]
        assert "why" in ie
