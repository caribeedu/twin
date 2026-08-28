"""Eval: ACL intersection (§9.3 #5)."""

from __future__ import annotations

from twin.cognize.commit import commit_narrative
from twin.inject.context_pack import build_context_pack
from twin.store.embeddings import HashEmbedder
from twin.privacy.models import AccessRequest
from twin.sense.sensory.percept import Percept


def test_eval_acl_intersection_private_slack_plus_public_pr(store, cfg):
    slack = Percept(
        percept_type="message",
        source_sensor="slack",
        content="CANARY_PRIVATE_SLACK_FACT",
        source_confidentiality="private",
    )
    pr = Percept(
        percept_type="pull_request",
        source_sensor="github",
        content="public PR description",
        source_confidentiality="public",
    )
    store.insert_percept(slack)
    store.insert_percept(pr)

    nar = commit_narrative(
        store,
        account="Decision derived from Slack and PR — CANARY_PRIVATE_SLACK_FACT",
        vault_id="default",
        evidence_ids=[slack.id, pr.id],
        committed_by="eval",
        domain="technical",
    )
    assert nar.sensitivity == "private"

    access = AccessRequest(
        audience="client",
        principal_id="no_slack",
        persona="individual",
        purpose="context_retrieval",
        tool_id="test",
        requested_domains=["technical"],
        metadata={"allowed_source_sensors": ["github"], "vault_id": "default"},
    )
    pack = build_context_pack(
        store, cfg, HashEmbedder(),
        query="What was decided?",
        target_domain="technical",
        access=access,
    )
    assert nar.id not in [n["narrative_id"] for n in pack.narratives]
    text = pack.context_pack or ""
    assert "CANARY_PRIVATE_SLACK_FACT" not in text

    owner = AccessRequest(
        audience="self",
        principal_id="owner",
        persona="individual",
        purpose="context_retrieval",
        tool_id="test",
        requested_domains=["technical"],
        metadata={
            "allowed_source_sensors": ["slack", "github"],
            "vault_id": "default",
        },
    )
    pack_ok = build_context_pack(
        store, cfg, HashEmbedder(),
        query="What was decided?",
        target_domain="technical",
        access=owner,
    )
    assert nar.id in [n["narrative_id"] for n in pack_ok.narratives]
