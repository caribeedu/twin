"""Unit tests for shared meeting model / speakers / correlation (Phase 5)."""

from __future__ import annotations

from twin.connectors.meeting import (
    MeetingRecord,
    TranscriptSegment,
    correlation_fingerprint,
    map_speakers,
    records_from_meeting,
    revision_for_meeting,
)
from twin.connectors.meeting.normalize import (
    MAX_CHUNK_CHARS,
    revision_for_summary,
)
from twin.connectors.meeting.speakers import (
    ACTOR_PROMOTE_THRESHOLD,
    attach_speaker_ids,
)
from twin.connectors.calendar.normalize import (
    freebusy_projection,
    qualified_event_id,
    record_from_event,
)


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
        transcript_complete=True,
        provider_status="complete",
    )
    recs = records_from_meeting(
        connector_id="conn_f",
        account_id="acc_f",
        account_key="edu@acme.com",
        meeting=meeting,
    )
    chunks = [r for r in recs if r.external_type == "meeting_transcript_chunk"]
    assert cal.source_metadata["correlation_fingerprint"] == fp
    assert chunks[0].source_metadata["correlation_fingerprint"] == fp
    assert cal.external_id == qualified_event_id("primary", "evt_arch_1")


def test_long_transcript_chunked_no_loss():
    segs = [
        TranscriptSegment(i, "Alice", f"word-{i} " + ("x" * 200))
        for i in range(80)
    ]
    meeting = MeetingRecord(
        provider="fireflies",
        external_id="mtg_long",
        title="Long",
        started_at="2026-07-15T10:00:00Z",
        segments=segs,
        transcript_complete=True,
        provider_status="complete",
    )
    recs = records_from_meeting(
        connector_id="c", account_id="a", account_key="edu@acme.com",
        meeting=meeting,
    )
    chunks = [r for r in recs if r.external_type == "meeting_transcript_chunk"]
    assert len(chunks) >= 2
    joined = "\n".join(c.content for c in chunks)
    for i in range(80):
        assert f"word-{i}" in joined
    assert all(len(c.content) <= MAX_CHUNK_CHARS + 200 for c in chunks)
    assert len({c.thread_key for c in chunks}) == 1


def test_revision_tracks_full_content():
    m1 = {
        "external_id": "m",
        "title": "T",
        "transcript_version": "v1",
        "segments": [
            {"index": 0, "speaker_label": "A", "text": "one"},
            {"index": 1, "speaker_label": "B", "text": "two"},
        ],
        "speakers": [],
    }
    m2 = dict(m1)
    m2["segments"] = [
        {"index": 0, "speaker_label": "A", "text": "one"},
        {"index": 1, "speaker_label": "B", "text": "CHANGED"},
    ]
    assert revision_for_meeting(m1) != revision_for_meeting(m2)
    assert revision_for_summary(m1, "sum A") != revision_for_summary(m1, "sum B")


def test_summary_is_derived_not_primary():
    meeting = MeetingRecord(
        provider="fireflies",
        external_id="mtg_x",
        title="Standup",
        started_at="2026-07-15T10:00:00Z",
        segments=[TranscriptSegment(0, "Edu", "Ship Friday")],
        provider_summary="Ship Friday confirmed.",
        transcript_complete=True,
        provider_status="complete",
    )
    recs = records_from_meeting(
        connector_id="c", account_id="a", account_key="edu@acme.com",
        meeting=meeting,
    )
    types = [r.external_type for r in recs]
    assert "meeting_manifest" in types
    assert "meeting_transcript_chunk" in types
    assert "meeting_summary" in types
    sm = next(r for r in recs if r.external_type == "meeting_summary")
    assert sm.source_metadata["derived"] == "provider_summary"


def test_speaker_1_not_auto_merged_and_not_global():
    speakers = map_speakers(
        provider="fireflies",
        account_key="acct_a",
        meeting_id="m1",
        segment_labels=["Speaker 1", "Alice"],
        participants=[{"name": "Alice", "email": "alice@acme.com"},
                      {"name": "Bob", "email": "bob@acme.com"}],
        provider_speaker_map={
            "Alice": {"name": "Alice", "email": "alice@acme.com", "id": "1"},
        },
    )
    by = {s.label: s for s in speakers}
    assert by["Alice"].confirmed is True
    assert by["Alice"].confidence >= ACTOR_PROMOTE_THRESHOLD
    assert by["Speaker 1"].confidence < ACTOR_PROMOTE_THRESHOLD
    assert by["Speaker 1"].email is None
    assert by["Alice"].actor_id == "mail:alice@acme.com"
    # Provider speaker ids are account-qualified when no email.
    speakers2 = map_speakers(
        provider="fireflies",
        account_key="acct_b",
        meeting_id="m9",
        segment_labels=["Carol"],
        provider_speaker_map={"Carol": {"id": "99", "name": "Carol"}},
    )
    assert speakers2[0].actor_id == "meeting:fireflies:acct_b:speaker:99"


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
        account_key="edu@acme.com",
        meeting_id="m1",
        segment_labels=["Alice", "Speaker 2"],
        participants=[{"name": "Alice", "email": "alice@acme.com"}],
        provider_speaker_map={
            "Alice": {"email": "alice@acme.com", "id": "a"},
        },
    )
    out = attach_speaker_ids(meeting, speakers)
    assert out.segments[0].speaker_identity_id == "mail:alice@acme.com"
    assert out.segments[1].speaker_identity_id is None


def test_freebusy_projection_strips_sensitive_fields():
    proj = freebusy_projection({
        "id": "e1",
        "summary": "Secret",
        "description": "notes",
        "attendees": [{"email": "x@y.com"}],
        "hangoutLink": "https://meet.google.com/x",
        "start": {"dateTime": "2026-07-15T15:00:00Z"},
        "end": {"dateTime": "2026-07-15T16:00:00Z"},
        "updated": "2026-07-15T14:00:00Z",
        "status": "confirmed",
    })
    assert "summary" not in proj
    assert "description" not in proj
    assert "attendees" not in proj
    assert "hangoutLink" not in proj
    assert proj["freebusy_only"] is True
