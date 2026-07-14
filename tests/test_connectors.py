"""v0.6 Phase 1 — connector framework contract suite (on FakeConnector).

Proves the framework invariants without any real provider:

- nothing becomes cognitively visible before a consistent commit: a partial
  batch persists no Records and no Percepts, and the retry lands everything
  together;
- batch committed ⇔ checkpoint references that batch — fault injection
  between the two cannot produce a divergent state;
- one worker per (connector, stream): leases, not hope;
- an external revision is immutable — same key + different content is a
  collision (DLQ), never an overwrite;
- credentials fail closed (no crypto backend → no connector), are written
  atomically under a lock, and survive corruption via backup;
- provisioning and revocation are compensable/resumable;
- MCP/API connector surfaces demand connector:* capabilities;
- deletions resolve lineage into a deletion event instead of silently
  keeping (or dropping) derived memory.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

import pytest

from twin.connectors import (
    CredentialBackendUnavailable,
    add_connector_instance,
    build_credential_store,
    connector_health,
    reclassify_source_account,
    register_source_account,
    retry_dead_letter,
    revoke_connector,
    sanitize_error,
    sync_connector,
    validate_account_vault,
)
from twin.connectors.fake import _MALICIOUS

PRINCIPAL = "principal_test_owner"


@pytest.fixture()
def creds(tmp_path):
    return build_credential_store(tmp_path / "creds-home")


def _make(store, creds, *, source_owner="personal", org_key=None, vault_id=None,
          secret="tok-secret-value", configuration=None):
    acc = register_source_account(
        store, connector_type="fake", source_owner=source_owner,
        org_key=org_key, vault_id=vault_id, owner_principal_id=PRINCIPAL,
    )
    inst = add_connector_instance(
        store, creds, account_id=acc.id, secret=secret, configuration=configuration,
    )
    return acc, inst


# -- happy path + lineage -------------------------------------------------------


def test_sync_produces_raw_record_and_percept_with_lineage(store, creds):
    acc, inst = _make(store, creds, source_owner="employer", org_key="acme")
    result = sync_connector(store, creds, inst.id)

    assert result.health.value == "healthy"
    assert len(store.list_connector_raw_items(inst.id)) == 3
    assert len(store.list_connector_records(inst.id)) == 3
    percepts = store.list_percepts()
    assert len(percepts) == 3
    for p in percepts:
        assert p.metadata["source_account_id"] == acc.id
        assert p.metadata["source_owner"] == "employer"
        assert p.metadata["vault_id"] == "vault_work_acme"
        assert p.metadata["connector_id"] == inst.id
    assert acc.owner_principal_id == PRINCIPAL


def test_account_requires_owner_principal(store):
    with pytest.raises(Exception):  # pydantic/service — no privileged default
        register_source_account(
            store, connector_type="fake", source_owner="personal",
            owner_principal_id="",
        )


def test_employer_requires_org_key_even_with_explicit_vault(store):
    with pytest.raises(ValueError, match="org_key"):
        register_source_account(
            store, connector_type="fake", source_owner="employer",
            vault_id="vault_work_acme", owner_principal_id=PRINCIPAL,
        )
    with pytest.raises(ValueError, match="org_key"):
        register_source_account(
            store, connector_type="fake", source_owner="client",
            vault_id="vault_work_x", owner_principal_id=PRINCIPAL,
        )


def test_second_sync_is_idempotent(store, creds):
    _acc, inst = _make(store, creds)
    sync_connector(store, creds, inst.id)
    second = sync_connector(store, creds, inst.id)
    assert second.percepts == 0
    assert len(store.list_connector_records(inst.id)) == 3
    assert len(store.list_percepts()) == 3


# -- checkpoint discipline -------------------------------------------------------


def test_checkpoint_advances_only_after_commit(store, creds):
    _acc, inst = _make(store, creds)
    assert store.get_connector_checkpoint(inst.id, "issues") is None
    sync_connector(store, creds, inst.id)
    ckpt = store.get_connector_checkpoint(inst.id, "issues")
    assert ckpt is not None
    assert ckpt.cursor.get("seq") == 2
    assert ckpt.committed_batch_id is not None
    assert ckpt.version == 1
    # the committed batch and the checkpoint reference each other
    batch = store.get_connector_batch(ckpt.committed_batch_id)
    assert batch is not None and batch.status.value == "committed"


def test_partial_failure_persists_nothing_cognitive(store, creds):
    """A partially failed batch leaves NO records and NO percepts — nothing
    from an uncommitted stream is visible to extraction. Raw items persist
    (source cache for DLQ replay); the checkpoint stays put."""
    _acc, inst = _make(store, creds, configuration={"normalize_fail_ids": ["1"]})
    result = sync_connector(store, creds, inst.id)
    issues = next(s for s in result.streams if s.stream == "issues")
    assert issues.committed is False
    assert issues.failed == 1
    assert store.get_connector_checkpoint(inst.id, "issues") is None
    assert len(store.list_connector_dead_letters(inst.id)) == 1
    # the good item of the failed stream did NOT become a record or percept
    records = store.list_connector_records(inst.id)
    assert all(r.external_type != "issue" for r in records)
    percept_types = {p.percept_type for p in store.list_percepts()}
    assert "connector_issue" not in percept_types


def test_partial_failure_retry_delivers_everything_together(store, creds):
    _acc, inst = _make(store, creds, configuration={"normalize_fail_ids": ["1"]})
    sync_connector(store, creds, inst.id)
    assert not [r for r in store.list_connector_records(inst.id)
                if r.external_type == "issue"]
    # heal the adapter and retry: both issues land in one committed batch
    store.update_connector_instance(inst.id, configuration={})
    result = sync_connector(store, creds, inst.id)
    issues = next(s for s in result.streams if s.stream == "issues")
    assert issues.committed is True
    issue_records = [r for r in store.list_connector_records(inst.id)
                     if r.external_type == "issue"]
    assert len(issue_records) == 2
    assert all(r.percept_id for r in issue_records)
    assert store.get_connector_checkpoint(inst.id, "issues") is not None


def test_fault_between_commit_and_checkpoint_cannot_diverge(store, creds, monkeypatch):
    """Fault injection on the finalize transaction: whatever fails, the
    invariant `batch committed ⇔ checkpoint advanced` holds."""
    _acc, inst = _make(store, creds)

    original = store.update_connector_batch
    def failing_update(batch):
        if batch.status.value == "committed":
            raise RuntimeError("crash while marking batch committed")
        return original(batch)

    monkeypatch.setattr(store, "update_connector_batch", failing_update)
    with pytest.raises(RuntimeError):
        sync_connector(store, creds, inst.id)
    monkeypatch.undo()

    # nothing committed, checkpoint untouched, nothing cognitive persisted —
    # and the batch landed in a terminal `aborted` state, never `fetching`
    assert store.get_connector_checkpoint(inst.id, "issues") is None
    statuses = [b.status.value for b in store.list_connector_batches(inst.id)]
    assert "committed" not in statuses
    assert "fetching" not in statuses
    assert "aborted" in statuses
    assert store.list_percepts() == []
    assert store.list_connector_records(inst.id) == []

    # a healthy retry completes the whole stream
    result = sync_connector(store, creds, inst.id)
    assert result.percepts == 3
    assert store.get_connector_checkpoint(inst.id, "issues") is not None


def test_checkpoint_cas_failure_aborts_batch(store, creds, monkeypatch):
    _acc, inst = _make(store, creds)
    monkeypatch.setattr(store, "cas_connector_checkpoint",
                        lambda checkpoint, expected_version: False)
    result = sync_connector(store, creds, inst.id)
    assert all(not s.committed for s in result.streams)
    assert store.get_connector_checkpoint(inst.id, "issues") is None
    assert store.list_percepts() == []          # aborted tx rolled back
    statuses = {b.status.value for b in store.list_connector_batches(inst.id)}
    assert "committed" not in statuses
    assert "aborted" in statuses


def test_checkpoint_cas_rejects_stale_version(store, creds):
    from twin.connectors.models import ConnectorCheckpoint

    _acc, inst = _make(store, creds)
    sync_connector(store, creds, inst.id)          # version 1
    ckpt = store.get_connector_checkpoint(inst.id, "issues")
    assert ckpt.version == 1
    stale = ConnectorCheckpoint(connector_id=inst.id, stream="issues",
                                cursor={"seq": 0})
    # a worker that started from version 0 can no longer write
    assert store.cas_connector_checkpoint(stale, expected_version=0) is False
    assert store.get_connector_checkpoint(inst.id, "issues").cursor["seq"] == 2


# -- stream leases (fenced) --------------------------------------------------------


def test_stream_lease_mutual_exclusion(store, creds):
    _acc, inst = _make(store, creds)
    token_a = store.acquire_stream_lease(inst.id, "issues", "worker_a")
    assert token_a is not None
    assert store.acquire_stream_lease(inst.id, "issues", "worker_b") is None
    # re-entrant acquire keeps the SAME fencing token
    assert store.acquire_stream_lease(inst.id, "issues", "worker_a") == token_a
    store.release_stream_lease(inst.id, "issues", "worker_a")
    token_b = store.acquire_stream_lease(inst.id, "issues", "worker_b")
    assert token_b is not None and token_b > token_a  # monotonic on ownership change


def test_expired_lease_is_taken_over(store, creds):
    _acc, inst = _make(store, creds)
    assert store.acquire_stream_lease(inst.id, "issues", "worker_dead",
                                      ttl_seconds=0) is not None
    # ttl 0 → immediately expired → another worker may take over
    assert store.acquire_stream_lease(inst.id, "issues", "worker_b") is not None


def test_lease_renewal_and_fencing(store, creds):
    """A worker whose lease was taken over holds a stale fencing token and
    can no longer renew — it lost the authority to publish."""
    _acc, inst = _make(store, creds)
    token_a = store.acquire_stream_lease(inst.id, "issues", "worker_a",
                                         ttl_seconds=600)
    # the owner renews freely under its token
    assert store.renew_stream_lease(inst.id, "issues", "worker_a", token_a)
    # simulate expiry, then a takeover by B
    store.release_stream_lease(inst.id, "issues", "worker_a")
    token_b = store.acquire_stream_lease(inst.id, "issues", "worker_b")
    assert token_b > token_a
    # A's token is fenced out; B's works
    assert store.renew_stream_lease(inst.id, "issues", "worker_a", token_a) is False
    assert store.renew_stream_lease(inst.id, "issues", "worker_b", token_b) is True


def test_worker_that_lost_lease_cannot_publish(store, creds, monkeypatch):
    """Mid-sync lease loss (slow provider outliving the TTL): the batch is
    aborted, nothing cognitive persists and the checkpoint is untouched —
    then the rightful owner syncs normally."""
    _acc, inst = _make(store, creds)
    monkeypatch.setattr(store, "renew_stream_lease",
                        lambda *a, **kw: False)
    result = sync_connector(store, creds, inst.id)
    assert all(not s.committed for s in result.streams)
    assert store.list_percepts() == []
    assert store.get_connector_checkpoint(inst.id, "issues") is None
    statuses = {b.status.value for b in store.list_connector_batches(inst.id)}
    assert statuses == {"aborted"}

    monkeypatch.undo()
    healthy = sync_connector(store, creds, inst.id)
    assert healthy.percepts == 3
    assert store.get_connector_checkpoint(inst.id, "issues") is not None


def test_long_multi_page_sync_renews_lease(store, creds):
    """Every fetched page renews the lease, so a sync longer than the TTL
    keeps its authority instead of silently losing it."""
    _acc, inst = _make(store, creds, configuration={"page_size": 1})
    renewals = []
    original = store.renew_stream_lease

    def counting(connector_id, stream, owner, token, **kw):
        ok = original(connector_id, stream, owner, token, **kw)
        renewals.append((stream, ok))
        return ok

    store.renew_stream_lease = counting
    try:
        result = sync_connector(store, creds, inst.id)
    finally:
        store.renew_stream_lease = original
    assert result.percepts == 3
    # issues has 2 items → 2 pages → ≥2 renewals + 1 fence at finalize
    issues_renewals = [ok for stream, ok in renewals if stream == "issues"]
    assert len(issues_renewals) >= 3
    assert all(issues_renewals)


def test_leased_stream_is_skipped_not_duplicated(store, creds):
    _acc, inst = _make(store, creds)
    assert store.acquire_stream_lease(inst.id, "issues", "other_process") is not None
    result = sync_connector(store, creds, inst.id)
    issues = next(s for s in result.streams if s.stream == "issues")
    assert issues.skipped == "already_running"
    assert issues.committed is False
    # the un-leased stream still synced normally
    prs = next(s for s in result.streams if s.stream == "pull_requests")
    assert prs.committed is True
    assert store.get_connector_checkpoint(inst.id, "issues") is None


def test_concurrent_syncs_produce_single_checkpoint(store, creds):
    _acc, inst = _make(store, creds)
    results = []
    barrier = threading.Barrier(2)

    def run():
        barrier.wait()
        results.append(sync_connector(store, creds, inst.id))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # regardless of interleaving: exactly 3 percepts, one checkpoint at v1+
    assert len(store.list_percepts()) == 3
    assert len(store.list_connector_records(inst.id)) == 3
    ckpt = store.get_connector_checkpoint(inst.id, "issues")
    assert ckpt is not None and ckpt.cursor.get("seq") == 2


# -- revision immutability -------------------------------------------------------


def test_edit_creates_new_revision_old_retained(store, creds):
    fx = {"issues": [{"external_id": "1", "external_revision": "1", "seq": 1,
                      "content": "v1 original"}], "pull_requests": []}
    _acc, inst = _make(store, creds, configuration={"fixtures": fx})
    sync_connector(store, creds, inst.id)

    fx2 = {"issues": [{"external_id": "1", "external_revision": "2", "seq": 2,
                       "content": "v2 edited"}], "pull_requests": []}
    store.update_connector_instance(inst.id, configuration={"fixtures": fx2})
    sync_connector(store, creds, inst.id)

    records = store.list_connector_records(inst.id)
    revisions = sorted(r.external_revision for r in records)
    assert revisions == ["1", "2"]  # old revision retained alongside the edit


def test_same_revision_different_content_is_a_collision(store, creds):
    """The provider re-served revision 1 with other content: dead letter,
    never an overwrite — stored evidence is immutable."""
    fx = {"issues": [{"external_id": "1", "external_revision": "1", "seq": 1,
                      "content": "original evidence"}], "pull_requests": []}
    _acc, inst = _make(store, creds, configuration={"fixtures": fx})
    sync_connector(store, creds, inst.id)

    fx2 = {"issues": [{"external_id": "1", "external_revision": "1", "seq": 2,
                       "content": "SILENTLY DIFFERENT"}], "pull_requests": []}
    store.update_connector_instance(inst.id, configuration={"fixtures": fx2})
    result = sync_connector(store, creds, inst.id)

    issues = next(s for s in result.streams if s.stream == "issues")
    assert issues.committed is False
    dead = store.list_connector_dead_letters(inst.id)
    assert any(d.failure_class.value == "revision_collision" for d in dead)
    # raw evidence and record content both preserved
    raw = store.find_raw_item_by_key(
        f"fake:{_acc.id}:issue:1:1")
    assert raw.payload["content"] == "original evidence"
    [record] = [r for r in store.list_connector_records(inst.id)
                if r.external_type == "issue"]
    assert record.content == "original evidence"
    # the percept derived from the original was not replaced
    [percept] = store.list_percepts()
    assert "original evidence" in percept.content


def test_duplicate_item_in_same_page_is_deduplicated(store, creds):
    """A batch must be idempotent within itself: the provider sending the
    same revision twice in one page yields one raw item, one record, one
    percept — and a committed batch, not a unique-constraint explosion."""
    fx = {"issues": [
        {"external_id": "1", "external_revision": "1", "seq": 1,
         "content": "same thing"},
        {"external_id": "1", "external_revision": "1", "seq": 1,
         "content": "same thing"},
    ], "pull_requests": []}
    _acc, inst = _make(store, creds, configuration={"fixtures": fx})
    result = sync_connector(store, creds, inst.id)
    issues = next(s for s in result.streams if s.stream == "issues")
    assert issues.committed is True
    assert issues.deduplicated >= 1
    assert len([r for r in store.list_connector_records(inst.id)
                if r.external_type == "issue"]) == 1
    assert len(store.list_percepts()) == 1


def test_duplicate_item_across_pages_is_deduplicated(store, creds):
    fx = {"issues": [
        {"external_id": "1", "external_revision": "1", "seq": 1,
         "content": "same thing"},
        {"external_id": "1", "external_revision": "1", "seq": 1,
         "content": "same thing"},
        {"external_id": "2", "external_revision": "1", "seq": 2,
         "content": "another"},
    ], "pull_requests": []}
    _acc, inst = _make(store, creds,
                       configuration={"fixtures": fx, "page_size": 1})
    result = sync_connector(store, creds, inst.id)
    issues = next(s for s in result.streams if s.stream == "issues")
    assert issues.committed is True
    assert len([r for r in store.list_connector_records(inst.id)
                if r.external_type == "issue"]) == 2
    assert len(store.list_percepts()) == 2


def test_same_key_different_hash_within_one_batch_is_collision(store, creds):
    fx = {"issues": [
        {"external_id": "1", "external_revision": "1", "seq": 1,
         "content": "version A"},
        {"external_id": "1", "external_revision": "1", "seq": 1,
         "content": "version B — same revision, different payload"},
    ], "pull_requests": []}
    _acc, inst = _make(store, creds, configuration={"fixtures": fx})
    result = sync_connector(store, creds, inst.id)
    issues = next(s for s in result.streams if s.stream == "issues")
    assert issues.committed is False
    dead = store.list_connector_dead_letters(inst.id)
    assert any(d.failure_class.value == "revision_collision" for d in dead)
    # nothing cognitive from the conflicted batch
    assert not [r for r in store.list_connector_records(inst.id)
                if r.external_type == "issue"]
    assert store.list_percepts() == []


def test_tombstone_in_same_batch_resolves_staged_revision(store, creds):
    """Create + delete arriving in ONE batch (replay/lookback/aggregated
    providers): the deletion event still links the staged prior revision and
    its percept — staged records are not invisible to lineage."""
    fx = {"issues": [
        {"external_id": "1", "external_revision": "1", "seq": 1,
         "content": "created and deleted in the same batch"},
        {"external_id": "1", "external_revision": "2", "seq": 2,
         "content": "", "deleted": True},
    ], "pull_requests": []}
    _acc, inst = _make(store, creds, configuration={"fixtures": fx})
    result = sync_connector(store, creds, inst.id)
    issues = next(s for s in result.streams if s.stream == "issues")
    assert issues.committed is True
    [event] = store.list_connector_deletion_events(inst.id)
    prior = [r for r in store.list_connector_records(inst.id)
             if r.external_type == "issue" and not r.deleted]
    assert len(prior) == 1
    assert event.prior_record_ids == [prior[0].id]
    assert event.affected_percept_ids == [prior[0].percept_id]
    assert prior[0].percept_id  # revision 1 did produce its percept


def test_records_are_immutable_no_update_api(store, creds):
    """There is deliberately no store method that rewrites a record payload;
    processing state travels in columns only."""
    _acc, inst = _make(store, creds)
    sync_connector(store, creds, inst.id)
    assert not hasattr(store, "update_connector_record")
    rec = store.list_connector_records(inst.id)[0]
    original_content = rec.content
    store.set_connector_record_state(rec.id, percept_id="pct_other")
    reloaded = store.get_connector_record(rec.id)
    assert reloaded.percept_id == "pct_other"
    assert reloaded.content == original_content  # payload untouched


# -- deletions -------------------------------------------------------------------


def test_delete_creates_tombstone_and_no_percept(store, creds):
    fx = {"issues": [{"external_id": "1", "external_revision": "9", "seq": 9,
                      "content": "removed upstream", "deleted": True}],
          "pull_requests": []}
    _acc, inst = _make(store, creds, configuration={"fixtures": fx})
    result = sync_connector(store, creds, inst.id)
    assert result.percepts == 0
    records = store.list_connector_records(inst.id)
    assert records and all(r.deleted for r in records)
    assert store.list_percepts() == []


def test_tombstone_builds_lineage_impact_event(store, creds):
    """A deletion locates every prior revision and its Percepts, and files a
    deletion event for the planner — the memory layer is never touched
    directly, and corroborated evidence is not silently dropped."""
    fx = {"issues": [{"external_id": "1", "external_revision": "1", "seq": 1,
                      "content": "will be deleted"}], "pull_requests": []}
    _acc, inst = _make(store, creds, configuration={"fixtures": fx})
    sync_connector(store, creds, inst.id)
    [prior] = [r for r in store.list_connector_records(inst.id)
               if r.external_type == "issue"]
    assert prior.percept_id

    fx2 = {"issues": [{"external_id": "1", "external_revision": "2", "seq": 2,
                       "content": "", "deleted": True}], "pull_requests": []}
    store.update_connector_instance(inst.id, configuration={"fixtures": fx2})
    sync_connector(store, creds, inst.id)

    [event] = store.list_connector_deletion_events(inst.id)
    assert event.external_id == "1"
    assert event.status.value == "pending"      # awaiting the deletion planner
    assert event.prior_record_ids == [prior.id]
    assert event.affected_percept_ids == [prior.percept_id]
    # the tombstone itself created no percept and removed none
    assert len(store.list_percepts()) == 1


# -- auth / rate limit / quarantine ----------------------------------------------


def test_auth_expiry_reports_unauthorized_and_no_checkpoint(store, creds):
    _acc, inst = _make(store, creds, configuration={"fail_mode": "auth_expired"})
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "unauthorized"
    assert store.get_connector_checkpoint(inst.id, "issues") is None
    assert connector_health(store, inst.id)["health"] == "unauthorized"


def test_rate_limit_degrades_and_keeps_checkpoint(store, creds):
    _acc, inst = _make(store, creds, configuration={"fail_mode": "rate_limit"})
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "degraded"
    assert store.get_connector_checkpoint(inst.id, "issues") is None
    assert store.list_percepts() == []


def test_malicious_content_quarantined_never_extracted(store, creds, cfg, embedder):
    fx = {"issues": [{"external_id": "1", "external_revision": "1", "seq": 1,
                      "content": _MALICIOUS}], "pull_requests": []}
    _acc, inst = _make(store, creds, configuration={"fixtures": fx})
    result = sync_connector(store, creds, inst.id)

    assert result.percepts == 0
    records = [r for r in store.list_connector_records(inst.id)
               if r.external_type == "issue"]
    assert records and records[0].quarantined is True
    assert store.list_percepts() == []
    assert store.list_quarantine(status="quarantined")

    # extraction has nothing to chew on → no memories
    from twin.cognition import extract_pending
    extract_pending(store, cfg, embedder)
    assert store.list_memories() == []


# -- ownership / vaults ----------------------------------------------------------


def test_employer_account_rejected_for_personal_vault(store, creds):
    with pytest.raises(ValueError):
        validate_account_vault("employer", "vault_personal")
    with pytest.raises(ValueError):
        register_source_account(
            store, connector_type="fake", source_owner="employer",
            vault_id="vault_personal", org_key="acme",
            owner_principal_id=PRINCIPAL,
        )


def test_ownership_enum_rejects_typos():
    from twin.connectors.models import SourceAccount

    with pytest.raises(Exception):
        SourceAccount(connector_type="fake", owner_principal_id=PRINCIPAL,
                      source_owner="employeer")
    with pytest.raises(Exception):
        SourceAccount(connector_type="fake", owner_principal_id=PRINCIPAL,
                      source_trust=1.7)


def test_org_vault_isolated_and_declared(store, creds):
    _acc, inst = _make(store, creds, source_owner="employer", org_key="Globex Inc")
    vault = store.get_vault("vault_work_globex_inc")
    assert vault is not None
    assert vault.source_owner == "employer"
    assert vault.storage_backend == "shared_db"
    assert vault.backup_class == "employer"


def test_reclassification_is_preview_first_state_aware_and_audited(store, creds):
    acc, _inst = _make(store, creds, source_owner="personal")
    preview = reclassify_source_account(
        store, acc.id, actor_principal_id=PRINCIPAL,
        source_owner="employer", org_key="acme",
    )
    assert preview["applied"] is False
    assert preview["proposed"]["vault_id"] == "vault_work_acme"
    token = preview["confirm_token"]
    # nothing changed yet
    assert store.get_source_account(acc.id).source_owner.value == "personal"

    # apply without (or with a wrong) token is refused
    with pytest.raises(ValueError, match="confirm_token"):
        reclassify_source_account(
            store, acc.id, actor_principal_id=PRINCIPAL,
            source_owner="employer", org_key="acme", apply=True,
        )
    with pytest.raises(ValueError, match="confirm_token"):
        reclassify_source_account(
            store, acc.id, actor_principal_id=PRINCIPAL,
            source_owner="employer", org_key="acme", apply=True,
            confirm_token="bogus",
        )

    applied = reclassify_source_account(
        store, acc.id, actor_principal_id=PRINCIPAL,
        source_owner="employer", org_key="acme", apply=True,
        confirm_token=token,
    )
    assert applied["applied"] is True
    reloaded = store.get_source_account(acc.id)
    assert reloaded.source_owner.value == "employer"
    assert reloaded.vault_id == "vault_work_acme"
    audit = reloaded.metadata["reclassifications"]
    assert audit and audit[0]["actor"] == PRINCIPAL

    # the OLD token no longer matches the account's new state — state drift
    # between preview and apply always forces a fresh preview
    with pytest.raises(ValueError, match="confirm_token"):
        reclassify_source_account(
            store, acc.id, actor_principal_id=PRINCIPAL,
            source_owner="employer", org_key="acme", apply=True,
            confirm_token=token,
        )

    # client ownership needs a *client* identifier — a fresh account without
    # any org_key cannot be reclassified blindly
    fresh = register_source_account(
        store, connector_type="fake", source_owner="personal",
        owner_principal_id=PRINCIPAL,
    )
    with pytest.raises(ValueError, match="org_key"):
        reclassify_source_account(store, fresh.id, actor_principal_id=PRINCIPAL,
                                  source_owner="client")


# -- credentials -----------------------------------------------------------------


def test_credentials_absent_from_store_payloads(store, creds):
    secret = "super-secret-token-42"
    _acc, inst = _make(store, creds, secret=secret)
    sync_connector(store, creds, inst.id)

    inst_row = store._j_fetchone(
        "SELECT payload FROM connector_instances WHERE id = ?", (inst.id,)
    )
    assert secret not in inst_row["payload"]
    cred_rows = store._j_fetchall("SELECT payload FROM connector_credential_refs", ())
    for r in cred_rows:
        assert secret not in r["payload"]
    assert creds.get(inst.credential_ref) == secret


def test_credentials_fail_closed_without_crypto_backend(tmp_path, monkeypatch):
    """No cryptography → no credential store → connector cannot be
    configured. There is no reversible-obfuscation fallback."""
    monkeypatch.setitem(sys.modules, "cryptography", None)
    monkeypatch.setitem(sys.modules, "cryptography.fernet", None)
    with pytest.raises(CredentialBackendUnavailable):
        build_credential_store(tmp_path / "no-crypto-home")


def test_credential_writes_are_concurrent_safe(creds):
    errors: list[Exception] = []

    def put_many(prefix):
        try:
            for i in range(10):
                creds.put(f"{prefix}_{i}", f"secret-{prefix}-{i}")
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=put_many, args=(p,)) for p in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    for p in ("a", "b"):
        for i in range(10):
            assert creds.get(f"{p}_{i}") == f"secret-{p}-{i}"


def test_corrupted_main_never_overwrites_valid_backup(creds):
    """Recovery must not destroy the last known-good state: a corrupted main
    file is NEVER copied over the healthy backup, and a save after recovery
    keeps every previously stored credential."""
    creds.put("cred_a", "secret-a")
    creds.put("cred_b", "secret-b")           # backup now holds {a}
    creds.put("cred_c", "secret-c")           # backup now holds {a,b}
    creds._path.write_text("{ this is not json", encoding="utf-8")

    # reads fall back to the backup
    assert creds.get("cred_a") == "secret-a"
    assert creds.get("cred_b") == "secret-b"

    # a write during recovery must not copy the corrupted main over the
    # backup — and must preserve everything the backup knew
    creds.put("cred_d", "secret-d")
    for ref, secret in (("cred_a", "secret-a"), ("cred_b", "secret-b"),
                        ("cred_d", "secret-d")):
        assert creds.get(ref) == secret
    # the rewritten main file is valid again
    assert creds._try_read(creds._path) is not None


def test_invalid_ciphertext_is_treated_as_corruption(creds):
    """Corruption detection covers the ciphertext, not only the JSON: valid
    JSON with undecryptable tokens must not be trusted."""
    creds.put("cred_a", "secret-a")
    creds.put("cred_b", "secret-b")           # backup holds {a}
    import json as _json
    creds._path.write_text(_json.dumps({"cred_a": "bm90LWEtZmVybmV0LXRva2Vu"}),
                           encoding="utf-8")
    assert creds.get("cred_a") == "secret-a"  # backup wins over bogus tokens


def test_both_files_corrupted_fails_closed(creds):
    """Existing-but-unreadable credential files must raise — silently
    reinitializing an empty map would erase every secret on the next put."""
    from twin.connectors import CredentialStoreCorrupted

    creds.put("cred_a", "secret-a")
    creds.put("cred_b", "secret-b")
    creds._path.write_text("garbage", encoding="utf-8")
    creds._bak.write_text("also garbage", encoding="utf-8")
    with pytest.raises(CredentialStoreCorrupted):
        creds.get("cred_a")
    with pytest.raises(CredentialStoreCorrupted):
        creds.put("cred_new", "secret-new")
    # nothing was overwritten by the refused put
    assert creds._path.read_text(encoding="utf-8") == "garbage"


def test_empty_map_only_when_no_files_existed(tmp_path):
    fresh = build_credential_store(tmp_path / "fresh-home")
    assert fresh.get("anything") is None      # empty state is fine when new
    fresh.put("cred_a", "secret-a")
    assert fresh.get("cred_a") == "secret-a"


def _mp_put_many(home: str, prefix: str) -> None:
    """Top-level so multiprocessing can pickle it."""
    from twin.connectors import build_credential_store

    cred_store = build_credential_store(Path(home))
    for i in range(8):
        cred_store.put(f"{prefix}_{i}", f"secret-{prefix}-{i}")


def test_credential_writes_survive_concurrent_processes(tmp_path):
    """Two PROCESSES (not threads) writing concurrently: the cross-platform
    file lock + per-PID temp files mean no lost updates and no temp-file
    interference."""
    import multiprocessing

    home = tmp_path / "mp-home"
    parent = build_credential_store(home)   # creates the key first
    parent.put("seed", "seed-secret")

    ctx = multiprocessing.get_context("fork" if hasattr(os, "fork") else "spawn")
    procs = [ctx.Process(target=_mp_put_many, args=(str(home), p))
             for p in ("pa", "pb")]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0
    assert parent.get("seed") == "seed-secret"
    for prefix in ("pa", "pb"):
        for i in range(8):
            assert parent.get(f"{prefix}_{i}") == f"secret-{prefix}-{i}"
    # no leftover temp files from either writer
    assert not list((home / "secrets").glob("*.tmp"))


def test_lock_routes_to_msvcrt_when_fcntl_missing(tmp_path, monkeypatch):
    """Windows path: without fcntl the lock must go through msvcrt.locking —
    never silently continue lockless."""
    import types

    calls = []
    fake_msvcrt = types.SimpleNamespace(
        LK_LOCK=0, LK_UNLCK=1,
        locking=lambda fd, mode, n: calls.append(mode),
    )
    monkeypatch.setitem(sys.modules, "fcntl", None)   # import fcntl → ImportError
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    win_creds = build_credential_store(tmp_path / "win-home")
    win_creds.put("cred_w", "secret-w")
    assert win_creds.get("cred_w") == "secret-w"
    assert fake_msvcrt.LK_LOCK in calls               # lock actually taken
    assert fake_msvcrt.LK_UNLCK in calls              # and released


def test_no_locking_backend_fails_closed(tmp_path, monkeypatch):
    from twin.connectors import CredentialBackendUnavailable

    no_lock = build_credential_store(tmp_path / "nolock-home")
    monkeypatch.setitem(sys.modules, "fcntl", None)
    monkeypatch.setitem(sys.modules, "msvcrt", None)
    with pytest.raises(CredentialBackendUnavailable):
        no_lock.put("cred_x", "secret-x")


def test_provisioning_failure_compensates(store, creds, monkeypatch):
    acc = register_source_account(
        store, connector_type="fake", source_owner="personal",
        owner_principal_id=PRINCIPAL,
    )

    def broken_put(ref, secret):
        raise OSError("disk full")

    monkeypatch.setattr(creds, "put", broken_put)
    with pytest.raises(OSError):
        add_connector_instance(store, creds, account_id=acc.id, secret="tok-x")

    [inst] = store.list_connector_instances()
    assert inst.status.value == "provisioning_failed"
    assert inst.credential_ref is None
    # no orphan credential refs, no usable connector
    assert store._j_fetchall("SELECT * FROM connector_credential_refs", ()) == []
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "unauthorized"
    assert store.list_percepts() == []


def test_revocation_is_resumable_never_claims_clean(store, creds, monkeypatch):
    _acc, inst = _make(store, creds, secret="tok-to-destroy")
    ref = inst.credential_ref

    def broken_delete(credential_ref):
        raise OSError("keyring offline")

    monkeypatch.setattr(creds, "delete", broken_delete)
    updated = revoke_connector(store, creds, inst.id)
    assert updated.status.value == "revoked_with_residual_secret"
    assert updated.credential_ref == ref       # kept so retry can clean up
    assert creds.get(ref) == "tok-to-destroy"  # residual honestly reported
    # sync is stopped regardless
    assert sync_connector(store, creds, inst.id).health.value == "revoked"

    monkeypatch.undo()
    retried = revoke_connector(store, creds, inst.id)
    assert retried.status.value == "revoked"
    assert retried.credential_ref is None
    assert creds.get(ref) is None


def test_revoke_removes_secret_and_stops_sync(store, creds):
    _acc, inst = _make(store, creds, secret="tok-to-destroy")
    ref = inst.credential_ref
    assert creds.get(ref) == "tok-to-destroy"

    revoke_connector(store, creds, inst.id)
    assert creds.get(ref) is None
    reloaded = store.get_connector_instance(inst.id)
    assert reloaded.status.value == "revoked"
    assert reloaded.credential_ref is None

    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "revoked"
    assert store.list_percepts() == []


def test_external_provider_without_secret_awaits_auth(store, creds):
    """Only generated_local_token adapters may receive a generated secret;
    an external provider without a credential is awaiting_auth — never
    active with a random token."""
    from twin.connectors.protocol import AdapterManifest, ConnectorHealth
    from twin.connectors.models import HealthStatus
    from twin.connectors.registry import register_adapter

    @register_adapter
    class _ExternalProvider:
        connector_type = "extprov"

        def __init__(self, instance, account, secret):
            self.secret = secret

        @staticmethod
        def adapter_manifest():
            return AdapterManifest(connector_type="extprov",
                                   auth_mode="personal_access_token",
                                   streams=["default"])

        def validate_credentials(self):
            return ConnectorHealth(status=(
                HealthStatus.healthy if self.secret else HealthStatus.unauthorized))

    acc = register_source_account(
        store, connector_type="extprov", source_owner="personal",
        owner_principal_id=PRINCIPAL,
    )
    inst = add_connector_instance(store, creds, account_id=acc.id, secret=None)
    assert inst.status.value == "awaiting_auth"
    assert inst.credential_ref is None
    assert sync_connector(store, creds, inst.id).health.value == "unauthorized"

    # fake (generated_local_token) still self-provisions
    _acc2, inst2 = _make(store, creds, secret=None)
    assert inst2.status.value == "active"
    assert inst2.credential_ref is not None


# -- dead letters ----------------------------------------------------------------


def test_dead_letter_retry_reprocesses_from_raw(store, creds):
    _acc, inst = _make(store, creds, configuration={"normalize_fail_ids": ["1"]})
    sync_connector(store, creds, inst.id)
    [dlq] = store.list_connector_dead_letters(inst.id)
    assert dlq.status.value == "open"
    assert dlq.raw_item_id

    # heal the adapter, then replay just the dead letter
    store.update_connector_instance(inst.id, configuration={})
    resolved = retry_dead_letter(store, creds, dlq.id)
    assert resolved.status.value == "resolved"
    assert resolved.attempts == 2
    recs = [r for r in store.list_connector_records(inst.id)
            if r.external_id == "1" and r.external_type == "issue"]
    assert len(recs) == 1 and recs[0].percept_id
    # the stream can subsequently advance
    result = sync_connector(store, creds, inst.id)
    issues = next(s for s in result.streams if s.stream == "issues")
    assert issues.committed is True


def test_dead_letter_retry_failure_stays_open_with_sanitized_error(store, creds):
    _acc, inst = _make(store, creds, configuration={"normalize_fail_ids": ["1"]})
    sync_connector(store, creds, inst.id)
    [dlq] = store.list_connector_dead_letters(inst.id)
    again = retry_dead_letter(store, creds, dlq.id)  # adapter still failing
    assert again.status.value == "open"
    assert again.attempts == 2


def test_persisted_errors_are_sanitized(store, creds):
    """Adapter errors carrying URLs/tokens/emails never land verbatim."""
    leaky = ("fetch of https://api.acme.com/v1/mail?user=edu@acme.com failed: "
             "Authorization: Bearer ghp_SECRETSECRETSECRETSECRET123456")
    _acc, inst = _make(store, creds, configuration={
        "normalize_fail_ids": ["1"], "fail_message": leaky,
    })
    # FakeConnector raises with its default message; test the sanitizer
    # directly against the leaky string plus the persisted DLQ shape.
    safe = sanitize_error(RuntimeError(leaky))
    assert "ghp_SECRET" not in safe
    assert "edu@acme.com" not in safe
    assert "https://" not in safe
    assert "Bearer" not in safe or "[redacted]" in safe

    sync_connector(store, creds, inst.id)
    for d in store.list_connector_dead_letters(inst.id):
        assert "tok-secret-value" not in d.last_error


# -- framework guarantees ---------------------------------------------------------


def test_no_confirmed_memory_or_judgment_written(store, creds):
    _acc, inst = _make(store, creds, source_owner="employer", org_key="acme")
    sync_connector(store, creds, inst.id)
    assert store.list_memories(status="confirmed") == []
    assert store.list_memories() == []
    if hasattr(store, "list_judgment_items"):
        assert store.list_judgment_items() == []


def test_manifest_and_adapter_registration():
    from twin.connectors import get_manifest, list_adapters
    assert "fake" in list_adapters()
    manifest = get_manifest("fake")
    assert manifest.connector_type == "fake"
    assert "issues" in manifest.streams
    assert manifest.affordances["deletions"] is True
    assert manifest.auth_mode == "generated_local_token"


# -- scheduler -------------------------------------------------------------------


def test_scheduler_rejects_invalid_config(tmp_path):
    from twin.connectors.scheduler import ScheduleConfigError, load_schedule

    (tmp_path / "connectors.yaml").write_text("intervals: [not, a, mapping]")
    with pytest.raises(ScheduleConfigError):
        load_schedule(tmp_path)
    (tmp_path / "connectors.yaml").write_text("intervals:\n  fake: 0\n")
    with pytest.raises(ScheduleConfigError):
        load_schedule(tmp_path)
    (tmp_path / "connectors.yaml").write_text("intervals:\n  fake: 30\n")
    assert load_schedule(tmp_path)["fake"] == 30


def test_scheduler_isolates_failing_connector(store, creds, tmp_path, monkeypatch):
    """One broken connector never blocks the others; its failure lands on
    its own sync state with backoff."""
    from twin.connectors import scheduler as sched

    _acc1, healthy = _make(store, creds)
    _acc2, broken = _make(store, creds)

    real_sync = sched.sync_connector
    def selective(store_, creds_, connector_id, **kw):
        if connector_id == broken.id:
            raise RuntimeError("adapter blew up")
        return real_sync(store_, creds_, connector_id, **kw)

    monkeypatch.setattr(sched, "sync_connector", selective)
    results = sched.sync_due(store, creds, tmp_path)
    assert len(results) == 1                      # healthy one ran
    assert results[0].connector_id == healthy.id
    state = store.get_connector_sync_state(broken.id)
    assert state.status.value == "failed"
    assert state.backoff_seconds >= 60
    assert state.next_run_at is not None          # still rescheduled
    healthy_state = store.get_connector_sync_state(healthy.id)
    assert healthy_state.next_run_at is not None
