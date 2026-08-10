"""FirefliesConnector — GraphQL meeting transcripts via MeetingRecord.

Stream:

 meetings

Discovery uses ``transcripts(fromDate)`` which filters by *creation* time.
Incomplete transcripts are kept in ``pending_transcripts`` and re-fetched by
ID until terminal. Recent completes are periodically reconciled for late
edits (summary / sentences).

Deletion feed: not offered by provider (``deletions=false``). Structural
chunk/summary shrinks emit tombstones from the meeting normalizer.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..meeting.model import MeetingRecord, TranscriptSegment
from ..meeting.normalize import records_from_meeting, revision_for_meeting
from ..meeting.speakers import attach_speaker_ids, map_speakers
from ..models import (
    ConnectorCheckpoint,
    ConnectorInstance,
    ConnectorRecord,
    FailureClass,
    HealthStatus,
    RawConnectorItem,
    SourceAccount,
)
from ..protocol import (
    AdapterManifest,
    ConnectorError,
    ConnectorHealth,
    FetchPage,
    RawFetchItem,
    SyncPlan,
)
from ..registry import register_adapter
from . import sync_state as ss
from .client import FIREFLIES_API, FirefliesClient

DEFAULT_LOOKBACK_SECONDS = 86400
STREAM = "meetings"


def _iso_minus_seconds(iso_ts: Optional[str], seconds: int) -> Optional[str]:
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _date_to_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ms = float(value)
        if ms > 1e12:
            ms = ms / 1000.0
        return datetime.fromtimestamp(ms, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    text = str(value)
    if text.isdigit():
        return _date_to_iso(int(text))
    return text


def _summary_text(summary: Any) -> Optional[str]:
    if summary is None:
        return None
    if isinstance(summary, str):
        return summary
    if isinstance(summary, dict):
        for key in (
            "overview", "short_summary", "short_overview", "gist",
            "shorthand_bullet", "action_items",
        ):
            val = summary.get(key)
            if isinstance(val, str) and val.strip():
                return val
            if isinstance(val, list) and val:
                return "\n".join(str(x) for x in val)
    return None


def _infer_status(payload: dict[str, Any], segments: list) -> tuple[str, bool]:
    if payload.get("is_live"):
        return "live", False
    info = payload.get("meeting_info") or {}
    summary_status = str(
        info.get("summary_status") or payload.get("summary_status") or ""
    ).lower()
    if summary_status in ("processing", "pending", "in_progress"):
        return "processing", False
    if summary_status in ("failed", "error"):
        return "failed", False
    if not segments and summary_status in ("", "none", "null"):
        if payload.get("sentences") is None:
            return "processing", False
        return "partial", False
    if summary_status in ("processed", "complete", "done", "completed"):
        return "complete", True
    if segments:
        return "complete", True
    return "partial", False


def meeting_from_fireflies(
    payload: dict[str, Any], *, account_key: str = "me",
) -> MeetingRecord:
    """Normalize a Fireflies GraphQL transcript into MeetingRecord."""
    sentences = payload.get("sentences") or []
    segments: list[TranscriptSegment] = []
    labels: list[str] = []
    if isinstance(sentences, list):
        for i, s in enumerate(sentences):
            if not isinstance(s, dict):
                continue
            label = (
                s.get("speaker_name") or s.get("speaker") or s.get("name") or "?"
            )
            labels.append(str(label))
            start = s.get("start_time") if s.get("start_time") is not None else s.get("start_ms")
            end = s.get("end_time") if s.get("end_time") is not None else s.get("end_ms")
            if isinstance(start, float) and start < 1e6:
                start = int(start * 1000)
            if isinstance(end, float) and end < 1e6:
                end = int(end * 1000)
            segments.append(TranscriptSegment(
                index=int(s["index"]) if s.get("index") is not None else i,
                speaker_label=str(label),
                text=str(s.get("text") or s.get("raw_text") or ""),
                start_ms=start,
                end_ms=end,
            ))

    attendees = payload.get("meeting_attendees") or []
    participants = payload.get("participants") or []
    combined: list[Any] = list(attendees)
    for p in participants:
        combined.append(p)

    speaker_map: dict[str, dict[str, Any]] = {}
    for sp in payload.get("speakers") or []:
        if not isinstance(sp, dict):
            continue
        name = sp.get("name")
        if name:
            speaker_map[str(name)] = sp
        sid = sp.get("id")
        if sid:
            speaker_map[str(sid)] = sp

    for s in sentences if isinstance(sentences, list) else []:
        if not isinstance(s, dict):
            continue
        sid = s.get("speaker_id")
        sname = s.get("speaker_name")
        if sid and sname and str(sname) not in speaker_map:
            speaker_map[str(sname)] = {"id": sid, "name": sname}

    mid = str(payload.get("id") or payload.get("transcript_id") or "?")
    status, complete = _infer_status(payload, segments)
    summary = _summary_text(payload.get("summary"))
    started = _date_to_iso(
        payload.get("date") or payload.get("dateString")
        or payload.get("start_time")
    )

    media_present = [
        k for k in ("audio_url", "video_url", "transcript_url")
        if payload.get(k)
    ]

    meeting = MeetingRecord(
        provider="fireflies",
        external_id=mid,
        title=payload.get("title") or payload.get("meeting_title") or "(untitled)",
        started_at=started,
        ended_at=_date_to_iso(payload.get("end_time")),
        duration_seconds=payload.get("duration") or payload.get("duration_seconds"),
        participants=[
            (p.get("email") or p.get("name") or p.get("displayName")
             if isinstance(p, dict) else str(p))
            for p in combined
        ],
        organizer=(payload.get("organizer_email") or payload.get("host_email")),
        segments=segments,
        provider_summary=summary,
        transcript_version=str(
            payload.get("transcript_version")
            or payload.get("date")
            or started
            or "1"
        ),
        calendar_event_id=(
            payload.get("calendar_event_id")
            or payload.get("cal_id")
            or payload.get("calendar_id")
        ),
        calendar_iCalUID=payload.get("ical_uid") or payload.get("iCalUID"),
        conference_url=payload.get("meeting_link") or payload.get("conference_url"),
        recording_id=mid if media_present else None,
        host_email=payload.get("host_email"),
        provider_status=status,
        transcript_complete=complete,
        raw_metadata={
            "fireflies_keys": sorted(payload.keys())[:40],
            "media_urls_present": media_present,
            # Intentionally omit signed media URLs from persisted payloads.
            "summary_status": (payload.get("meeting_info") or {}).get(
                "summary_status"),
            "is_live": bool(payload.get("is_live")),
            "deletion_policy": "retain_until_offboarding",
        },
    )
    speakers = map_speakers(
        provider="fireflies",
        account_key=account_key,
        meeting_id=mid,
        segment_labels=labels,
        participants=combined,
        organizer_email=meeting.organizer,
        host_email=meeting.host_email,
        provider_speaker_map=speaker_map,
    )
    return attach_speaker_ids(meeting, speakers)


@register_adapter
class FirefliesConnector:
    connector_type = "fireflies"

    def __init__(
        self,
        instance: ConnectorInstance,
        account: SourceAccount,
        secret: Optional[str],
    ) -> None:
        self.instance = instance
        self.account = account
        self.secret = secret
        cfg = instance.configuration or {}
        self.lookback_seconds = int(cfg.get("lookback_seconds",
                                            DEFAULT_LOOKBACK_SECONDS))
        self.backfill_since: Optional[str] = cfg.get("backfill_since")
        self.max_pages = int(cfg.get("max_pages_per_stream", 5))
        self.api_base_url: str = cfg.get("api_base_url", FIREFLIES_API)
        self.page_overlap = int(cfg.get("page_overlap", ss.DEFAULT_PAGE_OVERLAP))
        self.reconcile_days = int(cfg.get("reconcile_days", ss.DEFAULT_RECONCILE_DAYS))
        self.reconcile_interval_seconds = int(
            cfg.get("reconcile_interval_seconds", 3600))
        self.max_known = int(cfg.get("max_known_transcripts", ss.DEFAULT_MAX_KNOWN))
        self._client: Optional[FirefliesClient] = None
        self._account_email: Optional[str] = cfg.get("account_email")
        self._store = None

    @property
    def client(self) -> FirefliesClient:
        if self._client is None:
            self._client = FirefliesClient(self.secret, base_url=self.api_base_url)
        return self._client

    @staticmethod
    def adapter_manifest() -> AdapterManifest:
        return AdapterManifest(
            connector_type="fireflies",
            adapter_version="1.2",
            schema_version=1,
            auth_mode="api_key",
            affordances={
                "incremental_sync": True,
                "webhooks": False,
                "deletions": False,
                "attachments": False,
                "threads": True,
            },
            supported_external_types=[
                "meeting_manifest",
                "meeting_transcript_chunk",
                "meeting_summary",
            ],
            streams=[STREAM],
            dynamic_streams=False,
            default_scopes=["transcripts:read"],
        )

    def discover_accounts(self) -> list[SourceAccount]:
        return [self.account]

    def list_meetings(self, *, limit: int = 20) -> list[dict[str, Any]]:
        stubs, _ = self.client.list_transcripts(limit=min(limit, 50), skip=0)
        out = []
        for s in stubs:
            out.append({
                "id": s.get("id"),
                "title": s.get("title"),
                "date": _date_to_iso(s.get("date")),
                "duration": s.get("duration"),
                "status": (s.get("meeting_info") or {}).get("summary_status"),
                "is_live": s.get("is_live"),
            })
        return out

    def validate_credentials(self) -> ConnectorHealth:
        if not self.secret:
            return ConnectorHealth(status=HealthStatus.unauthorized,
                                   detail="no credential configured")
        try:
            me = self.client.me()
        except ConnectorError as exc:
            if exc.failure_class in (FailureClass.authentication,
                                     FailureClass.authorization):
                return ConnectorHealth(status=HealthStatus.unauthorized,
                                       detail="token rejected by fireflies")
            return ConnectorHealth(
                status=HealthStatus.degraded,
                detail=f"fireflies unreachable: {exc.failure_class.value}",
            )
        email = me.get("email") or me.get("name") or "?"
        self._account_email = me.get("email") or self._account_email
        return ConnectorHealth(
            status=HealthStatus.healthy,
            detail=(
                f"authenticated as {email}; GraphQL read-only transcripts; "
                "creation_watermark + pending_transcripts for updates"
            ),
        )

    def plan_streams(self, account: SourceAccount) -> list[str]:
        return [STREAM]

    def plan_sync(
        self,
        account: SourceAccount,
        checkpoint: Optional[ConnectorCheckpoint],
        *,
        stream: str,
    ) -> SyncPlan:
        if stream != STREAM:
            raise ConnectorError(
                f"unknown fireflies stream: {stream!r}",
                failure_class=FailureClass.schema_change,
            )
        return SyncPlan(
            stream=stream,
            cursor_before=dict(checkpoint.cursor) if checkpoint else {},
            lookback_seconds=self.lookback_seconds,
            metadata={},
        )

    def _creation_from_date(self, cursor: dict[str, Any]) -> Optional[str]:
        wm = ss.creation_watermark(cursor)
        if wm:
            return _iso_minus_seconds(str(wm), self.lookback_seconds)
        return self.backfill_since

    def _account_key(self) -> str:
        return self._account_email or self.account.external_account_id or "me"

    def _raw_from_meeting(self, meeting: MeetingRecord) -> RawFetchItem:
        obj = meeting.to_dict()
        # Defense in depth: never persist signed URLs on the raw object.
        meta = obj.get("raw_metadata")
        if isinstance(meta, dict):
            meta = dict(meta)
            meta.pop("media_urls", None)
            obj["raw_metadata"] = meta
        return RawFetchItem(
            external_type="meeting_transcript",
            external_id=meeting.external_id,
            external_revision=revision_for_meeting(obj),
            payload={
                "provider": "fireflies",
                "account_email": self._account_key(),
                "object": obj,
            },
            occurred_at=meeting.started_at,
        )

    def _fetch_one(
        self, tid: str, *, seen_ids: set[str], items: list[RawFetchItem],
        pending: dict[str, dict[str, Any]], known: dict[str, dict[str, Any]],
        cursor: dict[str, Any],
    ) -> None:
        if tid in seen_ids:
            return
        full = self.client.get_transcript(str(tid))
        seen_ids.add(tid)
        if full is None:
            # Provider no longer returns it — drop pending; retain known.
            pending.pop(tid, None)
            return
        meeting = meeting_from_fireflies(full, account_key=self._account_key())
        items.append(self._raw_from_meeting(meeting))
        ss.note_transcript(
            pending, known,
            tid=meeting.external_id,
            status=meeting.provider_status or "unknown",
            started_at=meeting.started_at,
            max_known=self.max_known,
        )
        ss.bump_creation_seen(cursor, meeting.started_at)

    def fetch_batch(
        self, plan: SyncPlan, cursor: Optional[dict[str, Any]],
    ) -> FetchPage:
        base = dict(cursor or plan.cursor_before or {})
        progress = dict(base.get("progress") or {})
        pending = ss.pending_map(base)
        known = ss.known_map(base)
        seen_ids: set[str] = set()
        items: list[RawFetchItem] = []
        pages_done = int(progress.get("pages_done") or 0)
        phase = progress.get("phase") or "pending"

        # re-fetch incomplete transcripts by ID (independent of fromDate).
        if phase == "pending":
            pending_ids = list(pending.keys())
            start_idx = int(progress.get("pending_idx") or 0)
            for offset, tid in enumerate(pending_ids[start_idx:]):
                if pages_done >= self.max_pages:
                    after = self._cursor_after(
                        base, pending, known, progress={
                            "phase": "pending",
                            "pages_done": 0,
                            "pending_idx": start_idx + offset,
                        },
                        promote=False,
                    )
                    return FetchPage(
                        raw_items=items, cursor_after=after, done=False,
                    )
                self._fetch_one(
                    tid, seen_ids=seen_ids, items=items,
                    pending=pending, known=known, cursor=base,
                )
                pages_done += 1
            phase = "discover"
            pages_done = 0
            progress = {}

        # discover newly *created* meetings via fromDate.
        if phase == "discover":
            skip = int(progress.get("skip") or 0)
            from_date = (
                base.get("_from_date") if skip
                else self._creation_from_date(base)
            )
            stubs, _next = self.client.list_transcripts(
                from_date=from_date, skip=skip, limit=50,
            )
            pages_done += 1
            for stub in stubs:
                tid = stub.get("id")
                if not tid:
                    continue
                self._fetch_one(
                    str(tid), seen_ids=seen_ids, items=items,
                    pending=pending, known=known, cursor=base,
                )
            next_skip = ss.next_skip_with_overlap(
                skip, len(stubs), overlap=self.page_overlap, limit=50,
            )
            if next_skip is not None and pages_done < self.max_pages:
                after = self._cursor_after(
                    base, pending, known,
                    progress={
                        "phase": "discover",
                        "skip": next_skip,
                        "pages_done": pages_done,
                    },
                    from_date=from_date,
                    promote=False,
                )
                return FetchPage(raw_items=items, cursor_after=after, done=False)
            if next_skip is not None:
                after = self._cursor_after(
                    base, pending, known,
                    progress={
                        "phase": "discover",
                        "skip": next_skip,
                        "pages_done": 0,
                    },
                    from_date=from_date,
                    promote=False,
                )
                return FetchPage(raw_items=items, cursor_after=after, done=False)
            # End of discover window — optional reconcile of recent completes.
            phase = "reconcile"
            pages_done = 0

        # re-fetch recent known completes for late summary/sentence edits.
        if phase == "reconcile":
            if ss.reconcile_due(
                base, interval_seconds=self.reconcile_interval_seconds,
            ):
                candidates = ss.reconcile_candidates(
                    known, pending,
                    reconcile_days=self.reconcile_days,
                    limit=min(40, max(1, self.max_pages * 10)),
                )
                start_idx = int(progress.get("reconcile_idx") or 0)
                for tid in candidates[start_idx:]:
                    if pages_done >= self.max_pages:
                        after = self._cursor_after(
                            base, pending, known,
                            progress={
                                "phase": "reconcile",
                                "pages_done": 0,
                                "reconcile_idx": candidates.index(tid),
                            },
                            promote=False,
                        )
                        return FetchPage(
                            raw_items=items, cursor_after=after, done=False,
                        )
                    self._fetch_one(
                        tid, seen_ids=seen_ids, items=items,
                        pending=pending, known=known, cursor=base,
                    )
                    pages_done += 1
                base["last_reconciliation_at"] = (
                    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                )

        after = self._cursor_after(
            base, pending, known, progress={}, promote=True,
        )
        return FetchPage(raw_items=items, cursor_after=after, done=True)

    def _cursor_after(
        self,
        base: dict[str, Any],
        pending: dict[str, dict[str, Any]],
        known: dict[str, dict[str, Any]],
        *,
        progress: dict[str, Any],
        from_date: Optional[str] = None,
        promote: bool,
    ) -> dict[str, Any]:
        after = {
            "creation_watermark": ss.creation_watermark(base),
            "window_max_seen": base.get("window_max_seen"),
            "pending_transcripts": pending,
            "known_transcripts": known,
            "last_reconciliation_at": base.get("last_reconciliation_at"),
            "progress": progress,
        }
        if from_date is not None:
            after["_from_date"] = from_date
        if promote:
            return ss.promote_creation_watermark(after)
        return after

    def _previous_meeting_state(self, meeting_id: str) -> dict[str, Any]:
        if self._store is None:
            return {}
        manifests = self._store.list_connector_records_for_object(
            self.instance.id, "meeting_manifest", f"{meeting_id}:manifest",
        )
        live_manifests = [m for m in manifests if not m.deleted]
        chunk_count = 0
        if live_manifests:
            chunk_count = int(
                (live_manifests[-1].source_metadata or {}).get("chunk_count") or 0
            )
        summaries = self._store.list_connector_records_for_object(
            self.instance.id, "meeting_summary", f"{meeting_id}:summary",
        )
        had_summary = any(not s.deleted for s in summaries)
        return {"chunk_count": chunk_count, "had_summary": had_summary}

    def normalize(self, raw_item: RawConnectorItem) -> list[ConnectorRecord]:
        payload = raw_item.payload or {}
        obj = payload.get("object")
        if not isinstance(obj, dict):
            raise ConnectorError(
                "fireflies raw item missing object envelope",
                failure_class=FailureClass.schema_change,
                external_id=raw_item.external_id,
                external_type=raw_item.external_type,
            )
        account_key = payload.get("account_email") or "me"
        mid = str(obj.get("external_id") or raw_item.external_id)
        return records_from_meeting(
            connector_id=raw_item.connector_id,
            account_id=raw_item.source_account_id,
            account_key=str(account_key),
            meeting=obj,
            previous=self._previous_meeting_state(mid),
        )

    def acknowledge(self, plan: SyncPlan, page: FetchPage) -> dict[str, Any]:
        return page.cursor_after or dict(plan.cursor_before or {})
