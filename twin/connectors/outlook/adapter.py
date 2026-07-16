"""OutlookConnector — Microsoft Graph mail adapter (v0.6 Phase 4).

Streams:

    folder:{folder_id}
    backfill:{job}:{partition}:folder:{folder_id}

Continuous sync uses Graph delta queries (``delta_link`` in the checkpoint).
Backfill is a receivedDateTime window on a namespaced stream. ``@removed``
objects become tombstones. Attachment discovery lists real Graph metadata.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..mail import mime as mail_mime
from ..mail import normalize as mail_norm
from ..mail import sync_state as ss
from ..mail.classification import classify_message
from ..mail.membership import (
    active_memberships,
    resolve_mail_tombstone_type,
)
from ..mail.streams import parse_folder_stream, parse_mail_stream
from ..models import (
    ConnectorCheckpoint,
    ConnectorInstance,
    ConnectorRecord,
    FailureClass,
    HealthStatus,
    RawConnectorItem,
    SourceAccount,
    SyncExecutionContext,
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
        self.max_pages = int(cfg.get("max_pages_per_stream", DEFAULT_MAX_PAGES))
        self.api_base_url: str = cfg.get("api_base_url", GRAPH_API)
        self.attachment_mode: str = cfg.get("attachment_mode") or "metadata_only"
        self._client: Optional[OutlookClient] = None
        self._account_email: Optional[str] = cfg.get("account_email")
        self._execution_context = SyncExecutionContext()
        self._store = None

    @property
    def client(self) -> OutlookClient:
        if self._client is None:
            self._client = OutlookClient(self.secret, base_url=self.api_base_url)
        return self._client

    @property
    def exec_ctx(self) -> SyncExecutionContext:
        return getattr(self, "_execution_context", None) or SyncExecutionContext()

    @staticmethod
    def adapter_manifest() -> AdapterManifest:
        return AdapterManifest(
            connector_type="outlook",
            adapter_version="1.1",
            schema_version=1,
            auth_mode="oauth2",
            affordances={
                "incremental_sync": True,
                "webhooks": False,
                "deletions": True,
                "attachments": True,
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
        meta = parse_mail_stream(stream)
        folder = parse_folder_stream(meta["base_stream"])
        return SyncPlan(
            stream=stream,
            cursor_before=dict(checkpoint.cursor) if checkpoint else {},
            lookback_seconds=self.lookback_seconds,
            metadata={
                "folder": folder,
                "mode": meta["mode"],
                "job_id": meta.get("job_id"),
                "partition_key": meta.get("partition_key"),
            },
        )

    def _range_bounds(self, mode: str) -> tuple[Optional[str], Optional[str]]:
        ctx = self.exec_ctx
        if mode == "backfill" or ctx.mode == "backfill":
            return ctx.range_start, ctx.range_end
        return self.backfill_since, None

    def _window_oldest(self, cursor: Optional[dict[str, Any]],
                       mode: str) -> Optional[str]:
        since, _until = self._range_bounds(mode)
        if mode == "backfill":
            return since
        if cursor is None or not (cursor or {}).get("watermark"):
            return since
        watermark = (cursor or {}).get("watermark")
        if watermark:
            return _iso_minus_seconds(str(watermark), self.lookback_seconds)
        return since

    def _filter(self, oldest: Optional[str], until: Optional[str]) -> Optional[str]:
        clauses = []
        if oldest:
            clauses.append(f"receivedDateTime ge {oldest}")
        if until:
            clauses.append(f"receivedDateTime le {until}")
        return " and ".join(clauses) if clauses else None

    def fetch_batch(
        self, plan: SyncPlan, cursor: Optional[dict[str, Any]],
    ) -> FetchPage:
        mode = plan.metadata.get("mode") or "continuous"
        folder = plan.metadata["folder"]
        if mode == "backfill":
            return self._fetch_timerange(plan, cursor, folder)
        # Continuous sync: Graph delta is the authoritative feed (Strategy A).
        # Initial enumeration values are processed — never discarded.
        base = cursor or plan.cursor_before or {}
        return self._fetch_delta(base, folder)

    def _fetch_timerange(
        self, plan: SyncPlan, cursor: Optional[dict[str, Any]], folder: str,
    ) -> FetchPage:
        mode = plan.metadata.get("mode") or "continuous"
        base = cursor or plan.cursor_before or {}
        if (mode == "backfill" and base.get("partition_complete")
                and not ss.in_progress(base)):
            return FetchPage(raw_items=[], cursor_after=dict(base), done=True)
        since, until = self._range_bounds(mode)
        window_oldest = (
            base.get("window_oldest") if ss.in_progress(base)
            else self._window_oldest(base, mode)
        )
        cur = ss.normalize_cursor(base, window_oldest=window_oldest)
        state = ss.substream_state(cur, "messages")
        next_link = state.get("next_link")
        messages, next_link = self.client.list_messages(
            folder,
            filter_query=None if next_link else self._filter(
                cur.get("window_oldest"), until),
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
        finalized = ss.finalize_cursor(cur)
        if mode == "backfill":
            finalized["partition_complete"] = True
        return FetchPage(raw_items=items, cursor_after=finalized, done=True)

    def _fetch_delta(self, cursor: dict[str, Any], folder: str) -> FetchPage:
        link = cursor.get("next_link") or cursor.get("delta_link")
        data = self.client.delta_messages(folder, link=link)
        items: list[RawFetchItem] = []
        for msg in data.get("value") or []:
            if not isinstance(msg, dict):
                continue
            removed = msg.get("@removed")
            mid = msg.get("id")
            if removed and mid:
                action = self._removed_action(mid, folder, removed)
                if action is not None:
                    items.append(action)
                continue
            if msg.get("isDraft"):
                continue
            if mid:
                items.append(self._raw_from_graph(msg, folder))
                if msg.get("receivedDateTime"):
                    # keep a soft watermark for diagnostics
                    cursor = dict(cursor)
                    cursor["watermark"] = max(
                        str(cursor.get("watermark") or ""),
                        str(msg["receivedDateTime"]),
                    )
        after = {
            "watermark": cursor.get("watermark"),
            "reconciliation_watermark": cursor.get("reconciliation_watermark")
            or cursor.get("watermark"),
        }
        if data.get("@odata.nextLink"):
            # Preserve prior delta_link only as fallback; next page continues
            # the same enumeration — all values are processed.
            if cursor.get("delta_link"):
                after["delta_link"] = cursor["delta_link"]
            after["next_link"] = data["@odata.nextLink"]
            return FetchPage(raw_items=items, cursor_after=after, done=False)
        if data.get("@odata.deltaLink"):
            after["delta_link"] = data["@odata.deltaLink"]
        elif cursor.get("delta_link"):
            after["delta_link"] = cursor["delta_link"]
        return FetchPage(raw_items=items, cursor_after=after, done=True)

    def _removed_action(
        self, message_id: str, folder: str, removed: dict[str, Any],
    ) -> Optional[RawFetchItem]:
        """``@removed`` may mean delete OR move (reason=changed).

        Only leave the cognitive scope when the message is gone or no longer
        in any allowlisted folder.
        """
        reason = str((removed or {}).get("reason") or "").lower()
        if reason == "deleted":
            return self._tombstone(message_id, folder)
        # changed / moved / unknown — resolve current membership
        try:
            msg = self.client.get_message(message_id)
        except ConnectorError:
            return self._tombstone(message_id, folder)
        if not msg:
            return self._tombstone(message_id, folder)
        parent = msg.get("parentFolderId")
        if parent and parent in self.folders:
            return self._raw_from_graph(msg, parent)
        # Outside every allowlisted folder → global tombstone
        return self._tombstone(message_id, folder)

    def _tombstone(self, message_id: str, folder: str) -> RawFetchItem:
        ext_type = resolve_mail_tombstone_type(
            self._store, self.instance.id, str(message_id),
        )
        return RawFetchItem(
            external_type=ext_type,
            external_id=str(message_id),
            external_revision=f"{message_id}.deleted",
            payload={
                "provider": "outlook",
                "object": {"id": message_id, "folder_id": folder, "deleted": True},
                "account_email": self._account_email
                or self.account.external_account_id or "me",
            },
            deleted=True,
        )

    def _attachment_meta(self, msg: dict[str, Any]) -> list[dict[str, Any]]:
        mode = self.exec_ctx.attachment_mode or self.attachment_mode
        if not msg.get("hasAttachments"):
            return []
        mid = msg.get("id")
        if not mid:
            return [{
                "filename": "(has attachments)",
                "mime_type": "application/octet-stream",
                "size": 0,
                "download_status": mode,
            }]
        try:
            raw = self.client.list_attachments(str(mid))
        except ConnectorError:
            return [{
                "filename": "(has attachments)",
                "mime_type": "application/octet-stream",
                "size": 0,
                "download_status": "metadata_only",
            }]
        out = []
        for att in raw:
            out.append({
                "attachment_id": att.get("id"),
                "filename": att.get("name") or "attachment",
                "mime_type": att.get("contentType") or "application/octet-stream",
                "size": int(att.get("size") or 0),
                "content_id": att.get("contentId"),
                "is_inline": bool(att.get("isInline")),
                "odata_type": att.get("@odata.type"),
                "download_status": mode if mode in (
                    "metadata_only", "discovery") else "metadata_only",
                "storage_ref": None,
            })
        return out

    def _raw_from_graph(self, msg: dict[str, Any], folder: str) -> RawFetchItem:
        body = msg.get("body") or {}
        content = body.get("content") or ""
        ctype = (body.get("contentType") or "").lower()
        if ctype == "html":
            plain = mail_mime.strip_html(content)
            html_stub = mail_mime.untrusted_html_stub(content)
        else:
            plain = content
            html_stub = ""
        regions = mail_mime.split_authored(plain)
        from_addr = ((msg.get("from") or {}).get("emailAddress") or {}).get("address") or ""
        subject = msg.get("subject") or ""
        classification = classify_message(
            subject=subject,
            body=regions["authored"] or msg.get("bodyPreview") or "",
            from_addr=from_addr,
        )
        conv = msg.get("conversationId") or msg.get("id")
        # conversationId already threads; is_reply is soft metadata only.
        is_reply: Optional[bool]
        if regions.get("quoted"):
            is_reply = True
        elif subject.lower().startswith("re:"):
            is_reply = True
        else:
            is_reply = None  # unknown — do not force thread_message
        mode = self.exec_ctx.attachment_mode or self.attachment_mode
        memberships = active_memberships(
            kind="folder", configured_ids=self.folders, current_ids=[folder],
        )
        obj = {
            "id": msg.get("id"),
            "thread_id": conv,
            "conversationId": conv,
            "folder_id": folder,
            "source_memberships": memberships,
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
            "is_reply": is_reply,
            "body_text": plain,
            "body_html_untrusted_stub": html_stub,
            "authored": regions["authored"],
            "quoted": regions["quoted"],
            "signature": regions["signature"],
            "attachments": self._attachment_meta(msg),
            "attachment_mode": mode,
        }
        # Prefer stable external_type=message; reply is metadata.
        return RawFetchItem(
            external_type="message",
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
        if raw_item.deleted or obj.get("deleted"):
            return [ConnectorRecord(
                connector_id=raw_item.connector_id,
                source_account_id=raw_item.source_account_id,
                external_type=raw_item.external_type or "message",
                external_id=raw_item.external_id,
                external_revision=raw_item.external_revision,
                content=f"Email [outlook] deleted {raw_item.external_id}",
                deleted=True,
                source_metadata={"provider": "outlook", "deleted": True},
                confidentiality={"source_trust": 0.40},
            )]
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
