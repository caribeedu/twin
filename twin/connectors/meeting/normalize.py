"""MeetingRecord → ConnectorRecord (v0.6 Phase 5)."""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from ..models import ConnectorRecord, idempotency_key
from .correlate import (
    correlation_artifact_refs,
    meeting_correlation_metadata,
    meeting_thread_key,
)
from .model import MeetingRecord
from .trust import trust_for_meeting

MAX_CONTENT_CHARS = 12000


def _hash8(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:8]


def _clip(text: str) -> str:
    text = (text or "").strip()
    if len(text) > MAX_CONTENT_CHARS:
        return text[: MAX_CONTENT_CHARS - 1] + "…"
    return text


def revision_for_meeting(meeting: dict[str, Any]) -> str:
    for key in ("transcript_version", "etag", "updated_at", "date"):
        if meeting.get(key):
            return f"{meeting[key]}.{_hash8(meeting.get('title') or '')}"
    body = "|".join(
        f"{s.get('speaker_label')}:{s.get('text')}"
        for s in (meeting.get("segments") or [])[:20]
        if isinstance(s, dict)
    )
    return _hash8(f"{meeting.get('external_id')}|{body}")


def records_from_meeting(
    *,
    connector_id: str,
    account_id: str,
    account_key: str,
    meeting: MeetingRecord | dict[str, Any],
) -> list[ConnectorRecord]:
    """Emit transcript (primary) + optional provider-summary (derived)."""
    data = meeting.to_dict() if isinstance(meeting, MeetingRecord) else dict(meeting)
    provider = data.get("provider") or "meeting"
    mid = str(data.get("external_id") or data.get("id") or "?")
    title = data.get("title") or "(untitled meeting)"
    corr = meeting_correlation_metadata(data)
    tkey = meeting_thread_key(provider, account_key, mid)

    actors: list[str] = []
    for sp in data.get("speakers") or []:
        if not isinstance(sp, dict):
            continue
        aid = sp.get("actor_id")
        if aid and aid not in actors and float(sp.get("confidence") or 0) >= 0.30:
            actors.append(aid)
    for p in data.get("participants") or []:
        if isinstance(p, str) and "@" in p:
            aid = f"mail:{p.lower()}"
            if aid not in actors:
                actors.append(aid)

    lines = [f"# {title}"]
    if data.get("started_at"):
        lines.append(f"When: {data['started_at']}")
    for seg in data.get("segments") or []:
        if not isinstance(seg, dict):
            continue
        speaker = seg.get("speaker_label") or "?"
        text = seg.get("text") or ""
        lines.append(f"{speaker}: {text}")
    transcript_body = _clip("\n".join(lines))
    trust, kind = trust_for_meeting("meeting_transcript", data)
    rev = revision_for_meeting(data)

    speaker_meta = [
        {
            "label": sp.get("label"),
            "actor_id": sp.get("actor_id"),
            "confidence": sp.get("confidence"),
            "confirmed": sp.get("confirmed"),
            "signals": sp.get("mapping_signals") or [],
        }
        for sp in (data.get("speakers") or [])
        if isinstance(sp, dict)
    ]

    source_metadata: dict[str, Any] = {
        "provider": provider,
        "account_key": account_key,
        "meeting_id": mid,
        "evidence_role": "primary",
        "author_kind": kind,
        "transcript_version": data.get("transcript_version"),
        "speakers": speaker_meta,
        "unresolved_speakers": [
            s["label"] for s in speaker_meta
            if float(s.get("confidence") or 0) < 0.5
        ],
        **corr,
    }
    artifacts = (
        [{"kind": "meeting_transcript", "meeting_id": mid}]
        + correlation_artifact_refs(corr)
    )
    if data.get("recording_ref"):
        artifacts.append({
            "kind": "recording",
            "external_id": data["recording_ref"],
            "download_status": "metadata_only",
        })

    # Distinct keys per record — one raw fetch may expand to transcript +
    # summary; sharing the raw revision key would look like a collision.
    records = [ConnectorRecord(
        connector_id=connector_id,
        source_account_id=account_id,
        external_type="meeting_transcript",
        external_id=mid,
        external_revision=rev,
        idempotency_key=idempotency_key(
            provider, account_id, "meeting_transcript", mid, rev,
        ),
        occurred_at=data.get("started_at") or data.get("date"),
        actor_ids=actors,
        participant_ids=list(actors),
        project_hint=None,
        thread_key=tkey,
        artifact_refs=artifacts,
        content=transcript_body,
        source_metadata=source_metadata,
        confidentiality={"source_trust": trust},
    )]

    summary = data.get("provider_summary")
    if summary:
        s_trust, s_kind = trust_for_meeting("meeting_summary", data)
        s_id = f"{mid}:summary"
        s_rev = f"{rev}.summary"
        records.append(ConnectorRecord(
            connector_id=connector_id,
            source_account_id=account_id,
            external_type="meeting_summary",
            external_id=s_id,
            external_revision=s_rev,
            idempotency_key=idempotency_key(
                provider, account_id, "meeting_summary", s_id, s_rev,
            ),
            occurred_at=data.get("started_at") or data.get("date"),
            actor_ids=[],
            participant_ids=list(actors),
            thread_key=tkey,
            artifact_refs=[
                {"kind": "meeting_summary", "meeting_id": mid},
                {"kind": "derived_from", "external_id": mid},
            ],
            content=_clip(f"[provider summary] {title}\n\n{summary}"),
            source_metadata={
                "provider": provider,
                "meeting_id": mid,
                "evidence_role": "derived",
                "derived": "provider_summary",
                "author_kind": s_kind,
                "lineage_root": mid,
                **corr,
            },
            confidentiality={"source_trust": s_trust},
        ))
    return records
