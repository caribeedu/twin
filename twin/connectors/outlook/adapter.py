"""OutlookConnector — Microsoft Graph mail adapter (v0.6 Phase 4).

Shares the Gmail cognitive model (``mail.normalize``). Streams:

    folder:{folder_id}

Explicit folder allowlist only — never whole mailbox by default.
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
from .client import GRAPH_API, OutlookClient

DEFAULT_LOOKBACK_SECONDS = 86400
DEFAULT_MAX_PAGES = 5


def _parse_stream(stream: str) -> str:
    parts = stream.split(":", 1)
    if len(parts) != 2 or parts[0] != "folder" or not parts[1]:
        raise ConnectorError(
            f"unknown outlook stream layout: {stream!r}",
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


def _addr_list(recipients: Any) -> list[str]:
    out: list[str] = []
    for r in recipients or []:
        if not isinstance(r, dict):
            continue
        ea = (r.get("emailAddress") or {}).get("address")
        if ea:
            out.append(ea)
    return out


@register_adapter
class OutlookConnector:
    connector_type = "outlook"

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
        self.folders: list[str] = list(cfg.get("folders") or [])
        self.lookback_seconds = int(cfg.get("lookback_seconds",
                                            DEFAULT_LOOKBACK_SECONDS))
        self.backfill_since: Optional[str] = cfg.get("backfill_since")
        self.backfill_until: Optional[str] = cfg.get("backfill_until")
        self.max_pages = int(cfg.get("max_pages_per_stream", DEFAULT_MAX_PAGES))
        self.api_base_url: str = cfg.get("api_base_url", GRAPH_API)
        self._client: Optional[OutlookClient] = None
        self._account_email: Optional[str] = cfg.get("account_email")

    @property
    def client(self) -> OutlookClient:
        if self._client is None:
            self._client = OutlookClient(self.secret, base_url=self.api_base_url)
        return self._client

    @staticmethod
    def adapter_manifest() -> AdapterManifest:
        return AdapterManifest(
            connector_type="outlook",
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
            supported_external_types=["message", "thread_message"],
            streams=[],
            dynamic_streams=True,
            default_scopes=["Mail.Read"],
        )

    def discover_accounts(self) -> list[SourceAccount]:
        return [self.account]

    def list_folders(self) -> list[dict[str, Any]]:
        out = []
        for folder in self.client.list_folders():
            out.append({
                "id": folder.get("id"),
                "name": folder.get("displayName"),
                "total_item_count": folder.get("totalItemCount"),
            })
        return out

    def estimate_backfill(self) -> dict[str, dict[str, Any]]:
        known = {f["id"]: f for f in self.list_folders() if f.get("id")}
        out: dict[str, dict[str, Any]] = {}
        for fid in self.folders:
            meta = known.get(fid) or {"id": fid}
            out[f"folder:{fid}"] = {
                "name": meta.get("name"),
                "total_item_count": meta.get("total_item_count"),
            }
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
                                       detail="token rejected by graph")
            return ConnectorHealth(
                status=HealthStatus.degraded,
                detail=f"graph unreachable: {exc.failure_class.value}",
            )
        email = me.get("mail") or me.get("userPrincipalName") or "?"
        self._account_email = email
        return ConnectorHealth(
            status=HealthStatus.healthy,
            detail=(f"authenticated as {email}; connector runs read-only "
                    "Graph Mail.Read calls only"),
        )

    def plan_streams(self, account: SourceAccount) -> list[str]:
        return [f"folder:{fid}" for fid in self.folders]

    def plan_sync(
        self,
        account: SourceAccount,
        checkpoint: Optional[ConnectorCheckpoint],
        *,
        stream: str,
    ) -> SyncPlan:
        if not self.folders:
            raise ConnectorError(
                "no folders configured",
                failure_class=FailureClass.configuration,
                human_action_required=True,
            )
        folder = _parse_stream(stream)
        return SyncPlan(
            stream=stream,
            cursor_before=dict(checkpoint.cursor) if checkpoint else {},
            lookback_seconds=self.lookback_seconds,
            metadata={"folder": folder},
        )

    def _window_oldest(self, cursor: Optional[dict[str, Any]]) -> Optional[str]:
        if self.backfill_since and not (cursor or {}).get("watermark"):
            return self.backfill_since
        watermark = (cursor or {}).get("watermark")
        if watermark:
            return _iso_minus_seconds(str(watermark), self.lookback_seconds)
        return self.backfill_since

    def _filter(self, oldest: Optional[str]) -> Optional[str]:
        clauses = []
        if oldest:
            clauses.append(f"receivedDateTime ge {oldest}")
        if self.backfill_until:
            clauses.append(f"receivedDateTime le {self.backfill_until}")
        return " and ".join(clauses) if clauses else None

    def fetch_batch(
        self, plan: SyncPlan, cursor: Optional[dict[str, Any]],
    ) -> FetchPage:
        folder = plan.metadata["folder"]
        base = cursor or plan.cursor_before or {}
        window_oldest = (
            base.get("window_oldest") if ss.in_progress(base)
            else self._window_oldest(base)
        )
        cur = ss.normalize_cursor(base, window_oldest=window_oldest)
        state = ss.substream_state(cur, "messages")
        next_link = state.get("next_link")
        messages, next_link = self.client.list_messages(
            folder,
            filter_query=None if next_link else self._filter(cur.get("window_oldest")),
            skip_token=next_link,
            top=50,
        )
        items: list[RawFetchItem] = []
        for msg in messages:
            if msg.get("isDraft"):
                continue
            items.append(self._raw_from_graph(msg, folder))
            ss.bump_window_max(cur, msg.get("receivedDateTime"))

        state["next_link"] = next_link
        if next_link:
            return FetchPage(raw_items=items, cursor_after=cur, done=False)
        state.pop("next_link", None)
        return FetchPage(
            raw_items=items,
            cursor_after=ss.finalize_cursor(cur),
            done=True,
        )

    def _raw_from_graph(self, msg: dict[str, Any], folder: str) -> RawFetchItem:
        body = msg.get("body") or {}
        content = body.get("content") or ""
        ctype = (body.get("contentType") or "").lower()
        if ctype == "html":
            plain = mail_mime.strip_html(content)
            html = mail_mime.sanitize_html(content)
        else:
            plain = content
            html = ""
        regions = mail_mime.split_authored(plain)
        from_addr = ((msg.get("from") or {}).get("emailAddress") or {}).get("address") or ""
        subject = msg.get("subject") or ""
        classification = classify_message(
            subject=subject,
            body=regions["authored"] or msg.get("bodyPreview") or "",
            from_addr=from_addr,
        )
        conv = msg.get("conversationId") or msg.get("id")
        # Graph rarely exposes In-Reply-To; treat quoted bodies / Re: subjects
        # as replies (conversationId alone is not enough — it is shared).
        in_reply = bool(regions.get("quoted")) or subject.lower().startswith("re:")
        obj = {
            "id": msg.get("id"),
            "thread_id": conv,
            "conversationId": conv,
            "folder_id": folder,
            "subject": subject,
            "from": from_addr,
            "to": _addr_list(msg.get("toRecipients")),
            "cc": _addr_list(msg.get("ccRecipients")),
            "snippet": msg.get("bodyPreview"),
            "receivedDateTime": msg.get("receivedDateTime"),
            "occurred_at": msg.get("receivedDateTime"),
            "changeKey": msg.get("changeKey"),
            "internet_message_id": msg.get("internetMessageId"),
            "classification": classification,
            "is_reply": in_reply,
            "body_text": plain,
            "body_html_sanitized": html,
            "authored": regions["authored"],
            "quoted": regions["quoted"],
            "signature": regions["signature"],
            "attachments": (
                [{"filename": "(has attachments)", "mime_type": "application/octet-stream",
                  "size": 0, "download_status": "metadata_only"}]
                if msg.get("hasAttachments") else []
            ),
        }
        ext_type = "thread_message" if in_reply else "message"
        return RawFetchItem(
            external_type=ext_type,
            external_id=str(msg.get("id")),
            external_revision=mail_norm.revision_for_message(obj),
            payload={"provider": "outlook", "object": obj,
                     "account_email": self._account_email
                     or self.account.external_account_id or "me"},
            occurred_at=obj.get("occurred_at"),
        )

    def normalize(self, raw_item: RawConnectorItem) -> list[ConnectorRecord]:
        payload = raw_item.payload or {}
        obj = payload.get("object")
        if not isinstance(obj, dict):
            raise ConnectorError(
                "outlook raw item missing object envelope",
                failure_class=FailureClass.schema_change,
                external_id=raw_item.external_id,
                external_type=raw_item.external_type,
            )
        account_key = payload.get("account_email") or "me"
        rec = mail_norm.record_from_message(
            connector_id=raw_item.connector_id,
            account_id=raw_item.source_account_id,
            provider="outlook",
            account_key=str(account_key),
            message=obj,
            external_type=raw_item.external_type,
        )
        rec.external_id = raw_item.external_id
        rec.external_revision = raw_item.external_revision
        return [rec]

    def acknowledge(self, plan: SyncPlan, page: FetchPage) -> dict[str, Any]:
        return page.cursor_after or dict(plan.cursor_before or {})
