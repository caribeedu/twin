"""v0.6 Phase 5 — Fireflies GraphQL connector against the offline double."""

from __future__ import annotations

import httpx
import pytest

from twin.connectors import (
    add_connector_instance,
    build_credential_store,
    register_source_account,
    sync_connector,
)
from twin.connectors.meeting.correlate import correlation_fingerprint
from twin.connectors.meeting.speakers import ACTOR_PROMOTE_THRESHOLD

from fireflies_mock import FakeFirefliesAPI

TOKEN = "ff-test-token"


@pytest.fixture()
def creds(tmp_path):
    return build_credential_store(tmp_path / "creds-home")


@pytest.fixture()
def fireflies(monkeypatch):
    api = FakeFirefliesAPI()
    from twin.connectors.fireflies import client as fclient
    real_build = fclient._build_http

    def fake_build(base_url, token):
        original = real_build(base_url, token)
        headers = dict(original.headers)
        original.close()
        return httpx.Client(
            transport=api.transport(),
            base_url="https://api.fireflies.ai/graphql",
            headers=headers,
        )

    monkeypatch.setattr(fclient, "_build_http", fake_build)
    return api


def _mk(store, creds, *, secret=TOKEN, extra=None):
    acc = register_source_account(
        store, connector_type="fireflies", source_owner="employer", org_key="acme",
        owner_principal_id="principal_test",
        external_account_id="edu@acme.com",
    )
    inst = add_connector_instance(
        store, creds, account_id=acc.id, secret=secret,
        configuration=dict(extra or {}),
    )
    return acc, inst


def test_sync_uses_graphql_and_chunks(store, creds, fireflies):
    fireflies.add_transcript("mtg_1")
    _acc, inst = _mk(store, creds)
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "healthy"
    assert any("query" in (r.get("query") or "").lower()
               for r in fireflies.requests)
    by_type: dict[str, list] = {}
    for r in store.list_connector_records(inst.id):
        by_type.setdefault(r.external_type, []).append(r)
    assert "meeting_manifest" in by_type
    assert "meeting_transcript_chunk" in by_type
    assert "meeting_summary" in by_type
    tr = by_type["meeting_transcript_chunk"][0]
    sm = by_type["meeting_summary"][0]
    assert tr.thread_key == sm.thread_key
    assert tr.confidentiality["source_trust"] == 0.75
    assert sm.confidentiality["source_trust"] == 0.45
    assert sm.source_metadata["derived"] == "provider_summary"
    fp = correlation_fingerprint(
        title="Architecture sync", started_at="2026-07-15T15:00:00Z",
    )
    assert tr.source_metadata["correlation_fingerprint"] == fp
    # Signed media URL must not be the recording artifact identity.
    rec_arts = [a for a in tr.artifact_refs if a.get("kind") == "recording"]
    assert rec_arts
    assert "http" not in rec_arts[0]["external_id"]
    assert "sig=" not in rec_arts[0]["external_id"]


def test_graphql_errors_array_degrades(store, creds, fireflies):
    fireflies.add_transcript("mtg_1")
    fireflies.graphql_errors = [{
        "message": "auth_failed",
        "extensions": {"code": "auth_failed"},
    }]
    _acc, inst = _mk(store, creds)
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "unauthorized"


def test_processing_transcript_not_final(store, creds, fireflies):
    fireflies.add_transcript(
        "mtg_proc",
        sentences=[],
        summary_status="processing",
        summary=None,
    )
    _acc, inst = _mk(store, creds)
    sync_connector(store, creds, inst.id)
    types = {r.external_type for r in store.list_connector_records(inst.id)}
    assert "meeting_manifest" in types
    assert "meeting_transcript_chunk" not in types
    assert "meeting_summary" not in types
    man = next(r for r in store.list_connector_records(inst.id)
               if r.external_type == "meeting_manifest")
    assert man.source_metadata["transcript_complete"] is False
    assert man.source_metadata["provider_status"] == "processing"


