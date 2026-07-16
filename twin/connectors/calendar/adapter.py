"""CalendarConnector — read-only calendar adapter (v0.6 Phase 5).

Streams (explicit allowlist only):

    calendar:{calendar_id}

Continuous sync uses ``updated`` watermark + lookback. Cancelled events
become tombstones. Free/busy detail level is honored when configured.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

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
from . import normalize as cal_norm
from .client import CALENDAR_API, CalendarClient

DEFAULT_LOOKBACK_SECONDS = 86400
DEFAULT_MAX_PAGES = 5


def _parse_stream(stream: str) -> str:
    parts = stream.split(":", 1)
    if len(parts) != 2 or parts[0] != "calendar" or not parts[1]:
        raise ConnectorError(
            f"unknown calendar stream layout: {stream!r}",
            failure_class=FailureClass.schema_change,
        )
    return parts[1]


def _iso_minus_seconds(iso_ts: Optional[str], seconds: int) -> Optional[str]:
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


@register_adapter
class CalendarConnector:
    connector_type = "calendar"

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
        self.calendars: list[str] = list(cfg.get("calendars") or [])
        self.lookback_seconds = int(cfg.get("lookback_seconds",
                                            DEFAULT_LOOKBACK_SECONDS))
        self.backfill_since: Optional[str] = cfg.get("backfill_since")
        self.max_pages = int(cfg.get("max_pages_per_stream", DEFAULT_MAX_PAGES))
        self.api_base_url: str = cfg.get("api_base_url", CALENDAR_API)
        self.freebusy_only: bool = bool(cfg.get("freebusy_only", False))
        self._client: Optional[CalendarClient] = None
        self._account_email: Optional[str] = cfg.get("account_email")
        self._store = None

    @property
    def client(self) -> CalendarClient:
        if self._client is None:
            self._client = CalendarClient(self.secret, base_url=self.api_base_url)
        return self._client

    @staticmethod
    def adapter_manifest() -> AdapterManifest:
        return AdapterManifest(
            connector_type="calendar",
            adapter_version="1.0",
            schema_version=1,
            auth_mode="oauth2",
            affordances={
                "incremental_sync": True,
                "webhooks": False,
                "deletions": True,
                "attachments": False,
                "threads": False,
            },
            supported_external_types=["calendar_event"],
            streams=[],
            dynamic_streams=True,
            default_scopes=[
                "https://www.googleapis.com/auth/calendar.readonly",
            ],
        )

    def discover_accounts(self) -> list[SourceAccount]:
        return [self.account]

    def list_calendars(self) -> list[dict[str, Any]]:
        out = []
        for cal in self.client.list_calendars():
            out.append({
                "id": cal.get("id"),
                "summary": cal.get("summary") or cal.get("id"),
                "primary": bool(cal.get("primary")),
                "access_role": cal.get("accessRole"),
            })
        return out

    def validate_credentials(self) -> ConnectorHealth:
        if not self.secret:
            return ConnectorHealth(status=HealthStatus.unauthorized,
                                   detail="no credential configured")
        try:
            cals = self.client.list_calendars()
        except ConnectorError as exc:
            if exc.failure_class in (FailureClass.authentication,
                                     FailureClass.authorization):
                return ConnectorHealth(status=HealthStatus.unauthorized,
                                       detail="token rejected by calendar")
            return ConnectorHealth(
                status=HealthStatus.degraded,
                detail=f"calendar unreachable: {exc.failure_class.value}",
            )
        return ConnectorHealth(
            status=HealthStatus.healthy,
            detail=(f"authenticated; {len(cals)} calendars visible; "
                    "read-only calendar.readonly"),
        )

    def plan_streams(self, account: SourceAccount) -> list[str]:
        return [f"calendar:{cid}" for cid in self.calendars]

    def plan_sync(
        self,
        account: SourceAccount,
        checkpoint: Optional[ConnectorCheckpoint],
        *,
        stream: str,
    ) -> SyncPlan:
        if not self.calendars:
            raise ConnectorError(
                "no calendars configured",
                failure_class=FailureClass.configuration,
                human_action_required=True,
            )
        cal_id = _parse_stream(stream)
        return SyncPlan(
            stream=stream,
            cursor_before=dict(checkpoint.cursor) if checkpoint else {},
            lookback_seconds=self.lookback_seconds,
            metadata={"calendar_id": cal_id},
        )

    def _updated_min(self, cursor: Optional[dict[str, Any]]) -> Optional[str]:
        watermark = (cursor or {}).get("watermark")
        if watermark:
            return _iso_minus_seconds(str(watermark), self.lookback_seconds)
        return self.backfill_since

    def fetch_batch(
        self, plan: SyncPlan, cursor: Optional[dict[str, Any]],
    ) -> FetchPage:
        cal_id = plan.metadata["calendar_id"]
        base = dict(cursor or plan.cursor_before or {})
        page_token = (base.get("progress") or {}).get("page_token")
        updated_min = None if page_token else self._updated_min(base)
        events, next_token = self.client.list_events(
            cal_id, updated_min=updated_min, page_token=page_token,
            max_results=50, show_deleted=True,
        )
        items: list[RawFetchItem] = []
        window_max = base.get("window_max_seen") or base.get("watermark")
        for ev in events:
            if self.freebusy_only:
                ev = dict(ev)
                ev["freebusy_only"] = True
            items.append(self._raw_from_event(ev, cal_id))
            updated = ev.get("updated")
            if updated and (not window_max or str(updated) > str(window_max)):
                window_max = updated

        if next_token:
            after = {
                "watermark": base.get("watermark"),
                "window_max_seen": window_max,
                "progress": {"page_token": next_token},
            }
            return FetchPage(raw_items=items, cursor_after=after, done=False)
        after = {"watermark": window_max or base.get("watermark")}
        return FetchPage(raw_items=items, cursor_after=after, done=True)

    def _raw_from_event(self, event: dict[str, Any], calendar_id: str) -> RawFetchItem:
        eid = str(event.get("id") or "?")
        status = str(event.get("status") or "").lower()
        deleted = status == "cancelled" or bool(event.get("deleted"))
        return RawFetchItem(
            external_type="calendar_event",
            external_id=eid,
            external_revision=(
                f"{eid}.deleted" if deleted
                else cal_norm.revision_for_event(event)
            ),
            payload={
                "provider": "google_calendar",
                "calendar_id": calendar_id,
                "account_email": self._account_email
                or self.account.external_account_id or "me",
                "object": event,
            },
            occurred_at=cal_norm._start_iso(event),
            deleted=deleted,
        )

    def normalize(self, raw_item: RawConnectorItem) -> list[ConnectorRecord]:
        payload = raw_item.payload or {}
        obj = payload.get("object")
        if not isinstance(obj, dict):
            raise ConnectorError(
                "calendar raw item missing object envelope",
                failure_class=FailureClass.schema_change,
                external_id=raw_item.external_id,
                external_type=raw_item.external_type,
            )
        account_key = payload.get("account_email") or "me"
        calendar_id = payload.get("calendar_id") or "primary"
        if raw_item.deleted or str(obj.get("status") or "").lower() == "cancelled":
            return [ConnectorRecord(
                connector_id=raw_item.connector_id,
                source_account_id=raw_item.source_account_id,
                external_type="calendar_event",
                external_id=raw_item.external_id,
                external_revision=raw_item.external_revision,
                content=f"Calendar event cancelled {raw_item.external_id}",
                deleted=True,
                source_metadata={"provider": "google_calendar", "deleted": True,
                                 "calendar_id": calendar_id},
                confidentiality={"source_trust": 0.40},
            )]
        rec = cal_norm.record_from_event(
            connector_id=raw_item.connector_id,
            account_id=raw_item.source_account_id,
            provider="google_calendar",
            account_key=str(account_key),
            calendar_id=str(calendar_id),
            event=obj,
        )
        rec.external_id = raw_item.external_id
        rec.external_revision = raw_item.external_revision
        return [rec]

    def acknowledge(self, plan: SyncPlan, page: FetchPage) -> dict[str, Any]:
        return page.cursor_after or dict(plan.cursor_before or {})
