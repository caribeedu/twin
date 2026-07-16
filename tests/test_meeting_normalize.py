"""Unit tests for shared meeting model / speakers / correlation (Phase 5)."""

from __future__ import annotations

from twin.connectors.meeting import (
    MeetingRecord,
    TranscriptSegment,
    correlation_fingerprint,
    map_speakers,
    records_from_meeting,
)
from twin.connectors.meeting.speakers import attach_speaker_ids
from twin.connectors.calendar.normalize import record_from_event


def test_correlation_fingerprint_stable():
    a = correlation_fingerprint(
        title="Architecture Sync!!!", started_at="2026-07-15T15:00:30Z",
    )
    b = correlation_fingerprint(
        title="architecture sync", started_at="2026-07-15T15:00:59Z",
    )
    assert a == b
    assert a.startswith("calmeet:2026-07-15T15:00Z:")


def test_calendar_and_meeting_share_fingerprint():
    start = "2026-07-15T15:00:00Z"
    title = "Architecture sync"
    fp = correlation_fingerprint(title=title, started_at=start)
    cal = record_from_event(
        connector_id="conn_c",
        account_id="acc_c",
        provider="google_calendar",
        account_key="edu@acme.com",
        calendar_id="primary",
        event={
            "id": "evt_arch_1",
            "summary": title,
            "status": "confirmed",
            "updated": "2026-07-15T14:00:00Z",
            "start": {"dateTime": start},
            "end": {"dateTime": "2026-07-15T16:00:00Z"},
            "hangoutLink": "https://meet.google.com/abc-defg",
            "organizer": {"email": "edu@acme.com"},
            "attendees": [{"email": "alice@acme.com"}],
        },
    )
    meeting = MeetingRecord(
        provider="fireflies",
        external_id="mtg_1",
        title=title,
        started_at=start,
        calendar_event_id="evt_arch_1",
        conference_url="https://meet.google.com/abc-defg",
        segments=[TranscriptSegment(0, "Edu", "Hello")],
        provider_summary="Decided Postgres.",
    )
    recs = records_from_meeting(
        connector_id="conn_f",
        account_id="acc_f",
        account_key="edu@acme.com",
        meeting=meeting,
    )
    tr = recs[0]
    assert cal.source_metadata["correlation_fingerprint"] == fp
    assert tr.source_metadata["correlation_fingerprint"] == fp
    assert cal.source_metadata["calendar_event_id"] == "evt_arch_1"
    assert tr.source_metadata["calendar_event_id"] == "evt_arch_1"


def test_summary_is_derived_not_primary():
    meeting = MeetingRecord(
        provider="fireflies",
        external_id="mtg_x",
        title="Standup",
        started_at="2026-07-15T10:00:00Z",
        segments=[TranscriptSegment(0, "Edu", "Ship Friday")],
        provider_summary="Ship Friday confirmed.",
    )
    recs = records_from_meeting(
        connector_id="c", account_id="a", account_key="edu@acme.com",
        meeting=meeting,
    )
    assert len(recs) == 2
    assert recs[0].external_type == "meeting_transcript"
    assert recs[1].external_type == "meeting_summary"
    assert recs[1].source_metadata["derived"] == "provider_summary"
    assert recs[1].confidentiality["source_trust"] < recs[0].confidentiality[
        "source_trust"
    ]


def test_speaker_1_not_auto_merged():
    speakers = map_speakers(
        provider="fireflies",
        segment_labels=["Speaker 1", "Alice"],
        participants=[{"name": "Alice", "email": "alice@acme.com"},
                      {"name": "Bob", "email": "bob@acme.com"}],
        provider_speaker_map={
            "Alice": {"name": "Alice", "email": "alice@acme.com", "id": "1"},
        },
    )
    by = {s.label: s for s in speakers}
    assert by["Alice"].confirmed is True
    assert by["Alice"].confidence >= 0.9
    assert by["Speaker 1"].confidence < 0.5
    assert by["Speaker 1"].email is None


def test_attach_speaker_ids_on_segments():
    meeting = MeetingRecord(
        provider="fireflies",
        external_id="m1",
        title="t",
        segments=[
            TranscriptSegment(0, "Alice", "hi"),
            TranscriptSegment(1, "Speaker 2", "yo"),
        ],
    )
    speakers = map_speakers(
        provider="fireflies",
        segment_labels=["Alice", "Speaker 2"],
        participants=[{"name": "Alice", "email": "alice@acme.com"}],
        provider_speaker_map={
            "Alice": {"email": "alice@acme.com", "id": "a"},
        },
    )
    out = attach_speaker_ids(meeting, speakers)
    assert out.segments[0].speaker_identity_id == "mail:alice@acme.com"
    assert out.segments[1].confidence < 0.5
