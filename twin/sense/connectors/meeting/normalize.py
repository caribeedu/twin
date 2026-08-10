"""MeetingRecord → ConnectorRecord.

Long transcripts become ``meeting_transcript_chunk`` records — never silent
truncation of primary evidence. Optional ``meeting_manifest`` + derived summary.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from ..models import ConnectorRecord, idempotency_key
from .correlate import (
    correlation_artifact_refs,
    meeting_correlation_metadata,
    meeting_thread_key,
)
from .model import MeetingRecord
from .speakers import ACTOR_PROMOTE_THRESHOLD, resolved_actor_ids
from .trust import trust_for_meeting

# Soft budget per chunk content. Segments are never split mid-utterance.
MAX_CHUNK_CHARS = 8000


def _hash8(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:8]


def _hash16(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def _canonical_segments(segments: list[Any]) -> list[tuple]:
    out = []
    for s in segments or []:
        if not isinstance(s, dict):
            continue
        out.append((
            s.get("index"),
            s.get("speaker_label") or "",
            s.get("text") or "",
            s.get("start_ms"),
            s.get("end_ms"),
        ))
    return out


def content_hash_segments(segments: list[Any]) -> str:
    return _hash16(json.dumps(_canonical_segments(segments), sort_keys=True))


def segments_revision(meeting: dict[str, Any]) -> str:
    """Revision stem for transcript chunks — ignores summary text."""
    provider_stamp = (
        meeting.get("transcript_version")
        or meeting.get("etag")
        or meeting.get("updated_at")
        or meeting.get("date")
        or "1"
    )
    seg_hash = content_hash_segments(meeting.get("segments") or [])
    speakers = meeting.get("speakers") or []
    sp_canon = [
        (sp.get("label"), sp.get("actor_id"), sp.get("confidence"),
         sp.get("provider_speaker_id"))
        for sp in speakers if isinstance(sp, dict)
    ]
    sp_hash = _hash8(json.dumps(sp_canon, sort_keys=True, default=str))
    status = meeting.get("provider_status") or ""
    return f"{provider_stamp}.{seg_hash}.{sp_hash}.{_hash8(status)}"


def revision_for_meeting(meeting: dict[str, Any]) -> str:
    """Raw-item revision: segments + summary (any cognitive change advances)."""
    base = segments_revision(meeting)
    summary_hash = _hash16(str(meeting.get("provider_summary") or ""))
    return f"{base}.sum{summary_hash}"


def revision_for_summary(meeting: dict[str, Any], summary_text: str) -> str:
    """Summary revision follows summary text — independent of transcript."""
    provider_stamp = (
        meeting.get("transcript_version")
        or meeting.get("updated_at")
        or meeting.get("date")
        or "1"
    )
    return f"{provider_stamp}.summary.{_hash16(summary_text or '')}"


def _chunk_segments(segments: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Pack whole segments into chunks under MAX_CHUNK_CHARS."""
    if not segments:
        return [[]]
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    size = 0
    for seg in segments:
        line = f"{seg.get('speaker_label') or '?'}: {seg.get('text') or ''}\n"
        line_len = len(line)
        if current and size + line_len > MAX_CHUNK_CHARS:
            chunks.append(current)
            current = []
            size = 0
        current.append(seg)
        size += line_len
    if current or not chunks:
        chunks.append(current)
    return chunks


