"""Calendar ↔ meeting correlation keys (v0.6 Phase 5).

Phase 5 correlates at ``ConnectorRecord`` metadata / artifact_refs level.
Phase 7 promotes strong keys into ``WorkEpisode`` via
``twin.cognition.correlation`` (fingerprints remain weak until corroborated).
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Optional

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]+", re.UNICODE)


def _norm_title(title: Optional[str]) -> str:
    text = _PUNCT.sub(" ", (title or "").lower())
    return _WS.sub(" ", text).strip()


def _minute_bucket(iso_ts: Optional[str]) -> Optional[str]:
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
    except ValueError:
        return str(iso_ts)[:16] if iso_ts else None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def correlation_fingerprint(
    *, title: Optional[str], started_at: Optional[str],
) -> Optional[str]:
    """Weak calendar↔meeting key: minute bucket + normalized title."""
    bucket = _minute_bucket(started_at)
    title_n = _norm_title(title)
    if not bucket or not title_n:
        return None
    digest = hashlib.sha256(f"{bucket}|{title_n}".encode("utf-8")).hexdigest()[:16]
    return f"calmeet:{bucket}:{digest}"


def meeting_thread_key(provider: str, account_key: str, meeting_id: str) -> str:
    return f"meeting:{provider}:{account_key}:{meeting_id}"


def calendar_thread_key(provider: str, account_key: str, event_id: str) -> str:
    return f"calendar:{provider}:{account_key}:{event_id}"


def calendar_correlation_metadata(event: dict[str, Any]) -> dict[str, Any]:
    """Fields a calendar event exposes for later meeting linkage."""
    title = event.get("summary") or event.get("title") or ""
    start = (
        (event.get("start") or {}).get("dateTime")
        or (event.get("start") or {}).get("date")
        or event.get("started_at")
        or event.get("start_time")
    )
    fp = correlation_fingerprint(title=title, started_at=start)
    meta: dict[str, Any] = {
        "calendar_event_id": event.get("id") or event.get("external_id"),
        "iCalUID": event.get("iCalUID") or event.get("ical_uid"),
        "conference_url": (
            event.get("hangoutLink")
            or event.get("conference_url")
            or _first_entry_point(event)
        ),
        "correlation_fingerprint": fp,
    }
    return {k: v for k, v in meta.items() if v}


def meeting_correlation_metadata(meeting: dict[str, Any]) -> dict[str, Any]:
    title = meeting.get("title") or ""
    start = meeting.get("started_at") or meeting.get("date")
    fp = correlation_fingerprint(title=title, started_at=start)
    meta: dict[str, Any] = {
        "calendar_event_id": meeting.get("calendar_event_id"),
        "iCalUID": meeting.get("calendar_iCalUID") or meeting.get("ical_uid"),
        "conference_url": meeting.get("conference_url"),
        "correlation_fingerprint": fp,
    }
    return {k: v for k, v in meta.items() if v}


def _first_entry_point(event: dict[str, Any]) -> Optional[str]:
    conf = event.get("conferenceData") or {}
    for ep in conf.get("entryPoints") or []:
        if isinstance(ep, dict) and ep.get("uri"):
            return ep["uri"]
    return None


def correlation_artifact_refs(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Lightweight refs so retrieval can join calendar ↔ meeting later."""
    refs: list[dict[str, Any]] = []
    if meta.get("calendar_event_id"):
        refs.append({
            "kind": "calendar_event",
            "external_id": meta["calendar_event_id"],
            "download_status": "metadata_only",
        })
    if meta.get("correlation_fingerprint"):
        refs.append({
            "kind": "correlation_fingerprint",
            "external_id": meta["correlation_fingerprint"],
            "download_status": "metadata_only",
        })
    if meta.get("conference_url"):
        refs.append({
            "kind": "conference_url",
            "external_id": meta["conference_url"],
            "download_status": "metadata_only",
        })
    return refs
