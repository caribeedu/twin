"""Calendar events → ConnectorRecord (v0.6 Phase 5 §38–39)."""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from ..meeting.correlate import (
    calendar_correlation_metadata,
    calendar_thread_key,
    correlation_artifact_refs,
)
from ..meeting.trust import trust_for_calendar
from ..models import ConnectorRecord

MAX_CONTENT_CHARS = 4000


def _hash8(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:8]


def _clip(text: str) -> str:
    text = (text or "").strip()
    if len(text) > MAX_CONTENT_CHARS:
        return text[: MAX_CONTENT_CHARS - 1] + "…"
    return text


def _start_iso(event: dict[str, Any]) -> Optional[str]:
    start = event.get("start") or {}
    if isinstance(start, dict):
        return start.get("dateTime") or start.get("date")
    return event.get("started_at")


def _end_iso(event: dict[str, Any]) -> Optional[str]:
    end = event.get("end") or {}
    if isinstance(end, dict):
        return end.get("dateTime") or end.get("date")
    return event.get("ended_at")


def _attendee_addrs(event: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for a in event.get("attendees") or []:
        if not isinstance(a, dict):
            continue
        email = (a.get("email") or "").lower()
        if email:
            out.append(email)
    return out


def revision_for_event(event: dict[str, Any]) -> str:
    for key in ("etag", "updated", "sequence"):
        if event.get(key) is not None:
            return f"{event[key]}.{_hash8(event.get('summary') or '')}"
    return _hash8(str(event.get("id") or "0"))


def record_from_event(
    *,
    connector_id: str,
    account_id: str,
    provider: str,
    account_key: str,
    calendar_id: str,
    event: dict[str, Any],
) -> ConnectorRecord:
    eid = str(event.get("id") or "?")
    title = event.get("summary") or event.get("title") or "(no title)"
    status = str(event.get("status") or "confirmed").lower()
    deleted = status == "cancelled" or bool(event.get("deleted"))
    start = _start_iso(event)
    end = _end_iso(event)
    organizer = ((event.get("organizer") or {}).get("email") or "").lower()
    attendees = _attendee_addrs(event)
    actors = [f"mail:{organizer}"] if organizer else []
    participants = list(actors)
    for addr in attendees:
        aid = f"mail:{addr}"
        if aid not in participants:
            participants.append(aid)

    # Privacy: expose free/busy fields separately from rich details (§39).
    freebusy_only = bool(event.get("freebusy_only"))
    transparency = event.get("transparency") or "opaque"
    trust, kind = trust_for_calendar("calendar_event", {
        "status": status,
        "transparency": transparency,
        "freebusy_only": freebusy_only,
    })
    corr = calendar_correlation_metadata({**event, "id": eid})
    tkey = calendar_thread_key(provider, account_key, eid)

    if freebusy_only or transparency == "transparent":
        content = (
            f"Calendar [{provider}] busy\n"
            f"When: {start or '?'} → {end or '?'}"
        )
        detail_level = "freebusy"
    else:
        desc = event.get("description") or ""
        loc = event.get("location") or ""
        lines = [
            f"Calendar [{provider}] {title}",
            f"When: {start or '?'} → {end or '?'}",
            f"Status: {status}",
        ]
        if loc:
            lines.append(f"Location: {loc}")
        if organizer:
            lines.append(f"Organizer: {organizer}")
        if attendees:
            lines.append("Attendees: " + ", ".join(attendees[:20]))
        if desc:
            lines.append("")
            lines.append(_clip(desc))
        content = "\n".join(lines)
        detail_level = "full"

    source_metadata: dict[str, Any] = {
        "provider": provider,
        "account_key": account_key,
        "calendar_id": calendar_id,
        "status": status,
        "detail_level": detail_level,
        "author_kind": kind,
        "transparency": transparency,
        "time_range": {"start": start, "end": end},
        "attendee_count": len(attendees),
        **corr,
    }
    if deleted:
        source_metadata["deleted"] = True

    return ConnectorRecord(
        connector_id=connector_id,
        source_account_id=account_id,
        external_type="calendar_event",
        external_id=eid,
        external_revision=revision_for_event(event),
        occurred_at=start,
        actor_ids=actors,
        participant_ids=participants,
        project_hint=calendar_id,
        thread_key=tkey,
        artifact_refs=(
            [{"kind": "calendar_event", "event_id": eid, "calendar_id": calendar_id}]
            + correlation_artifact_refs(corr)
        ),
        content=content,
        source_metadata=source_metadata,
        confidentiality={"source_trust": trust},
        deleted=deleted,
    )