def test_speaker_mapping_keeps_confidence(store, creds, fireflies):
    fireflies.add_transcript(
        "mtg_spk",
        sentences=[
            {"index": 0, "speaker_name": "Speaker 1", "text": "Hello"},
            {"index": 1, "speaker_name": "Alice", "speaker_id": "sp_a",
             "text": "Hi"},
        ],
        speakers=[{"name": "Alice", "id": "sp_a"}],
        participants=["alice@acme.com"],
        meeting_attendees=[{"name": "Alice", "email": "alice@acme.com"}],
    )
    # Inject email onto speaker via attendees name match + provider id
    fireflies.transcripts["mtg_spk"]["speakers"] = [
        {"name": "Alice", "id": "sp_a", "email": "alice@acme.com"},
    ]
    _acc, inst = _mk(store, creds)
    sync_connector(store, creds, inst.id)
    tr = next(r for r in store.list_connector_records(inst.id)
              if r.external_type == "meeting_transcript_chunk")
    speakers = tr.source_metadata["speakers"]
    by_label = {s["label"]: s for s in speakers}
    assert by_label["Alice"]["confidence"] >= ACTOR_PROMOTE_THRESHOLD
    assert by_label["Speaker 1"]["confidence"] < ACTOR_PROMOTE_THRESHOLD
    assert "Speaker 1" in tr.source_metadata["unresolved_speakers"]
    # Silent participant Bob must not appear as actor.
    assert all("bob@" not in a for a in tr.actor_ids)
    # Alice email actor; Speaker 1 must not be a global name id.
    assert "mail:alice@acme.com" in tr.actor_ids
    assert not any(a.endswith(":name:speaker-1") for a in tr.actor_ids)


def test_silent_attendee_not_actor(store, creds, fireflies):
    fireflies.add_transcript(
        "mtg_silent",
        sentences=[
            {"index": 0, "speaker_name": "Alice", "speaker_id": "sp_a",
             "text": "Only I spoke."},
        ],
        speakers=[{"name": "Alice", "id": "sp_a", "email": "alice@acme.com"}],
        participants=["alice@acme.com", "bob@acme.com"],
        meeting_attendees=[
            {"name": "Alice", "email": "alice@acme.com"},
            {"name": "Bob", "email": "bob@acme.com"},
        ],
    )
    _acc, inst = _mk(store, creds)
    sync_connector(store, creds, inst.id)
    tr = next(r for r in store.list_connector_records(inst.id)
              if r.external_type == "meeting_transcript_chunk")
    assert "mail:alice@acme.com" in tr.actor_ids
    assert "mail:bob@acme.com" not in tr.actor_ids
    assert "mail:bob@acme.com" in tr.participant_ids


def test_idempotent_resync(store, creds, fireflies):
    fireflies.add_transcript("mtg_1")
    _acc, inst = _mk(store, creds)
    first = sync_connector(store, creds, inst.id)
    again = sync_connector(store, creds, inst.id)
    assert first.percepts >= 3
    assert again.percepts == 0


def test_content_change_new_revision(store, creds, fireflies):
    fireflies.add_transcript("mtg_rev")
    _acc, inst = _mk(store, creds)
    sync_connector(store, creds, inst.id)
    before = {
        r.external_id: r.external_revision
        for r in store.list_connector_records(inst.id)
        if r.external_type == "meeting_transcript_chunk"
    }
    # Mutate one sentence — revision must change.
    fireflies.transcripts["mtg_rev"]["sentences"][2]["text"] = (
        "Agreed. Decision: MySQL instead."
    )
    sync_connector(store, creds, inst.id)
    after = [
        r for r in store.list_connector_records(inst.id)
        if r.external_type == "meeting_transcript_chunk"
    ]
    assert any(r.external_revision not in before.values() for r in after)
    assert any("MySQL" in r.content for r in after)


def test_summary_only_change_new_summary_revision(store, creds, fireflies):
    fireflies.add_transcript("mtg_sum")
    _acc, inst = _mk(store, creds)
    sync_connector(store, creds, inst.id)
    old = next(r for r in store.list_connector_records(inst.id)
               if r.external_type == "meeting_summary")
    fireflies.transcripts["mtg_sum"]["summary"] = {
        "overview": "Completely new summary text about Redis.",
    }
    sync_connector(store, creds, inst.id)
    summaries = [r for r in store.list_connector_records(inst.id)
                 if r.external_type == "meeting_summary"]
    assert any(r.external_revision != old.external_revision for r in summaries)
    assert any("Redis" in r.content for r in summaries)


def test_rate_limit_degrades(store, creds, fireflies):
    fireflies.add_transcript("mtg_1")
    _acc, inst = _mk(store, creds)
    fireflies.rate_limited = True
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "degraded"
    assert store.list_percepts() == []


def test_ownership_sealed(store, creds, fireflies):
    fireflies.add_transcript("mtg_1")
    _acc, inst = _mk(store, creds)
    sync_connector(store, creds, inst.id)
    assert all(
        p.metadata.get("vault_id") == "vault_work_acme"
        for p in store.list_percepts()
    )
