"""Analysis Context Compiler — dossier compile, budget, soft cross-sense.

The flagship success criterion: a standalone Slack symptom and a GitHub fix in
the same project/time window end up together in one dossier **without** an
explicit correlation anchor between them.
"""

from __future__ import annotations

import pytest

from twin.cognize.services import BrainStage, run_episode_cognition
from twin.cognize.services.analysis_dossier import (
    compile_episode_dossier,
    compile_window_dossier,
)
from twin.sense.connectors.models import (
    ConnectorInstance,
    ConnectorStatus,
    ConnectorRecord,
    OwnershipClass,
    SourceAccount,
    idempotency_key,
)


def _acct(store, *, vault_id="vault_work_acme", account_id="acct_acc"):
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


_LONG_PR = (
    "GitHub pull request acme/atlas!7: Fix idempotency in the payments webhook "
    "handler.\nstate: MERGED\n"
    + "The payments webhook double-charged customers on retried deliveries. "
    "We add an idempotency key keyed on the provider event id so a redelivered "
    "webhook is a no-op. This closes the double-charge path reported by ops. "
    * 12
)


def _github_episode(store, cfg, embedder, acc, inst):
    lineage = "github:acme/atlas#7"
    pr = _rec(
        id="gh_pr", connector_id=inst.id, source_account_id=acc.id,
        external_type="pull_request", external_id="acme/atlas!7",
        content=_LONG_PR,
        occurred_at="2026-07-10T09:00:00Z",
        actor_ids=["github:edu"],
        ownership={"vault_id": acc.vault_id},
        source_metadata={"lineage_root": lineage, "repo": "acme/atlas",
                         "provider": "github"},
    )
    commit = _rec(
        id="gh_commit", connector_id=inst.id, source_account_id=acc.id,
        external_type="commit", external_id="abc7",
        content="Commit abc7 in acme/atlas by Edu: add idempotency key on "
                "payments webhook provider event id.",
        occurred_at="2026-07-10T11:00:00Z",
        actor_ids=["github:edu"],
        ownership={"vault_id": acc.vault_id},
        source_metadata={"lineage_root": lineage, "repo": "acme/atlas",
                         "provider": "github"},
    )
    for r in (pr, commit):
        store.insert_connector_record(r)
    report = run_episode_cognition(
        store, cfg, embedder, mode="full", until=BrainStage.sensory,
    )
    return store.get_work_episode(report.episode_ids[0])


def test_primary_evidence_exceeds_700_chars(store, cfg, embedder):
    acc, inst = _acct(store, account_id="acct_big")
    ep = _github_episode(store, cfg, embedder, acc, inst)
    dossier = compile_episode_dossier(store, embedder, ep.id)
    assert dossier is not None
    assert dossier.primary, "expected primary blobs"
    longest = max(len(b.text) for b in dossier.primary)
    assert longest > 700, "primary must break the old 700-char ceiling"
    assert any(b.tier == "l2" for b in dossier.primary)


def test_cross_sense_links_slack_symptom_to_github_fix(store, cfg, embedder):
    """Gold: standalone Slack symptom + GitHub fix, no explicit anchor."""
    acc, inst = _acct(store, account_id="acct_gold")
    # A Slack message reporting the symptom — no lineage_root, its own thread,
    # so it never joins the GitHub episode structurally.
    slack = _rec(
        id="slack_symptom", connector_id=inst.id, source_account_id=acc.id,
        external_type="channel_message", external_id="C1:1699",
        content="ops: the payments webhook is double-charging customers on "
                "retried deliveries — looks like an idempotency bug, can "
                "someone take a look?",
        occurred_at="2026-07-10T08:30:00Z",
        actor_ids=["slack:edu"],
        thread_key="slack:acme:C1:1699",
        ownership={"vault_id": acc.vault_id},
        source_metadata={"provider": "slack", "channel_id": "C1"},
    )
    store.insert_connector_record(slack)
    ep = _github_episode(store, cfg, embedder, acc, inst)

    dossier = compile_episode_dossier(store, embedder, ep.id)
    assert dossier is not None
    cross_refs = {b.ref for b in dossier.cross_sense}
    assert "channel_message:C1:1699" in cross_refs, (
        f"slack symptom missing from cross_sense: {cross_refs}"
    )
    slack_blob = next(b for b in dossier.cross_sense
                      if b.ref == "channel_message:C1:1699")
    assert slack_blob.sense == "slack"
    assert "topic" in slack_blob.anchors
    # compiler flags the unlinked symptom → remediation opportunity
    assert any("resolves" in g or "raised" in g for g in dossier.gaps)
    # lenses include both senses so the analyzer reads each differently
    lens_senses = {l["sense"] for l in dossier.lenses}
    assert "github" in lens_senses and "slack" in lens_senses


def test_unrelated_same_day_record_is_not_cross_sense(store, cfg, embedder):
    acc, inst = _acct(store, account_id="acct_noise")
    noise = _rec(
        id="slack_noise", connector_id=inst.id, source_account_id=acc.id,
        external_type="channel_message", external_id="C9:1",
        content="lunch plans for friday, anyone up for tacos near the office?",
        occurred_at="2026-07-10T08:30:00Z",
        actor_ids=["slack:someone"],
        thread_key="slack:acme:C9:1",
        ownership={"vault_id": acc.vault_id},
        source_metadata={"provider": "slack", "channel_id": "C9"},
    )
    store.insert_connector_record(noise)
    ep = _github_episode(store, cfg, embedder, acc, inst)
    dossier = compile_episode_dossier(store, embedder, ep.id)
    refs = {b.ref for b in dossier.cross_sense}
    assert "channel_message:C9:1" not in refs


def test_budget_report_records_dropped(store, cfg, embedder):
    acc, inst = _acct(store, account_id="acct_budget")
    ep = _github_episode(store, cfg, embedder, acc, inst)
    dossier = compile_episode_dossier(store, embedder, ep.id, budget_chars=150)
    assert dossier.budget.max_chars == 150
    assert dossier.budget.used_chars <= 150
    assert dossier.budget.dropped, "tiny budget must drop and audit pieces"


def test_window_dossier_scopes_to_project(store, cfg, embedder):
    acc, inst = _acct(store, account_id="acct_window")
    _github_episode(store, cfg, embedder, acc, inst)
    dossier = compile_window_dossier(
        store, embedder, vault_id=acc.vault_id,
        time_from="2026-07-01T00:00:00Z", time_until="2026-07-31T00:00:00Z",
    )
    assert dossier.focus.kind == "window"
    assert dossier.primary, "window should gather records in range"
