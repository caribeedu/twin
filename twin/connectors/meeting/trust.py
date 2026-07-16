"""Source-trust calibration for meetings and calendar (v0.6 §69)."""

from __future__ import annotations

from typing import Any

TRUST_TRANSCRIPT = 0.75
TRUST_PROVIDER_SUMMARY = 0.45   # derived — never independent of transcript
TRUST_CALENDAR_EVENT = 0.70
TRUST_FREEBUSY_ONLY = 0.55
TRUST_CANCELLED = 0.40


def trust_for_meeting(external_type: str, payload: dict[str, Any]) -> tuple[float, str]:
    if external_type == "meeting_summary":
        return TRUST_PROVIDER_SUMMARY, "derived"
    if external_type in ("meeting", "meeting_transcript", "transcript_segment"):
        return TRUST_TRANSCRIPT, "transcript"
    return TRUST_TRANSCRIPT, "unknown"


def trust_for_calendar(external_type: str, payload: dict[str, Any]) -> tuple[float, str]:
    status = str(payload.get("status") or "").lower()
    if status == "cancelled":
        return TRUST_CANCELLED, "cancelled"
    if payload.get("transparency") == "transparent" or payload.get("freebusy_only"):
        return TRUST_FREEBUSY_ONLY, "freebusy"
    return TRUST_CALENDAR_EVENT, "event"
