"""FirefliesConnector — meeting transcripts via shared MeetingRecord model.

Stream:

    meetings

Transcript is primary evidence; provider summary is derived. Speakers are
mapped with explicit confidence. Calendar correlation lives in metadata /
artifact_refs (fingerprint, calendar_event_id, conference URL).
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
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def meeting_from_fireflies(payload: dict[str, Any]) -> MeetingRecord:
    """Normalize a Fireflies-shaped transcript into MeetingRecord."""
    sentences = payload.get("sentences") or payload.get("transcript") or []
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
            segments.append(TranscriptSegment(
                index=i,
                speaker_label=str(label),
                text=str(s.get("text") or s.get("sentence") or ""),
                start_ms=s.get("start_time") or s.get("start_ms"),
                end_ms=s.get("end_time") or s.get("end_ms"),
            ))
    participants = payload.get("participants") or payload.get("attendees") or []
    speaker_map = {}
    for sp in payload.get("speakers") or []:
        if isinstance(sp, dict) and sp.get("name"):
            speaker_map[str(sp["name"])] = sp

    meeting = MeetingRecord(
        provider="fireflies",
        external_id=str(payload.get("id") or payload.get("transcript_id") or "?"),
        title=payload.get("title") or payload.get("meeting_title") or "(untitled)",
        started_at=(
            payload.get("date") or payload.get("start_time")
            or payload.get("scheduled_start")
        ),
        ended_at=payload.get("end_time"),
        duration_seconds=payload.get("duration") or payload.get("duration_seconds"),
        participants=[
            (p.get("email") or p.get("name") if isinstance(p, dict) else str(p))
            for p in participants
        ],
        organizer=(payload.get("organizer_email") or payload.get("host_email")),
        segments=segments,
        provider_summary=payload.get("summary") or payload.get("short_summary"),
        transcript_version=str(
            payload.get("transcript_version")
            or payload.get("updated_at")
            or payload.get("date")
            or "1"
        ),
        calendar_event_id=payload.get("calendar_event_id") or payload.get(
            "calendar_id"),
        calendar_iCalUID=payload.get("ical_uid") or payload.get("iCalUID"),
        conference_url=payload.get("meeting_link") or payload.get("conference_url"),
        recording_ref=payload.get("audio_url") or payload.get("video_url"),
        host_email=payload.get("host_email"),
        raw_metadata={"fireflies_keys": sorted(payload.keys())[:40]},
    )
    speakers = map_speakers(
        provider="fireflies",
        segment_labels=labels,
        participants=participants,
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
            adapter_version="1.0",
            schema_version=1,
            auth_mode="oauth2",
            affordances={
                "incremental_sync": True,
                "webhooks": False,
                "deletions": False,
                "attachments": False,
                "threads": True,
            },
            supported_external_types=[
                "meeting_transcript", "meeting_summary",
            ],
            streams=[STREAM],
            dynamic_streams=False,
            default_scopes=["transcripts:read"],
        )

    def discover_accounts(self) -> list[SourceAccount]:
        return [self.account]

    def list_meetings(self, *, limit: int = 20) -> list[dict[str, Any]]:
        stubs, _ = self.client.list_transcripts(limit=limit)
        out = []
        for s in stubs:
            out.append({
                "id": s.get("id"),
                "title": s.get("title"),
                "date": s.get("date") or s.get("start_time"),
                "duration": s.get("duration"),
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
            detail=f"authenticated as {email}; read-only transcripts",
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

    def _updated_since(self, cursor: Optional[dict[str, Any]]) -> Optional[str]:
        watermark = (cursor or {}).get("watermark")
        if watermark:
            return _iso_minus_seconds(str(watermark), self.lookback_seconds)
        return self.backfill_since

    def fetch_batch(
        self, plan: SyncPlan, cursor: Optional[dict[str, Any]],
    ) -> FetchPage:
        base = dict(cursor or plan.cursor_before or {})
        page_token = (base.get("progress") or {}).get("page_token")
        since = None if page_token else self._updated_since(base)
        stubs, next_token = self.client.list_transcripts(
            updated_since=since, page_token=page_token, limit=50,
        )
        items: list[RawFetchItem] = []
        window_max = base.get("window_max_seen") or base.get("watermark")
        for stub in stubs:
            tid = stub.get("id")
            if not tid:
                continue
            full = self.client.get_transcript(str(tid)) or stub
            meeting = meeting_from_fireflies(full)
            obj = meeting.to_dict()
            items.append(RawFetchItem(
                external_type="meeting_transcript",
                external_id=meeting.external_id,
                external_revision=revision_for_meeting(obj),
                payload={
                    "provider": "fireflies",
                    "account_email": self._account_email
                    or self.account.external_account_id or "me",
                    "object": obj,
                },
                occurred_at=meeting.started_at,
            ))
            stamp = (
                full.get("updated_at") or meeting.started_at
                or full.get("date")
            )
            if stamp and (not window_max or str(stamp) > str(window_max)):
                window_max = stamp

        if next_token:
            after = {
                "watermark": base.get("watermark"),
                "window_max_seen": window_max,
                "progress": {"page_token": next_token},
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
