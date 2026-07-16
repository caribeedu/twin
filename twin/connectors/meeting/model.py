"""Provider-agnostic meeting transcript model (v0.6 Phase 5 §40–42).

Adapters (Fireflies, future Meetily, …) normalize into this shape before
becoming ``ConnectorRecord``s. Provider-generated summaries are derived
evidence — the transcript remains primary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class TranscriptSegment:
    index: int
    speaker_label: str
    text: str
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    speaker_identity_id: Optional[str] = None
    confidence: float = 1.0


@dataclass
class SpeakerIdentity:
    """Mapped speaker — never assume label == person without evidence."""
    label: str
    actor_id: Optional[str] = None
    display_name: Optional[str] = None
    email: Optional[str] = None
    provider_speaker_id: Optional[str] = None
    confidence: float = 0.0
    confirmed: bool = False
    mapping_signals: list[str] = field(default_factory=list)


@dataclass
class MeetingRecord:
    provider: str
    external_id: str
    title: str
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_seconds: Optional[int] = None
    participants: list[str] = field(default_factory=list)
    organizer: Optional[str] = None
    segments: list[TranscriptSegment] = field(default_factory=list)
    speakers: list[SpeakerIdentity] = field(default_factory=list)
    provider_summary: Optional[str] = None
    transcript_version: Optional[str] = None
    calendar_event_id: Optional[str] = None
    calendar_iCalUID: Optional[str] = None
    conference_url: Optional[str] = None
    # Stable provider recording id when known — never a signed/expiring URL.
    recording_id: Optional[str] = None
    # Transient media URLs stay in raw_metadata only (not identity).
    host_email: Optional[str] = None
    provider_status: Optional[str] = None   # processing | partial | complete | live | failed
    transcript_complete: bool = True
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "external_id": self.external_id,
            "title": self.title,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "participants": list(self.participants),
            "organizer": self.organizer,
            "segments": [
                {
                    "index": s.index,
                    "speaker_label": s.speaker_label,
                    "text": s.text,
                    "start_ms": s.start_ms,
                    "end_ms": s.end_ms,
                    "speaker_identity_id": s.speaker_identity_id,
                    "confidence": s.confidence,
                }
                for s in self.segments
            ],
            "speakers": [
                {
                    "label": sp.label,
                    "actor_id": sp.actor_id,
                    "display_name": sp.display_name,
                    "email": sp.email,
                    "provider_speaker_id": sp.provider_speaker_id,
                    "confidence": sp.confidence,
                    "confirmed": sp.confirmed,
                    "mapping_signals": list(sp.mapping_signals),
                }
                for sp in self.speakers
            ],
            "provider_summary": self.provider_summary,
            "transcript_version": self.transcript_version,
            "calendar_event_id": self.calendar_event_id,
            "calendar_iCalUID": self.calendar_iCalUID,
            "conference_url": self.conference_url,
            "recording_id": self.recording_id,
            "host_email": self.host_email,
            "provider_status": self.provider_status,
            "transcript_complete": self.transcript_complete,
            "raw_metadata": dict(self.raw_metadata),
        }
