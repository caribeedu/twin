"""ACL intersection + narrative tombstone on source revoke."""

from __future__ import annotations

import pytest

from twin.cognize.acl import intersect_sensitivity
from twin.cognize.commit import CommitError, commit_narrative
from twin.cognize.models import EpistemicStatus
from twin.cognition.context_pack import build_context_pack
from twin.memory.embeddings import HashEmbedder
from twin.memory.models import Artifact
from twin.memory.retention import delete_artifact
from twin.privacy.models import AccessRequest
from twin.sense.sensory.percept import Percept, SourceClass


def test_intersect_sensitivity_picks_strictest():
    assert intersect_sensitivity(["public", "private"]) == "private"
    assert intersect_sensitivity(["internal"]) == "internal"


def test_commit_refuses_sensitivity_expansion(store):
    private = Percept(
        percept_type="message",
        source_sensor="slack",
        content="private slack fact",
        source_confidentiality="private",
    )
    store.insert_percept(private)
    with pytest.raises(CommitError, match="expands"):
        commit_narrative(
            store,
            account="derived claim",
            vault_id="default",
            evidence_ids=[private.id],
            committed_by="tester",
            sensitivity="public",
            domain="technical",
        )


def test_tombstone_on_artifact_delete(store):
    p = Percept(
        percept_type="message",
        source_sensor="slack",
        content="secret thread",
        source_confidentiality="private",
    )
    store.insert_percept(p)
    art = Artifact(
        id="art_acl_1",
        kind="message",
        source_system="slack",
        external_id="msg1",
        metadata={"percept_id": p.id},
    )
    store.insert_artifact(art)
    store.link_artifact_percept(art.id, p.id)

    nar = commit_narrative(
        store,
        account="From private Slack",
        vault_id="default",
        evidence_ids=[p.id],
        committed_by="tester",
        domain="technical",
    )
    assert store.get_epistemic_state(nar.epistemic_state_id).status is EpistemicStatus.fresh

    delete_artifact(store, art.id, reason="source_removed")
    eps = store.get_epistemic_state(nar.epistemic_state_id)
    assert eps.status is EpistemicStatus.tombstoned


def test_pack_acl_hides_private_from_client_audience(store, cfg):
    slack = Percept(
        percept_type="message",
        source_sensor="slack",
        content="private decision",
        source_confidentiality="private",
    )
    store.insert_percept(slack)
    nar = commit_narrative(
        store,
        account="Private Slack decision must not leak",
        vault_id="default",
        evidence_ids=[slack.id],
        committed_by="tester",
        domain="technical",
    )
    assert (nar.metadata or {}).get("source_sensors") == ["slack"]

    access = AccessRequest(
        audience="client",
        principal_id="ext",
        persona="individual",
        purpose="memory_retrieval",
        tool_id="test",
        requested_domains=["technical"],
        metadata={"allowed_source_sensors": ["github"]},
    )
    pack = build_context_pack(
        store, cfg, HashEmbedder(),
        query="decision",
        target_domain="technical",
        access=access,
    )
    ids = [n["narrative_id"] for n in pack.narratives]
    assert nar.id not in ids
    assert "Private Slack decision must not leak" not in (pack.context_pack or "")


def test_source_class_persists(store):
    p = Percept(
        percept_type="pull_request",
        source_sensor="github",
        content="opened PR",
    )
    assert p.source_class is SourceClass.code_repo
    store.insert_percept(p)
    loaded = store.get_percept(p.id)
    assert loaded is not None
    assert loaded.source_class is SourceClass.code_repo

    s = Percept(
        percept_type="message",
        source_sensor="slack",
        content="chat",
    )
    assert s.source_class is SourceClass.chat_discussion
