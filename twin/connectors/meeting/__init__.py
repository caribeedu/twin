"""Shared meeting cognitive layer (v0.6 Phase 5).

Provider adapters (Fireflies, …) live alongside this package; calendar
correlation keys are also defined here so both sides share one fingerprint.
"""

from .correlate import (
    calendar_correlation_metadata,
    calendar_thread_key,
    correlation_fingerprint,
    meeting_correlation_metadata,
    meeting_thread_key,
)
from .model import MeetingRecord, SpeakerIdentity, TranscriptSegment
from .normalize import records_from_meeting
from .speakers import attach_speaker_ids, map_speakers

__all__ = [
    "MeetingRecord",
    "SpeakerIdentity",
    "TranscriptSegment",
    "attach_speaker_ids",
    "calendar_correlation_metadata",
    "calendar_thread_key",
    "correlation_fingerprint",
    "map_speakers",
    "meeting_correlation_metadata",
    "meeting_thread_key",
    "records_from_meeting",
]
