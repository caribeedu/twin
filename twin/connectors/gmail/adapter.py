"""GmailConnector — read-only Gmail adapter (v0.6 Phase 4).

Streams:

    label:{label_id}                              continuous change feed
    backfill:{job}:{partition}:label:{label_id}   historical time-range scan

Continuous sync prefers History API (``history_id`` in the checkpoint).
Backfill is a pure date-window search on a namespaced stream so it never
touches the continuous watermark. Deletions / label removals emit tombstones.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import getaddresses
from typing import Any, Optional

from ..mail import mime as mail_mime
from ..mail import normalize as mail_norm
from ..mail import sync_state as ss
from ..mail.classification import classify_message
from ..mail.membership import (
    active_memberships,
    resolve_mail_tombstone_type,
    still_in_scope,
)
from ..mail.streams import parse_label_stream, parse_mail_stream
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
from .client import GMAIL_API, GmailClient

DEFAULT_LOOKBACK_SECONDS = 86400
DEFAULT_MAX_PAGES = 5


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


def _iso_to_epoch(iso_ts: str) -> Optional[int]:
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(dt.timestamp())


def _header_map(payload: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for h in (payload.get("headers") or []):
        if isinstance(h, dict) and h.get("name"):
            out[h["name"]] = h.get("value") or ""
    return out


def _addresses(header_value: str) -> list[str]:
    return [addr for _name, addr in getaddresses([header_value or ""]) if addr]


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
        # Bootstrap / first-sync floor only — backfill bounds travel via
        # SyncExecutionContext, never temporary config mutation.
        self.backfill_since: Optional[str] = cfg.get("backfill_since")
        self.max_pages = int(cfg.get("max_pages_per_stream", DEFAULT_MAX_PAGES))
        self.api_base_url: str = cfg.get("api_base_url", GMAIL_API)
        self.include_spam = bool(cfg.get("include_spam", False))
        self.include_promotions = bool(cfg.get("include_promotions", False))
        self.attachment_mode: str = cfg.get("attachment_mode") or "metadata_only"
        self._client: Optional[GmailClient] = None
        self._account_email: Optional[str] = cfg.get("account_email")
        self._execution_context = SyncExecutionContext()
        self._store = None

    @property
    def client(self) -> GmailClient:
        if self._client is None:
            self._client = GmailClient(self.secret, base_url=self.api_base_url)
        return self._client

    @property
    def exec_ctx(self) -> SyncExecutionContext:
        return getattr(self, "_execution_context", None) or SyncExecutionContext()

    @staticmethod
    def adapter_manifest() -> AdapterManifest:
        return AdapterManifest(
            connector_type="gmail",
            adapter_version="1.1",
            schema_version=1,
            auth_mode="oauth2",
            affordances={
                "incremental_sync": True,
                "webhooks": False,
                "deletions": True,
                "attachments": True,  # discovery / metadata_only
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
        meta = parse_mail_stream(stream)
        label = parse_label_stream(meta["base_stream"])
        return SyncPlan(
            stream=stream,
            cursor_before=dict(checkpoint.cursor) if checkpoint else {},
            lookback_seconds=self.lookback_seconds,
            metadata={
                "label": label,
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

    def _query_for_window(
        self, oldest: Optional[str], until: Optional[str], *,
        edge_overlap_seconds: int = 1,
    ) -> Optional[str]:
        """Gmail ``after:`` is exclusive — overlap by 1s so month edges land."""
        parts: list[str] = []
        if oldest:
            epoch = _iso_to_epoch(oldest if "T" in oldest
                                  else oldest + "T00:00:00Z")
            if epoch is not None:
                parts.append(f"after:{epoch - edge_overlap_seconds}")
            elif len(oldest) >= 10:
                parts.append(f"after:{oldest[:10].replace('-', '/')}")
        if until:
            epoch = _iso_to_epoch(until if "T" in until
                                  else until + "T23:59:59Z")
            if epoch is not None:
                parts.append(f"before:{epoch + edge_overlap_seconds + 1}")
        if not self.include_spam:
            parts.append("-in:spam")
        if not self.include_promotions:
            parts.append("-category:promotions")
        return " ".join(parts) if parts else None

    def fetch_batch(
        self, plan: SyncPlan, cursor: Optional[dict[str, Any]],
    ) -> FetchPage:
        mode = plan.metadata.get("mode") or "continuous"
        label = plan.metadata["label"]
        if mode == "backfill":
            return self._fetch_timerange(plan, cursor, label)
        base = cursor or plan.cursor_before or {}
        # Sealed continuous feed.
        if (base.get("history_id") and not base.get("bootstrap_phase")
                and not ss.in_progress(base)):
            return self._fetch_history(plan, base, label)
        # After time-range bootstrap: catch up events since H0.
        if base.get("bootstrap_phase") == "history_catchup":
            return self._fetch_history(plan, base, label, catchup=True)
        # Bootstrap scan — capture history boundary FIRST.
        return self._fetch_timerange(plan, cursor, label, bootstrap=True)

    def _fetch_timerange(
        self, plan: SyncPlan, cursor: Optional[dict[str, Any]], label: str,
        *, bootstrap: bool = False,
    ) -> FetchPage:
        mode = plan.metadata.get("mode") or "continuous"
        base = cursor or plan.cursor_before or {}
        # Already finished this backfill partition window — no re-scan.
        if (mode == "backfill" and base.get("partition_complete")
                and not ss.in_progress(base)):
            return FetchPage(raw_items=[], cursor_after=dict(base), done=True)

        since, until = self._range_bounds(mode)
        window_oldest = (
            base.get("window_oldest") if ss.in_progress(base)
            else self._window_oldest(base, mode)
        )
        cur = ss.normalize_cursor(base, window_oldest=window_oldest)
        # Capture change-feed boundary BEFORE the scan so concurrent events
        # cannot fall between the last page and a late profile.historyId.
        if bootstrap and not cur.get("bootstrap_history_id"):
            profile = self.client.profile()
            hid = profile.get("historyId")
            if hid:
                cur["bootstrap_history_id"] = str(hid)
        if base.get("bootstrap_history_id"):
            cur["bootstrap_history_id"] = base["bootstrap_history_id"]
        if base.get("history_id"):
            cur["history_id"] = base["history_id"]

        state = ss.substream_state(cur, "messages")
        page_token = state.get("page_token")
        query = self._query_for_window(cur.get("window_oldest"), until)

        stubs, next_token = self.client.list_messages(
            label_ids=[label], query=query, page_token=page_token,
            max_results=50,
        )
        items: list[RawFetchItem] = []
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
        if next_token:
            return FetchPage(raw_items=items, cursor_after=cur, done=False)
        state.pop("page_token", None)
        finalized = ss.finalize_cursor(cur)
        if bootstrap and mode == "continuous":
            # Do NOT seal with a late profile historyId — catch up from H0.
            h0 = cur.get("bootstrap_history_id")
            if finalized.get("watermark"):
                finalized["reconciliation_watermark"] = finalized["watermark"]
            if h0:
                finalized["bootstrap_history_id"] = str(h0)
                finalized["bootstrap_phase"] = "history_catchup"
                finalized["history_id"] = str(h0)
                return FetchPage(raw_items=items, cursor_after=finalized,
                                 done=False)
            return FetchPage(raw_items=items, cursor_after=finalized, done=True)
        if mode == "backfill":
            finalized["partition_complete"] = True
        return FetchPage(raw_items=items, cursor_after=finalized, done=True)

    def _fetch_history(
        self, plan: SyncPlan, cursor: dict[str, Any], label: str,
        *, catchup: bool = False,
    ) -> FetchPage:
        start = str(
            cursor.get("history_id")
            or cursor.get("bootstrap_history_id")
            or ""
        )
        if not start:
            return self._fetch_timerange(plan, cursor, label, bootstrap=True)
        state = dict(cursor.get("history_progress") or {})
        page_token = state.get("page_token")
        try:
            data = self.client.list_history(
                start_history_id=start, label_id=label,
                page_token=page_token, max_results=100,
            )
        except ConnectorError as exc:
            if getattr(exc, "history_id_too_old", False):
                fresh = {
                    "watermark": cursor.get("reconciliation_watermark")
                    or cursor.get("watermark"),
                }
                return self._fetch_timerange(plan, fresh, label, bootstrap=True)
            raise

        items: list[RawFetchItem] = []
        seen_add: set[str] = set()
        seen_del: set[str] = set()
        for hist in data.get("history") or []:
            for added in hist.get("messagesAdded") or []:
                msg = added.get("message") or {}
                mid = msg.get("id")
                labels = set(msg.get("labelIds") or [])
                if not mid or mid in seen_add:
                    continue
                if label not in labels and labels:
                    continue
                full = self.client.get_message(mid)
                if full:
                    items.append(self._raw_from_gmail(full, label))
                    seen_add.add(mid)
            for lab_add in hist.get("labelsAdded") or []:
                msg = lab_add.get("message") or {}
                mid = msg.get("id")
                lab_ids = set(lab_add.get("labelIds") or [])
                if not mid or mid in seen_add or label not in lab_ids:
                    continue
                full = self.client.get_message(mid)
                if full:
                    items.append(self._raw_from_gmail(full, label))
                    seen_add.add(mid)
            for removed in hist.get("messagesDeleted") or []:
                msg = removed.get("message") or {}
                mid = msg.get("id")
                if mid and mid not in seen_del:
                    items.append(self._tombstone(mid, label))
                    seen_del.add(mid)
            for lab_rm in hist.get("labelsRemoved") or []:
                msg = lab_rm.get("message") or {}
                mid = msg.get("id")
                lab_ids = set(lab_rm.get("labelIds") or [])
                if not mid or label not in lab_ids or mid in seen_del:
                    continue
                decision = self._label_removal_action(mid)
                if decision == "tombstone":
                    items.append(self._tombstone(mid, label))
                    seen_del.add(mid)
                elif decision is not None:
                    items.append(decision)

        next_token = data.get("nextPageToken")
        new_history = str(data.get("historyId") or start)
        after = {
            "watermark": cursor.get("watermark"),
            "reconciliation_watermark": cursor.get("reconciliation_watermark")
            or cursor.get("watermark"),
        }
        if next_token:
            after["history_id"] = start
            after["history_progress"] = {"page_token": next_token}
            if catchup or cursor.get("bootstrap_phase"):
                after["bootstrap_phase"] = "history_catchup"
                after["bootstrap_history_id"] = cursor.get(
                    "bootstrap_history_id") or start
            return FetchPage(raw_items=items, cursor_after=after, done=False)
        # Catch-up / continuous page complete — seal final history_id.
        after["history_id"] = new_history
        return FetchPage(raw_items=items, cursor_after=after, done=True)

    def _label_removal_action(self, message_id: str) -> Any:
        """Return tombstone / updated RawFetchItem / None.

        Removing one allowlisted label is not a global deletion while another
        configured label still covers the message.
        """
        full = self.client.get_message(message_id)
        if not full:
            return "tombstone"
        current = list(full.get("labelIds") or [])
        if still_in_scope(configured_ids=self.labels, current_ids=current):
            # Still in connector scope — refresh membership metadata.
            # Prefer a remaining configured label as the stream context.
            remaining = [l for l in current if l in self.labels]
            return self._raw_from_gmail(full, remaining[0])
        return "tombstone"

    def _tombstone(self, message_id: str, label: str) -> RawFetchItem:
        ext_type = resolve_mail_tombstone_type(
            self._store, self.instance.id, str(message_id),
        )
        return RawFetchItem(
            external_type=ext_type,
            external_id=str(message_id),
            external_revision=f"{message_id}.deleted",
            payload={
                "provider": "gmail",
                "object": {
                    "id": message_id,
                    "folder_id": label,
                    "deleted": True,
                },
                "account_email": self._account_email
                or self.account.external_account_id or "me",
            },
            deleted=True,
        )

    def _raw_from_gmail(self, full: dict[str, Any], label: str) -> RawFetchItem:
        payload = full.get("payload") or {}
        headers = _header_map(payload)
        parts = mail_mime.parts_from_gmail_payload(payload)
        mode = self.exec_ctx.attachment_mode or self.attachment_mode
        for att in parts.get("attachments") or []:
            att["download_status"] = mode if mode in (
                "metadata_only", "discovery") else "metadata_only"
        from_addr = headers.get("From") or ""
        subject = headers.get("Subject") or ""
        classification = classify_message(
            subject=subject,
            body=parts.get("authored") or parts.get("body_text")
            or full.get("snippet") or "",
            from_addr=from_addr,
            headers=headers,
        )
        thread_id = full.get("threadId") or full.get("id")
        in_reply = bool(headers.get("In-Reply-To") or headers.get("References"))
        label_ids = list(full.get("labelIds") or [label])
        memberships = active_memberships(
            kind="label", configured_ids=self.labels, current_ids=label_ids,
        )
        obj = {
            "id": full.get("id"),
            "thread_id": thread_id,
            "threadId": thread_id,
            "label_ids": label_ids,
            "folder_id": label,
            "source_memberships": memberships,
            "subject": subject,
            "from": from_addr,
            "to": _addresses(headers.get("To") or ""),
            "cc": _addresses(headers.get("Cc") or ""),
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
            "attachment_mode": mode,
            **parts,
        }
        if "body_html_sanitized" in obj:
            obj["body_html_untrusted_stub"] = obj.pop("body_html_sanitized")
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
        if raw_item.deleted or obj.get("deleted"):
            rec = ConnectorRecord(
                connector_id=raw_item.connector_id,
                source_account_id=raw_item.source_account_id,
                external_type=raw_item.external_type or "message",
                external_id=raw_item.external_id,
                external_revision=raw_item.external_revision,
                content=f"Email [gmail] deleted {raw_item.external_id}",
                deleted=True,
                source_metadata={"provider": "gmail", "deleted": True},
                confidentiality={"source_trust": 0.40},
            )
            return [rec]
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
        return [rec]

    def acknowledge(self, plan: SyncPlan, page: FetchPage) -> dict[str, Any]:
        return page.cursor_after or dict(plan.cursor_before or {})