def _participant_ids(data: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for p in data.get("participants") or []:
        if isinstance(p, str) and "@" in p:
            aid = f"mail:{p.lower()}"
            if aid not in out:
                out.append(aid)
        elif isinstance(p, dict):
            email = (p.get("email") or "").lower()
            if email:
                aid = f"mail:{email}"
                if aid not in out:
                    out.append(aid)
    for key in ("organizer", "host_email"):
        email = (data.get(key) or "")
        if isinstance(email, str) and "@" in email:
            aid = f"mail:{email.lower()}"
            if aid not in out:
                out.append(aid)
    return out


def _tombstone(
    *,
    connector_id: str,
    account_id: str,
    external_type: str,
    external_id: str,
    revision: str,
    provider: str,
    thread_key: str,
    meeting_id: str,
    content: str,
) -> ConnectorRecord:
    return ConnectorRecord(
        connector_id=connector_id,
        source_account_id=account_id,
        external_type=external_type,
        external_id=external_id,
        external_revision=revision,
        idempotency_key=idempotency_key(
            provider, account_id, external_type, external_id, revision,
        ),
        thread_key=thread_key,
        content=content,
        deleted=True,
        source_metadata={
            "provider": provider,
            "meeting_id": meeting_id,
            "lineage_root": meeting_id,
            "deleted": True,
        },
        confidentiality={"source_trust": 0.40},
    )


def records_from_meeting(
    *,
    connector_id: str,
    account_id: str,
    account_key: str,
    meeting: MeetingRecord | dict[str, Any],
    previous: Optional[dict[str, Any]] = None,
) -> list[ConnectorRecord]:
    """Emit manifest + transcript chunks (primary) + optional summary (derived).

    ``previous`` (from store) may include ``chunk_count`` and ``had_summary`` so
    structural shrinks emit tombstones for retired chunks/summaries.
    """
    data = meeting.to_dict() if isinstance(meeting, MeetingRecord) else dict(meeting)
    # Signed / expiring media URLs must never reach cognitive envelopes.
    raw_meta = data.get("raw_metadata")
    if isinstance(raw_meta, dict) and "media_urls" in raw_meta:
        raw_meta = dict(raw_meta)
        raw_meta.pop("media_urls", None)
        data["raw_metadata"] = raw_meta
    provider = data.get("provider") or "meeting"
    mid = str(data.get("external_id") or data.get("id") or "?")
    title = data.get("title") or "(untitled meeting)"
    corr = meeting_correlation_metadata(data)
    tkey = meeting_thread_key(provider, account_key, mid)
    seg_rev = segments_revision(data)
    complete = bool(data.get("transcript_complete", True))
    status = data.get("provider_status") or ("complete" if complete else "processing")

    segments = [s for s in (data.get("segments") or []) if isinstance(s, dict)]
    spoke_labels = {
        str(s.get("speaker_label") or "") for s in segments if s.get("text")
    }
    actors = resolved_actor_ids(
        data.get("speakers") or [], spoke_labels=spoke_labels,
    )
    participants = list(_participant_ids(data))
    for aid in actors:
        if aid not in participants:
            participants.append(aid)

    speaker_meta = [
        {
            "label": sp.get("label"),
            "actor_id": sp.get("actor_id"),
            "confidence": sp.get("confidence"),
            "confirmed": sp.get("confirmed"),
            "signals": sp.get("mapping_signals") or [],
            "spoke": str(sp.get("label") or "") in spoke_labels,
        }
        for sp in (data.get("speakers") or [])
        if isinstance(sp, dict)
    ]
    common_meta = {
        "provider": provider,
        "account_key": account_key,
        "meeting_id": mid,
        "lineage_root": mid,
        "transcript_version": data.get("transcript_version"),
        "provider_status": status,
        "transcript_complete": complete,
        "speakers": speaker_meta,
        "unresolved_speakers": [
            s["label"] for s in speaker_meta
            if float(s.get("confidence") or 0) < ACTOR_PROMOTE_THRESHOLD
        ],
        **corr,
    }
    artifacts = correlation_artifact_refs(corr)
    if data.get("recording_id"):
        artifacts.append({
            "kind": "recording",
            "external_id": data["recording_id"],
            "download_status": "metadata_only",
        })

    records: list[ConnectorRecord] = []

    # --- meeting_manifest (lightweight index) ---
    chunk_plan = _chunk_segments(segments)
    chunk_count = len(chunk_plan) if segments else 0
    m_trust, m_kind = trust_for_meeting("meeting_manifest", data)
    manifest_body = "\n".join([
        f"# {title}",
        f"When: {data.get('started_at') or '?'}",
        f"Status: {status}",
        f"Complete: {complete}",
        f"Segments: {len(segments)}",
        f"Chunks: {chunk_count}",
        f"Participants: {', '.join(participants[:30])}",
    ])
    records.append(ConnectorRecord(
        connector_id=connector_id,
        source_account_id=account_id,
        external_type="meeting_manifest",
        external_id=f"{mid}:manifest",
        external_revision=f"{seg_rev}.manifest",
        idempotency_key=idempotency_key(
            provider, account_id, "meeting_manifest", f"{mid}:manifest",
            f"{seg_rev}.manifest",
        ),
        occurred_at=data.get("started_at") or data.get("date"),
        actor_ids=[],
        participant_ids=list(participants),
        thread_key=tkey,
        artifact_refs=[
            {"kind": "meeting_manifest", "meeting_id": mid,
             "chunk_count": chunk_count},
        ] + artifacts,
        content=manifest_body,
        source_metadata={
            **common_meta,
            "evidence_role": "index",
            "author_kind": m_kind,
            "chunk_count": chunk_count,
            "segment_count": len(segments),
        },
        confidentiality={"source_trust": m_trust},
    ))

    prev = previous or {}
    prev_chunk_count = int(prev.get("chunk_count") or 0)
    prev_had_summary = bool(prev.get("had_summary"))

    def _emit_chunk_tombstones(from_index: int) -> None:
        for index in range(from_index, prev_chunk_count):
            cid = f"{mid}:chunk:{index}"
            records.append(_tombstone(
                connector_id=connector_id,
                account_id=account_id,
                external_type="meeting_transcript_chunk",
                external_id=cid,
                revision=f"{seg_rev}.chunk{index}.deleted",
                provider=provider,
                thread_key=tkey,
                meeting_id=mid,
                content=f"Meeting chunk removed {cid}",
            ))

    # Incomplete / empty → manifest only (no faux-primary empty transcript),
    # but still retire previously published structural artifacts.
    if not complete and not segments:
        _emit_chunk_tombstones(0)
        if prev_had_summary and status == "failed":
            records.append(_tombstone(
                connector_id=connector_id,
                account_id=account_id,
                external_type="meeting_summary",
                external_id=f"{mid}:summary",
                revision=f"{seg_rev}.summary.deleted",
                provider=provider,
                thread_key=tkey,
                meeting_id=mid,
                content=f"Meeting summary removed {mid}",
            ))
        return records

    # --- transcript chunks (primary evidence; never silently drop segments) ---
    trust, kind = trust_for_meeting("meeting_transcript_chunk", data)
    for chunk_index, chunk_segs in enumerate(chunk_plan):
        if not chunk_segs and chunk_count == 0:
            continue
        seg_start = chunk_segs[0].get("index", 0) if chunk_segs else 0
        seg_end = chunk_segs[-1].get("index", 0) if chunk_segs else 0
        lines = [f"# {title} (chunk {chunk_index})"]
        for seg in chunk_segs:
            lines.append(
                f"{seg.get('speaker_label') or '?'}: {seg.get('text') or ''}"
            )
        body = "\n".join(lines)
        chunk_hash = content_hash_segments(chunk_segs)
        chunk_id = f"{mid}:chunk:{chunk_index}"
        # Chunk revision ignores summary so summary-only edits do not fork chunks.
        chunk_rev = f"{seg_rev}.chunk{chunk_index}.{chunk_hash}"
        records.append(ConnectorRecord(
            connector_id=connector_id,
            source_account_id=account_id,
            external_type="meeting_transcript_chunk",
            external_id=chunk_id,
            external_revision=chunk_rev,
            idempotency_key=idempotency_key(
                provider, account_id, "meeting_transcript_chunk",
                chunk_id, chunk_rev,
            ),
            occurred_at=data.get("started_at") or data.get("date"),
            actor_ids=list(actors),
            participant_ids=list(participants),
            thread_key=tkey,
            artifact_refs=[
                {"kind": "meeting_transcript_chunk", "meeting_id": mid,
                 "chunk_index": chunk_index},
                {"kind": "derived_from", "external_id": mid},
            ] + artifacts,
            content=body,
            source_metadata={
                **common_meta,
                "evidence_role": "primary" if complete else "operational",
                "author_kind": kind,
                "chunk_index": chunk_index,
                "segment_start": seg_start,
                "segment_end": seg_end,
                "chunk_content_hash": chunk_hash,
            },
            confidentiality={"source_trust": trust},
        ))

    # Structural shrink: retire chunk ids that no longer exist.
    if prev_chunk_count > chunk_count:
        _emit_chunk_tombstones(chunk_count)

    summary = data.get("provider_summary")
    if summary and complete:
        s_trust, s_kind = trust_for_meeting("meeting_summary", data)
        s_id = f"{mid}:summary"
        s_rev = revision_for_summary(data, str(summary))
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
            participant_ids=list(participants),
            thread_key=tkey,
            artifact_refs=[
                {"kind": "meeting_summary", "meeting_id": mid},
                {"kind": "derived_from", "external_id": mid},
            ],
            content=f"[provider summary] {title}\n\n{summary}",
            source_metadata={
                **common_meta,
                "evidence_role": "derived",
                "derived": "provider_summary",
                "author_kind": s_kind,
            },
            confidentiality={"source_trust": s_trust},
        ))
    elif complete and prev_had_summary and not summary:
        # Final revision dropped the summary — retire prior derived evidence.
        records.append(_tombstone(
            connector_id=connector_id,
            account_id=account_id,
            external_type="meeting_summary",
            external_id=f"{mid}:summary",
            revision=f"{seg_rev}.summary.deleted",
            provider=provider,
            thread_key=tkey,
            meeting_id=mid,
            content=f"Meeting summary removed {mid}",
        ))
    return records
