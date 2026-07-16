"""v0.6 Phase 5 — Fireflies connector against the offline API double."""

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
            base_url="https://api.fireflies.ai/v2/",
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


def test_sync_transcript_and_derived_summary(store, creds, fireflies):
    fireflies.add_transcript("mtg_1")
    _acc, inst = _mk(store, creds)
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "healthy"
    # transcript + provider summary
    assert result.percepts == 2
    by_type = {}
    for r in store.list_connector_records(inst.id):
        by_type.setdefault(r.external_type, []).append(r)
    assert "meeting_transcript" in by_type
    assert "meeting_summary" in by_type
    tr = by_type["meeting_transcript"][0]
    sm = by_type["meeting_summary"][0]
    assert tr.thread_key == sm.thread_key
    assert tr.thread_key.startswith("meeting:fireflies:")
    assert tr.confidentiality["source_trust"] == 0.75
    assert sm.confidentiality["source_trust"] == 0.45
    assert sm.source_metadata["derived"] == "provider_summary"
    assert sm.source_metadata["evidence_role"] == "derived"
    assert tr.source_metadata["evidence_role"] == "primary"
    assert tr.source_metadata["calendar_event_id"] == "evt_arch_1"
    fp = correlation_fingerprint(
        title="Architecture sync", started_at="2026-07-15T15:00:00Z",
    )
    assert tr.source_metadata["correlation_fingerprint"] == fp
    ckpt = store.get_connector_checkpoint(inst.id, "meetings")
    assert ckpt is not None
    assert ckpt.cursor.get("watermark")


def test_speaker_mapping_keeps_confidence(store, creds, fireflies):
    fireflies.add_transcript(
        "mtg_spk",
        sentences=[
            {"speaker_name": "Speaker 1", "text": "Hello"},
            {"speaker_name": "Alice", "text": "Hi"},
        ],
        speakers=[{"name": "Alice", "email": "alice@acme.com", "id": "sp_a"}],
        participants=[{"name": "Alice", "email": "alice@acme.com"}],
    )
    _acc, inst = _mk(store, creds)
    sync_connector(store, creds, inst.id)
    tr = next(r for r in store.list_connector_records(inst.id)
              if r.external_type == "meeting_transcript")
    speakers = tr.source_metadata["speakers"]
    by_label = {s["label"]: s for s in speakers}
    assert by_label["Alice"]["confidence"] >= 0.90
    assert by_label["Alice"]["confirmed"] is True
    assert by_label["Speaker 1"]["confidence"] < 0.5
    assert "Speaker 1" in tr.source_metadata["unresolved_speakers"]


def test_idempotent_resync(store, creds, fireflies):
    fireflies.add_transcript("mtg_1")
    _acc, inst = _mk(store, creds)
    first = sync_connector(store, creds, inst.id)
    again = sync_connector(store, creds, inst.id)
    assert first.percepts == 2
    assert again.percepts == 0


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
