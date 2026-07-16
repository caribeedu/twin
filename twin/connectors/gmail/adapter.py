"""GmailConnector — read-only Gmail adapter (v0.6 Phase 4).

Streams are dynamic, one per allowlisted label:

    label:{label_id}

Configuration is an EXPLICIT label allowlist — whole-mailbox ingest is
never a default. Continuous sync uses ``internalDate`` watermark +
lookback; historical coverage uses partitionable ``BackfillJob`` windows
(``backfill_since`` / ``backfill_until`` on the instance configuration).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..mail import mime as mail_mime
from ..mail import normalize as mail_norm
from ..mail import sync_state as ss
from ..mail.classification import classify_message
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
from .client import GMAIL_API, GmailClient

DEFAULT_LOOKBACK_SECONDS = 86400
DEFAULT_MAX_PAGES = 5


def _parse_stream(stream: str) -> str:
    parts = stream.split(":", 1)
    if len(parts) != 2 or parts[0] != "label" or not parts[1]:
        raise ConnectorError(
            f"unknown gmail stream layout: {stream!r}",
            failure_class=FailureClass.schema_change,
        )
    return parts[1]


def _header_map(payload: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for h in (payload.get("headers") or []):
        if isinstance(h, dict) and h.get("name"):
            out[h["name"]] = h.get("value") or ""
    return out


def _ms_to_iso(ms: Any) -> Optional[str]:
    try:
        seconds = int(ms) / 1000.0
    except (TypeError, ValueError):
        return None
    return (datetime.fromtimestamp(seconds, tz=timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"))


def _iso_minus_seconds(iso_ts: Optional[str], seconds: int) -> Optional[str]:
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


@register_adapter
class GmailConnector:
    connector_type = "gmail"

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
        self.labels: list[str] = list(cfg.get("labels") or [])
        self.lookback_seconds = int(cfg.get("lookback_seconds",
                                            DEFAULT_LOOKBACK_SECONDS))
        self.backfill_since: Optional[str] = cfg.get("backfill_since")
        self.backfill_until: Optional[str] = cfg.get("backfill_until")
        self.max_pages = int(cfg.get("max_pages_per_stream", DEFAULT_MAX_PAGES))
        self.api_base_url: str = cfg.get("api_base_url", GMAIL_API)
        self.include_spam = bool(cfg.get("include_spam", False))
        self.include_promotions = bool(cfg.get("include_promotions", False))
        self._client: Optional[GmailClient] = None
        self._account_email: Optional[str] = cfg.get("account_email")

    @property
    def client(self) -> GmailClient:
        if self._client is None:
            self._client = GmailClient(self.secret, base_url=self.api_base_url)
        return self._client

    @staticmethod
    def adapter_manifest() -> AdapterManifest:
        return AdapterManifest(
            connector_type="gmail",
            adapter_version="1.0",
            schema_version=1,
            auth_mode="oauth2",
            affordances={
                "incremental_sync": True,
                "webhooks": False,
                "deletions": False,
                "attachments": False,  # metadata refs only
                "threads": True,
            },
            supported_external_types=["message", "thread_message"],
            streams=[],
            dynamic_streams=True,
            default_scopes=[
                "https://www.googleapis.com/auth/gmail.readonly",
            ],
        )

    def discover_accounts(self) -> list[SourceAccount]:
        return [self.account]

    def list_labels(self) -> list[dict[str, Any]]:
        out = []
        for lab in self.client.list_labels():
            out.append({
                "id": lab.get("id"),
                "name": lab.get("name"),
                "type": lab.get("type"),
                "messages_total": lab.get("messagesTotal"),
            })
        return out

    def estimate_backfill(self) -> dict[str, dict[str, Any]]:
        known = {l["id"]: l for l in self.list_labels() if l.get("id")}
        out: dict[str, dict[str, Any]] = {}
        for lid in self.labels:
            meta = known.get(lid) or {"id": lid}
            out[f"label:{lid}"] = {
                "name": meta.get("name"),
                "messages_total": meta.get("messages_total"),
            }
        return out

    def validate_credentials(self) -> ConnectorHealth:
        if not self.secret:
            return ConnectorHealth(status=HealthStatus.unauthorized,
                                   detail="no credential configured")
        try:
            profile = self.client.profile()
        except ConnectorError as exc:
            if exc.failure_class in (FailureClass.authentication,
                                     FailureClass.authorization):
                return ConnectorHealth(status=HealthStatus.unauthorized,
                                       detail="token rejected by gmail")
            return ConnectorHealth(
                status=HealthStatus.degraded,
                detail=f"gmail unreachable: {exc.failure_class.value}",
            )
        email = profile.get("emailAddress") or "?"
        self._account_email = email
        return ConnectorHealth(
            status=HealthStatus.healthy,
            detail=(f"authenticated as {email}; connector runs read-only "
                    "Gmail API calls only (gmail.readonly)"),
        )

    def plan_streams(self, account: SourceAccount) -> list[str]:
        return [f"label:{lid}" for lid in self.labels]

    def plan_sync(
        self,
        account: SourceAccount,
        checkpoint: Optional[ConnectorCheckpoint],
        *,
        stream: str,
    ) -> SyncPlan:
        if not self.labels:
            raise ConnectorError(
                "no labels configured",
                failure_class=FailureClass.configuration,
                human_action_required=True,
            )
        label = _parse_stream(stream)
        return SyncPlan(
            stream=stream,
            cursor_before=dict(checkpoint.cursor) if checkpoint else {},
            lookback_seconds=self.lookback_seconds,
            metadata={"label": label},
        )

    def _window_oldest(self, cursor: Optional[dict[str, Any]]) -> Optional[str]:
        if self.backfill_until or (
            cursor is None or not (cursor or {}).get("watermark")
        ):
            # Partition / first backfill uses explicit bounds when present.
            if self.backfill_since:
                return self.backfill_since
        watermark = (cursor or {}).get("watermark")
        if watermark:
            return _iso_minus_seconds(str(watermark), self.lookback_seconds)
        return self.backfill_since

    def _query_for_window(self, oldest: Optional[str]) -> Optional[str]:
        parts: list[str] = []
        if oldest:
            # Gmail q uses epoch seconds for after:
            try:
                dt = datetime.fromisoformat(oldest.replace("Z", "+00:00"))
                parts.append(f"after:{int(dt.timestamp())}")
            except ValueError:
                if len(oldest) >= 10:
                    parts.append(f"after:{oldest[:10].replace('-', '/')}")
        if self.backfill_until:
            try:
                dt = datetime.fromisoformat(
                    self.backfill_until.replace("Z", "+00:00"))
                parts.append(f"before:{int(dt.timestamp()) + 1}")
            except ValueError:
                pass
        if not self.include_spam:
            parts.append("-in:spam")
        if not self.include_promotions:
            parts.append("-category:promotions")
        return " ".join(parts) if parts else None

    def fetch_batch(
        self, plan: SyncPlan, cursor: Optional[dict[str, Any]],
    ) -> FetchPage:
        label = plan.metadata["label"]
        base = cursor or plan.cursor_before or {}
        window_oldest = (
            base.get("window_oldest") if ss.in_progress(base)
            else self._window_oldest(base)
        )
        cur = ss.normalize_cursor(base, window_oldest=window_oldest)
        state = ss.substream_state(cur, "messages")
        page_token = state.get("page_token")
        query = self._query_for_window(cur.get("window_oldest"))

        stubs, next_token = self.client.list_messages(
            label_ids=[label], query=query, page_token=page_token,
            max_results=50,
        )
        items: list[RawFetchItem] = []
        pages_used = 1
        for stub in stubs:
            mid = stub.get("id")
            if not mid:
                continue
            full = self.client.get_message(mid)
            if not full:
                continue
            items.append(self._raw_from_gmail(full, label))
            ss.bump_window_max(cur, _ms_to_iso(full.get("internalDate")))

        state["page_token"] = next_token
        if next_token and pages_used < self.max_pages:
            # continue same substream in a later batch
            return FetchPage(raw_items=items, cursor_after=cur, done=False)
        if next_token:
            return FetchPage(raw_items=items, cursor_after=cur, done=False)
        state.pop("page_token", None)
        return FetchPage(
            raw_items=items,
            cursor_after=ss.finalize_cursor(cur),
            done=True,
        )

    def _raw_from_gmail(self, full: dict[str, Any], label: str) -> RawFetchItem:
        payload = full.get("payload") or {}
        headers = _header_map(payload)
        parts = mail_mime.parts_from_gmail_payload(payload)
        from_addr = headers.get("From") or ""
        to_raw = headers.get("To") or ""
        cc_raw = headers.get("Cc") or ""
        subject = headers.get("Subject") or ""
        classification = classify_message(
            subject=subject,
            body=parts.get("authored") or parts.get("body_text") or full.get("snippet") or "",
            from_addr=from_addr,
            headers=headers,
        )
        thread_id = full.get("threadId") or full.get("id")
        in_reply = bool(headers.get("In-Reply-To") or headers.get("References"))
        obj = {
            "id": full.get("id"),
            "thread_id": thread_id,
            "threadId": thread_id,
            "label_ids": full.get("labelIds") or [label],
            "folder_id": label,
            "subject": subject,
            "from": from_addr,
            "to": [a.strip() for a in to_raw.split(",") if a.strip()],
            "cc": [a.strip() for a in cc_raw.split(",") if a.strip()],
            "snippet": full.get("snippet"),
            "internalDate": full.get("internalDate"),
            "internalDate_iso": _ms_to_iso(full.get("internalDate")),
            "occurred_at": _ms_to_iso(full.get("internalDate")),
            "historyId": full.get("historyId"),
            "internet_message_id": headers.get("Message-ID"),
            "in_reply_to": headers.get("In-Reply-To"),
            "headers": headers,
            "classification": classification,
            "is_reply": in_reply,
            **parts,
        }
        ext_type = "thread_message" if in_reply else "message"
        return RawFetchItem(
            external_type=ext_type,
            external_id=str(full.get("id")),
            external_revision=mail_norm.revision_for_message(obj),
            payload={"provider": "gmail", "object": obj,
                     "account_email": self._account_email
                     or self.account.external_account_id or "me"},
            occurred_at=obj.get("occurred_at"),
        )

    def normalize(self, raw_item: RawConnectorItem) -> list[ConnectorRecord]:
        payload = raw_item.payload or {}
        obj = payload.get("object")
        if not isinstance(obj, dict):
            raise ConnectorError(
                "gmail raw item missing object envelope",
                failure_class=FailureClass.schema_change,
                external_id=raw_item.external_id,
                external_type=raw_item.external_type,
            )
        account_key = payload.get("account_email") or "me"
        rec = mail_norm.record_from_message(
            connector_id=raw_item.connector_id,
            account_id=raw_item.source_account_id,
            provider="gmail",
            account_key=str(account_key),
            message=obj,
            external_type=raw_item.external_type,
        )
        rec.external_id = raw_item.external_id
        rec.external_revision = raw_item.external_revision
        if raw_item.deleted:
            rec.deleted = True
        return [rec]

    def acknowledge(self, plan: SyncPlan, page: FetchPage) -> dict[str, Any]:
        return page.cursor_after or dict(plan.cursor_before or {})
