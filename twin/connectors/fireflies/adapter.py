"""FirefliesConnector — GraphQL meeting transcripts via MeetingRecord.

Stream:

    meetings

Transcript is primary evidence (chunked); provider summary is derived.
Speakers are account-scoped with explicit confidence. Calendar correlation
lives in metadata / artifact_refs.

Deletion/reconciliation: Fireflies GraphQL does not expose a deletion feed.
``deletions=false`` — Twin retains previously ingested transcripts until a
future reconcile/offboarding policy removes them. Documented Phase 5 limit.
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
        # Fireflies often returns epoch ms.
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
    """Return (provider_status, transcript_complete)."""
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
        # Empty sentences — treat as incomplete unless explicitly processed.
        if payload.get("sentences") is None:
            return "processing", False
        return "partial", False
    if summary_status in ("processed", "complete", "done", "completed"):
        return "complete", True
    # Sentences present and not live → treat as complete primary evidence.
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
            # Fireflies start_time is often seconds (float); store as ms int.
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
    # participants may be email strings; attendees are objects.
    combined: list[Any] = list(attendees)
    for p in participants:
        if isinstance(p, str):
            combined.append(p)
        else:
            combined.append(p)

    speaker_map: dict[str, dict[str, Any]] = {}
    for sp in payload.get("speakers") or []:
        if not isinstance(sp, dict):
            continue
        name = sp.get("name")
        if name:
            speaker_map[str(name)] = sp
        # Also index by id for sentence speaker_id joins.
        sid = sp.get("id")
        if sid:
            speaker_map[str(sid)] = sp

    # Enrich speaker_map from sentence speaker_id when name known.
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

    media_urls = {
        k: payload.get(k)
        for k in ("audio_url", "video_url", "transcript_url")
        if payload.get(k)
    }

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
        recording_id=mid if media_urls else None,
        host_email=payload.get("host_email"),
        provider_status=status,
        transcript_complete=complete,
        raw_metadata={
            "fireflies_keys": sorted(payload.keys())[:40],
            "media_urls_present": sorted(media_urls.keys()),
            # URLs may be signed/expiring — never use as stable identity.
            "media_urls": media_urls,
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
            adapter_version="1.1",
            schema_version=1,
            auth_mode="api_key",
            affordances={
                "incremental_sync": True,
                "webhooks": False,
                # No provider deletion feed — see module docstring.
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
            detail=f"authenticated as {email}; GraphQL read-only transcripts",
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

    def _from_date(self, cursor: Optional[dict[str, Any]]) -> Optional[str]:
        watermark = (cursor or {}).get("watermark")
        if watermark:
            return _iso_minus_seconds(str(watermark), self.lookback_seconds)
        return self.backfill_since

    def fetch_batch(
        self, plan: SyncPlan, cursor: Optional[dict[str, Any]],
    ) -> FetchPage:
        base = dict(cursor or plan.cursor_before or {})
        progress = dict(base.get("progress") or {})
        skip = int(progress.get("skip") or 0)
        pages_done = int(progress.get("pages_done") or 0)
        from_date = self._from_date(base) if skip == 0 else base.get("_from_date")
        stubs, next_skip = self.client.list_transcripts(
            from_date=from_date, skip=skip, limit=50,
        )
        pages_done += 1
        account_key = (
            self._account_email or self.account.external_account_id or "me"
        )
        items: list[RawFetchItem] = []
        window_max = base.get("window_max_seen") or base.get("watermark")
        for stub in stubs:
            tid = stub.get("id")
            if not tid:
                continue
            full = self.client.get_transcript(str(tid))
            if full is None:
                continue
            meeting = meeting_from_fireflies(full, account_key=str(account_key))
            obj = meeting.to_dict()
            # Strip signed media URLs from the object persisted as cognition
            # input — keep them only under raw_metadata.media_urls.
            items.append(RawFetchItem(
                external_type="meeting_transcript",
                external_id=meeting.external_id,
                external_revision=revision_for_meeting(obj),
                payload={
                    "provider": "fireflies",
                    "account_email": account_key,
                    "object": obj,
                },
                occurred_at=meeting.started_at,
            ))
            stamp = meeting.started_at or _date_to_iso(full.get("date"))
            if stamp and (not window_max or str(stamp) > str(window_max)):
                window_max = stamp

        budget_exhausted = pages_done >= self.max_pages and next_skip is not None
        if next_skip is not None and not budget_exhausted:
            after = {
                "watermark": base.get("watermark"),
                "window_max_seen": window_max,
                "_from_date": from_date,
                "progress": {"skip": next_skip, "pages_done": pages_done},
            }
            return FetchPage(raw_items=items, cursor_after=after, done=False)
        if budget_exhausted:
            after = {
                "watermark": base.get("watermark"),
                "window_max_seen": window_max,
                "_from_date": from_date,
                "progress": {"skip": next_skip, "pages_done": 0},
            }
            return FetchPage(raw_items=items, cursor_after=after, done=False)
        return FetchPage(
            raw_items=items,
            cursor_after={"watermark": window_max or base.get("watermark")},
            done=True,
        )

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
        return records_from_meeting(
            connector_id=raw_item.connector_id,
            account_id=raw_item.source_account_id,
            account_key=str(account_key),
            meeting=obj,
        )

    def acknowledge(self, plan: SyncPlan, page: FetchPage) -> dict[str, Any]:
        return page.cursor_after or dict(plan.cursor_before or {})
