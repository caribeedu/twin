"""SlackConnector — ProfessionalConnector adapter for Slack (Web API).

Streams are dynamic, one per allowlisted channel:

    channel:{channel_id}

Each stream syncs channel history then thread replies for parents that
have ``reply_count > 0``. Configuration is an EXPLICIT channel allowlist —
workspace-wide ingest is never a default.

Incremental strategy: Slack ``ts`` watermark + lookback window, with
durable continuation cursors when the page budget is exhausted.
Deletions are observed via Events API hints (pending tombstones) and
emitted as ``deleted=True`` raw items for the framework deletion planner.
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
from .client import SLACK_API, SlackClient
from . import normalize as norm
from . import sync_state as ss

DEFAULT_LOOKBACK_SECONDS = 86400
DEFAULT_MAX_PAGES = 10
def _parse_stream(stream: str) -> str:
    """'channel:{id}' → channel id."""
    parts = stream.split(":", 1)
    if len(parts) != 2 or parts[0] != "channel" or not parts[1]:
        raise ConnectorError(
            f"unknown slack stream layout: {stream!r}",
            failure_class=FailureClass.schema_change,
        )
    return parts[1]


def _ts_minus_seconds(ts: str, seconds: int) -> str:
    try:
        base = float(ts)
    except (TypeError, ValueError):
        return ts
    return f"{max(0.0, base - seconds):.6f}"


def _iso_to_ts(iso_ts: Optional[str]) -> Optional[str]:
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return f"{dt.timestamp():.6f}"


@register_adapter
class SlackConnector:
    connector_type = "slack"

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
        self.channels: list[str] = list(cfg.get("channels") or [])
        self.lookback_seconds = int(cfg.get("lookback_seconds",
                                            DEFAULT_LOOKBACK_SECONDS))
        self.backfill_since: Optional[str] = cfg.get("backfill_since")
        self.max_pages = int(cfg.get("max_pages_per_stream", DEFAULT_MAX_PAGES))
        self.api_base_url: str = cfg.get("api_base_url", SLACK_API)
        self.include_dms = bool(cfg.get("include_direct_messages", False))
        self.include_private = bool(cfg.get("include_private_channels", False))
        self._client: Optional[SlackClient] = None
        self._channel_meta: dict[str, dict[str, Any]] = {}
        self._store = None
        self._pending_tombstone_emit: list[dict[str, str]] = []

    def attach_sync_hints(self, store) -> None:
        """Optional framework hook: let the adapter read CAS-guarded sync
        state (pending tombstones from Events API deletions)."""
        self._store = store

    @property
    def client(self) -> SlackClient:
        if self._client is None:
            self._client = SlackClient(self.secret, base_url=self.api_base_url)
        return self._client

    @staticmethod
    def adapter_manifest() -> AdapterManifest:
        return AdapterManifest(
            connector_type="slack",
            adapter_version="1.0",
            schema_version=1,
            auth_mode="personal_access_token",  # bot token / user token
            affordances={
                "incremental_sync": True,
                "webhooks": True,
                "deletions": True,
                "attachments": False,   # file metadata only in Phase 3
                "threads": True,
            },
            supported_external_types=[
                "channel", "message", "thread_reply", "file_share",
            ],
            streams=[],
            dynamic_streams=True,
            default_scopes=[
                "channels:history", "channels:read",
                "groups:history", "groups:read",
                "users:read",
            ],
        )

    def discover_accounts(self) -> list[SourceAccount]:
        return [self.account]

    def _channel_kind(self, channel_id: str) -> str:
        meta = self._channel_meta.get(channel_id) or {}
        if meta.get("is_im"):
            return "im"
        if meta.get("is_mpim"):
            return "mpim"
        if meta.get("is_private"):
            return "private"
        return "public"

    def list_channels(self) -> list[dict[str, Any]]:
        """Channels the token can see — for setup allowlist selection."""
        types = ["public_channel"]
        if self.include_private:
            types.append("private_channel")
        if self.include_dms:
            types.extend(["im", "mpim"])
        out: list[dict[str, Any]] = []
        cursor: Optional[str] = None
        pages = 0
        while pages < self.max_pages:
            batch, cursor = self.client.conversations_list(
                types=",".join(types), cursor=cursor)
            for ch in batch:
                out.append({
                    "id": ch.get("id"),
                    "name": ch.get("name") or ch.get("user"),
                    "is_private": bool(ch.get("is_private")),
                    "is_im": bool(ch.get("is_im")),
                    "is_mpim": bool(ch.get("is_mpim")),
                    "num_members": ch.get("num_members"),
                })
                if ch.get("id"):
                    self._channel_meta[ch["id"]] = ch
            pages += 1
            if not cursor:
                break
        return out

    def estimate_backfill(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        known = {c["id"]: c for c in self.list_channels() if c.get("id")}
        for cid in self.channels:
            meta = known.get(cid) or {"id": cid}
            out[f"channel:{cid}"] = {
                "name": meta.get("name"),
                "is_private": meta.get("is_private"),
                "num_members": meta.get("num_members"),
            }
        return out

    def validate_credentials(self) -> ConnectorHealth:
        if not self.secret:
            return ConnectorHealth(status=HealthStatus.unauthorized,
                                   detail="no credential configured")
        try:
            identity = self.client.auth_test()
        except ConnectorError as exc:
            if exc.failure_class == FailureClass.authentication:
                return ConnectorHealth(status=HealthStatus.unauthorized,
                                       detail="token rejected by slack")
            return ConnectorHealth(
                status=HealthStatus.degraded,
                detail=f"slack unreachable: {exc.failure_class.value}",
            )
        team = identity.get("team") or identity.get("url") or "?"
        user = identity.get("user") or identity.get("bot_id") or "?"
        # Slack does not reliably expose granted scopes on auth.test —
        # privilege is unverified; the connector itself only issues reads.
        detail = (f"authenticated as {user} on {team}; connector runs "
                  "read-only Web API calls only; credential privilege is "
                  "unverified via auth.test — use a least-privilege bot "
                  "token (channels:history/read, users:read)")
        return ConnectorHealth(status=HealthStatus.healthy, detail=detail)

    def plan_streams(self, account: SourceAccount) -> list[str]:
        return [f"channel:{cid}" for cid in self.channels]

    def plan_sync(
        self,
        account: SourceAccount,
        checkpoint: Optional[ConnectorCheckpoint],
        *,
        stream: str,
    ) -> SyncPlan:
        if not self.channels:
            raise ConnectorError(
                "no channels configured",
                failure_class=FailureClass.configuration,
                human_action_required=True,
            )
        channel = _parse_stream(stream)
        return SyncPlan(
            stream=stream,
            cursor_before=dict(checkpoint.cursor) if checkpoint else {},
            lookback_seconds=self.lookback_seconds,
            metadata={"channel": channel},
        )

    def _window_oldest(self, cursor: Optional[dict[str, Any]]) -> Optional[str]:
        watermark = (cursor or {}).get("watermark")
        if watermark:
            return _ts_minus_seconds(watermark, self.lookback_seconds)
        return _iso_to_ts(self.backfill_since)

    def fetch_batch(
        self, plan: SyncPlan, cursor: Optional[dict[str, Any]],
    ) -> FetchPage:
        channel = plan.metadata["channel"]
        base = cursor or plan.cursor_before or {}
        window_oldest = (
            base.get("window_oldest") if ss.in_progress(base)
            else self._window_oldest(base)
        )
        cur = ss.normalize_cursor(base, window_oldest=window_oldest)
        items: list[RawFetchItem] = []

        # Pending tombstones from Events API (message_deleted) — emit first
        # so a deletion hint is durable even when history no longer lists it.
        # Peek only here; clear in acknowledge after a successful commit so a
        # failed/partial batch does not drop the hint.
        self._pending_tombstone_emit = []
        for tomb in self._peek_tombstones(channel):
            items.append(tomb)
            ts = str((tomb.payload.get("object") or {}).get("ts") or "0")
            ss.bump_window_max(cur, ts)

        pages_budget = self.max_pages
        while pages_budget > 0:
            sub = cur["substream"]
            batch_items, pages_used, sub_done = self._fetch_substream(
                channel, sub, cur, pages_budget,
            )
            items.extend(batch_items)
            pages_budget -= pages_used
            if pages_used == 0 and not sub_done:
                return FetchPage(raw_items=items, cursor_after=cur, done=False)
            if not sub_done:
                return FetchPage(raw_items=items, cursor_after=cur, done=False)
            nxt = ss.next_substream(sub)
            if nxt:
                cur["substream"] = nxt
            else:
                return FetchPage(
                    raw_items=items,
                    cursor_after=ss.finalize_cursor(cur),
                    done=True,
                )
        return FetchPage(raw_items=items, cursor_after=cur, done=False)

    def _peek_tombstones(self, channel: str) -> list[RawFetchItem]:
        if self._store is None:
            return []
        state = self._store.get_connector_sync_state(self.instance.id)
        pending = list((state.metadata or {}).get("pending_tombstones") or []) \
            if state else []
        items: list[RawFetchItem] = []
        for tomb in pending:
            if tomb.get("channel") != channel:
                continue
            ts = str(tomb.get("ts") or "0")
            self._pending_tombstone_emit.append(
                {"channel": channel, "ts": ts},
            )
            items.append(self._raw(
                channel, "message", f"{channel}:{ts}",
                norm.revision_for_deletion(ts),
                {"ts": ts, "deleted": True, "subtype": "message_deleted",
                 "text": ""},
                deleted=True,
            ))
        return items

    def _clear_emitted_tombstones(self) -> None:
        if self._store is None or not self._pending_tombstone_emit:
            self._pending_tombstone_emit = []
            return
        from ..sync_state_cas import apply_sync_state

        remove = {(t["channel"], t["ts"]) for t in self._pending_tombstone_emit}

        def _apply(state) -> None:
            meta = dict(state.metadata or {})
            pending = list(meta.get("pending_tombstones") or [])
            keep = [t for t in pending
                    if (t.get("channel"), str(t.get("ts") or "0")) not in remove]
            if keep:
                meta["pending_tombstones"] = keep
            else:
                meta.pop("pending_tombstones", None)
            state.metadata = meta

        apply_sync_state(self._store, self.instance.id, _apply)
        self._pending_tombstone_emit = []

    def _fetch_substream(
        self, channel: str, substream: str, cursor: dict[str, Any],
        pages_budget: int,
    ) -> tuple[list[RawFetchItem], int, bool]:
        if substream == "history":
            return self._substream_history(channel, cursor, pages_budget)
        if substream == "threads":
            return self._substream_threads(channel, cursor, pages_budget)
        raise ConnectorError(
            f"unknown slack substream {substream!r}",
            failure_class=FailureClass.schema_change,
        )

    def _substream_history(
        self, channel: str, cursor: dict[str, Any], pages_budget: int,
    ) -> tuple[list[RawFetchItem], int, bool]:
        state = ss.substream_state(cursor, "history")
        thread_state = ss.substream_state(cursor, "threads")
        queue: list[str] = thread_state.setdefault("queue", [])
        seen: set[str] = set(thread_state.setdefault("seen", []))
        page_cursor = state.get("next_cursor")
        oldest = cursor.get("window_oldest")
        messages, next_cursor, has_more = self.client.conversations_history(
            channel, oldest=oldest, cursor=page_cursor, limit=200,
        )
        state["next_cursor"] = next_cursor
        items: list[RawFetchItem] = []
        for msg in messages:
            # history is newest-first; still process all in the page
            if msg.get("subtype") == "message_deleted" or msg.get("deleted"):
                ts_del = str(msg.get("ts") or "0")
                items.append(self._raw(
                    channel, "message",
                    f"{channel}:{ts_del}",
                    norm.revision_for_deletion(ts_del),
                    msg, deleted=True,
                ))
                ss.bump_window_max(cursor, ts_del)
                continue
            ts = str(msg.get("ts") or "")
            items.append(self._raw(
                channel, "message", f"{channel}:{ts}",
                norm.revision_for_message(msg), msg,
            ))
            ss.bump_window_max(cursor, ts)
            reply_count = int(msg.get("reply_count") or 0)
            if reply_count > 0 and ts and ts not in seen:
                seen.add(ts)
                queue.append(ts)
        thread_state["seen"] = sorted(seen)
        # Slack returns has_more + next_cursor; either signals continuation
        done = not has_more and not next_cursor
        return items, 1, done

    def _substream_threads(
        self, channel: str, cursor: dict[str, Any], pages_budget: int,
    ) -> tuple[list[RawFetchItem], int, bool]:
        state = ss.substream_state(cursor, "threads")
        queue: list[str] = state.get("queue") or []
        idx = int(state.get("idx", 0))
        items: list[RawFetchItem] = []
        pages_used = 0

        while idx < len(queue) and pages_used < pages_budget:
            thread_ts = queue[idx]
            reply_cursor = state.get("reply_cursor")
            messages, next_cursor = self.client.conversations_replies(
                channel, thread_ts, cursor=reply_cursor,
            )
            pages_used += 1
            for msg in messages:
                ts = str(msg.get("ts") or "")
                # conversations.replies includes the parent; skip it — history
                # already ingested the root
                if ts == thread_ts:
                    continue
                items.append(self._raw(
                    channel, "thread_reply", f"{channel}:{ts}",
                    norm.revision_for_message(msg), msg,
                ))
                ss.bump_window_max(cursor, ts)
            if next_cursor:
                state["reply_cursor"] = next_cursor
                state["idx"] = idx
                return items, pages_used, False
            state.pop("reply_cursor", None)
            idx += 1
            state["idx"] = idx
        return items, pages_used, idx >= len(queue)

    def _raw(self, channel: str, external_type: str, external_id: str,
             revision: str, obj: dict[str, Any], *,
             deleted: bool = False) -> RawFetchItem:
        return RawFetchItem(
            external_type=external_type,
            external_id=external_id,
            external_revision=str(revision),
            payload={"channel": channel, "object": obj,
                     "channel_kind": self._channel_kind(channel)},
            occurred_at=norm._ts_to_iso(str(obj.get("ts") or "")),
            deleted=deleted,
        )

    def normalize(self, raw_item: RawConnectorItem) -> list[ConnectorRecord]:
        payload = raw_item.payload or {}
        channel = payload.get("channel")
        obj = payload.get("object")
        if not channel or not isinstance(obj, dict):
            raise ConnectorError(
                "slack raw item missing channel/object envelope",
                failure_class=FailureClass.schema_change,
                external_id=raw_item.external_id,
                external_type=raw_item.external_type,
            )
        kind = raw_item.external_type
        cid, aid = raw_item.connector_id, raw_item.source_account_id
        channel_kind = payload.get("channel_kind")
        if kind == "channel":
            rec = norm.record_from_channel(cid, aid, obj)
        elif kind in ("message", "file_share"):
            rec = norm.record_from_message(
                cid, aid, channel, obj, channel_kind=channel_kind,
                is_reply=False,
            )
            if kind == "file_share":
                rec.external_type = "file_share"
        elif kind == "thread_reply":
            rec = norm.record_from_message(
                cid, aid, channel, obj, channel_kind=channel_kind,
                is_reply=True,
            )
        else:
            raise ConnectorError(
                f"unsupported slack object type {kind!r}",
                failure_class=FailureClass.schema_change,
                external_id=raw_item.external_id, external_type=kind,
            )
        rec.external_type = raw_item.external_type
        rec.external_id = raw_item.external_id
        rec.external_revision = raw_item.external_revision
        if raw_item.deleted:
            rec.deleted = True
        return [rec]

    def acknowledge(self, plan: SyncPlan, page: FetchPage) -> dict[str, Any]:
        # Called only on the success path (before finalize). Safe to drop
        # webhook tombstone hints that this page already emitted.
        self._clear_emitted_tombstones()
        return page.cursor_after or dict(plan.cursor_before or {})
