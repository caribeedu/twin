"""Calendar connector against the offline API double."""
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

from tests.connectors.calendar.calendar_mock import FakeCalendarAPI

TOKEN = "ya29.cal-test-token"
CAL = "primary"


@pytest.fixture()
def creds(tmp_path):
    return build_credential_store(tmp_path / "creds-home")


@pytest.fixture()
def calendar(monkeypatch):
    api = FakeCalendarAPI()
    from twin.connectors.calendar import client as cclient
    real_build = cclient._build_http

    def fake_build(base_url, token):
        original = real_build(base_url, token)
        headers = dict(original.headers)
        original.close()
        return httpx.Client(
            transport=api.transport(),
            base_url="https://www.googleapis.com/calendar/v3/",
            headers=headers,
        )

    monkeypatch.setattr(cclient, "_build_http", fake_build)
    return api


def _mk(store, creds, *, calendars=(CAL,), secret=TOKEN, extra=None):
    acc = register_source_account(
        store, connector_type="calendar", source_owner="employer", org_key="acme",
        owner_principal_id="principal_test",
        external_account_id="edu@acme.com",
    )
    inst = add_connector_instance(
        store, creds, account_id=acc.id, secret=secret,
        configuration={"calendars": list(calendars), **(extra or {})},
    )
    return acc, inst


def test_empty_calendars_await_configuration(store, creds, calendar):
    _acc, inst = _mk(store, creds, calendars=())
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "awaiting_configuration"


def test_sync_ingests_event_with_correlation(store, creds, calendar):
    calendar.add_event(
        "evt_arch_1",
        summary="Architecture sync",
        start="2026-07-15T15:00:00Z",
        hangout_link="https://meet.google.com/abc-defg",
        description="Decide queue technology",
    )
    _acc, inst = _mk(store, creds)
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "healthy"
    assert result.percepts == 1
    rec = store.list_connector_records(inst.id)[0]
    assert rec.external_type == "calendar_event"
    assert rec.external_id == f"google_calendar:{CAL}:evt_arch_1"
    assert rec.thread_key.startswith("calendar:google_calendar:")
    assert rec.source_metadata["provider_event_id"] == "evt_arch_1"
    assert rec.source_metadata["calendar_event_id"] == "evt_arch_1"
    assert rec.source_metadata["conference_url"] == "https://meet.google.com/abc-defg"
    fp = correlation_fingerprint(
        title="Architecture sync", started_at="2026-07-15T15:00:00Z",
    )
    assert rec.source_metadata["correlation_fingerprint"] == fp
    ckpt = store.get_connector_checkpoint(inst.id, f"calendar:{CAL}")
    assert ckpt is not None
    assert ckpt.cursor.get("watermark")


def test_freebusy_redacts_raw_and_record(store, creds, calendar):
    calendar.add_event(
        "evt_fb", summary="Secret 1:1", description="private notes",
        attendees=["doctor@clinic.com"],
        hangout_link="https://meet.google.com/secret",
    )
    _acc, inst = _mk(store, creds, extra={"freebusy_only": True})
    sync_connector(store, creds, inst.id)
    rec = store.list_connector_records(inst.id)[0]
    assert rec.source_metadata["detail_level"] == "freebusy"
    assert "Secret" not in rec.content
    assert "private notes" not in rec.content
    assert "doctor@" not in rec.content
    assert rec.confidentiality["source_trust"] == 0.55
    raw = store.list_connector_raw_items(inst.id)[0]
    blob = str(raw.payload)
    assert "Secret" not in blob
    assert "private notes" not in blob
    assert "doctor@" not in blob
    assert "meet.google.com/secret" not in blob
    assert raw.payload["object"].get("freebusy_only") is True
    assert "summary" not in raw.payload["object"]
    assert "description" not in raw.payload["object"]


def test_same_event_id_two_calendars_no_collision(store, creds, calendar):
    calendar.add_event("shared_id", calendar_id="primary", summary="Primary copy")
    calendar.add_event(
        "shared_id", calendar_id="work@acme.com", summary="Work copy",
        updated="2026-07-15T15:00:00Z",
    )
    _acc, inst = _mk(store, creds, calendars=("primary", "work@acme.com"))
    sync_connector(store, creds, inst.id)
    ids = {r.external_id for r in store.list_connector_records(inst.id)}
    assert "google_calendar:primary:shared_id" in ids
    assert "google_calendar:work@acme.com:shared_id" in ids
    assert len(ids) == 2


def test_cancel_one_calendar_does_not_delete_other(store, creds, calendar):
    calendar.add_event("shared_id", calendar_id="primary", summary="Primary")
    calendar.add_event(
        "shared_id", calendar_id="work@acme.com", summary="Work",
        updated="2026-07-15T15:00:00Z",
    )
    _acc, inst = _mk(store, creds, calendars=("primary", "work@acme.com"))
    sync_connector(store, creds, inst.id)
    calendar.cancel_event("shared_id", calendar_id="primary")
    sync_connector(store, creds, inst.id)
    by_id = {r.external_id: r for r in store.list_connector_records(inst.id)}
    # Latest revision for primary is deleted; work remains live.
    primary_revs = [r for r in store.list_connector_records(inst.id)
                    if r.external_id == "google_calendar:primary:shared_id"]
    assert any(r.deleted for r in primary_revs)
    work = [r for r in store.list_connector_records(inst.id)
            if r.external_id == "google_calendar:work@acme.com:shared_id"]
    assert work and not any(r.deleted for r in work)


def test_cancelled_emits_tombstone(store, creds, calendar):
    calendar.add_event("evt_1", summary="standup")
    _acc, inst = _mk(store, creds)
    sync_connector(store, creds, inst.id)
    calendar.cancel_event("evt_1")
    result = sync_connector(store, creds, inst.id)
    assert result.streams[0].deletion_events >= 1 or any(
        r.deleted for r in store.list_connector_records(inst.id)
    )
    deleted = [r for r in store.list_connector_records(inst.id) if r.deleted]
    assert deleted
    assert deleted[-1].external_type == "calendar_event"


def test_idempotent_resync(store, creds, calendar):
    calendar.add_event("evt_1", summary="one")
    _acc, inst = _mk(store, creds)
    assert sync_connector(store, creds, inst.id).percepts == 1
    assert sync_connector(store, creds, inst.id).percepts == 0


def test_rate_limit_degrades(store, creds, calendar):
    calendar.add_event("evt_1", summary="one")
    _acc, inst = _mk(store, creds)
    calendar.rate_limited = True
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "degraded"
    assert store.list_percepts() == []


def test_ownership_sealed_on_percept(store, creds, calendar):
    calendar.add_event("evt_1", summary="work sync")
    _acc, inst = _mk(store, creds)
    sync_connector(store, creds, inst.id)
    percepts = store.list_percepts()
    assert percepts
    assert all(p.metadata.get("vault_id") == "vault_work_acme" for p in percepts)
