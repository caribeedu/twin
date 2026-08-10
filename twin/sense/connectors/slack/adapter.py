"""SlackConnector — ProfessionalConnector adapter for Slack (Web API).

Streams are dynamic, one per allowlisted channel:

 channel:{channel_id}

Each stream syncs channel history then thread replies. Configuration is an
EXPLICIT channel allowlist — workspace-wide ingest is never a default.

Incremental strategy: Slack ``ts`` watermark + lookback window, with
durable continuation cursors when the page budget is exhausted.

The watermark is the maximum *observed* Slack event ts across history
roots and thread replies in a completed window. Activity on roots older
than ``watermark - lookback`` is recovered via durable Events API hints
(``pending_threads``, ``pending_message_refreshes``, ``pending_tombstones``),
not by widening history alone.

Hint consumption is at-least-once: entries leave sync-state only inside
the framework finalize transaction.
"""

from __future__ import annotations

from datetime import datetime, timezone
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
DEFAULT_CHANNEL_METADATA_TTL_SECONDS = 3600


def _base_stream(stream: str) -> str:
    """Strip a backfill namespace ``backfill:{job}:{partition}:{base}`` down to
    the provider-native base stream. Continuous streams pass through unchanged.

    The historical time window travels via the SyncExecutionContext, not the
    stream name, so only the base ``channel:{id}`` is parsed here."""
    if stream.startswith("backfill:"):
        parts = stream.split(":", 3)   # backfill : job : partition : base
        if len(parts) != 4 or not parts[1] or not parts[2] or not parts[3]:
            raise ConnectorError(
                f"unknown backfill stream layout: {stream!r}",
                failure_class=FailureClass.schema_change,
            )
        return parts[3]
    return stream


def _parse_stream(stream: str) -> str:
    """'channel:{id}' (optionally backfill-namespaced) → channel id."""
    parts = _base_stream(stream).split(":", 1)
    if len(parts) != 2 or parts[0] != "channel" or not parts[1]:
        raise ConnectorError(
            f"unknown slack stream layout: {stream!r}",
            failure_class=FailureClass.schema_change,
        )
    return parts[1]


def _created_to_iso(created: Any) -> Optional[str]:
    """Slack channel ``created`` unix seconds → ``YYYY-MM-DD`` (UTC)."""
    try:
        ts = float(created)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


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
        self.channel_metadata_ttl_seconds = int(
            cfg.get("channel_metadata_ttl_seconds",
                    DEFAULT_CHANNEL_METADATA_TTL_SECONDS)
        )
        self.team_id: Optional[str] = cfg.get("team_id")
        self._client: Optional[SlackClient] = None
        self._channel_meta: dict[str, dict[str, Any]] = {}
        persisted = cfg.get("channel_metadata") or {}
        if isinstance(persisted, dict):
            self._channel_meta.update(persisted)
        self._store = None
        self._pending_hint_consumptions: list[dict[str, Any]] = []
        # thread_ts → hint generations snapshotted before conversations.replies
        self._threads_awaiting_hint_ack: dict[str, list[dict[str, Any]]] = {}
        # Channels refreshed via conversations.info during this adapter life
        self._channel_meta_fresh: set[str] = set()
        # user_id → display label (users.info cache for this adapter life)
        self._user_labels: dict[str, str] = {}

    def _in_backfill(self) -> bool:
        """True while replaying a historical backfill partition.

        Backfill must NOT mutate ``ConnectorInstance.configuration`` — the
        runtime snapshots config before the partition and raises an invariant
        violation if it changes (see ``run_backfill_partition``). ``team_id``
        and ``channel_metadata`` are continuous-sync caches, so during backfill
        we keep them in-memory for this run but skip persisting them."""
        ctx = getattr(self, "_execution_context", None)
        return bool(ctx and getattr(ctx, "mode", None) == "backfill")

    def attach_sync_hints(self, store) -> None:
        """Optional framework hook: read CAS-guarded sync-state hints."""
        self._store = store

    def collect_sync_hint_consumptions(self) -> list[dict[str, Any]]:
        return list(self._pending_hint_consumptions)

    def consume_sync_hints(self, store, hints: list[dict[str, Any]]) -> None:
        """Remove processed hint generations inside finalize's transaction.

        Uses a commit-free CAS so a conflict aborts the whole finalize
        instead of leaving evidence committed with hints still pending —
        or worse, committing hints out-of-band.
        """
        if not hints:
            return
        from twin.interfaces.runtime import SyncHintConflict

        ok = store.consume_connector_sync_hints_cas(self.instance.id, hints)
        if not ok:
            raise SyncHintConflict(
                f"sync-state hint CAS lost for connector {self.instance.id}"
            )
        self._pending_hint_consumptions = []
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
            auth_mode="slack_bot_token",
            affordances={
                "incremental_sync": True,
                "webhooks": True,
                "deletions": True,
                "attachments": False,   # metadata refs only in "threads": True,
            },
            supported_external_types=[
                "channel", "message", "thread_reply",
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
        meta = self._channel_meta.get(channel_id)
        if not meta:
            return "unknown"
        return norm.channel_kind_from_meta(meta)

    def _persist_channel_meta(self, channel_id: str, meta: dict[str, Any]) -> None:
        self._channel_meta[channel_id] = meta
        if self._store is None or self._in_backfill():
            return
        cfg = dict(self.instance.configuration or {})
        stored = dict(cfg.get("channel_metadata") or {})
        stored[channel_id] = {
            "id": meta.get("id") or channel_id,
            "name": meta.get("name") or meta.get("user"),
            "is_private": bool(meta.get("is_private")),
            "is_im": bool(meta.get("is_im")),
            "is_mpim": bool(meta.get("is_mpim")),
            "is_channel": bool(meta.get("is_channel",
                                         not meta.get("is_private")
                                         and not meta.get("is_im")
                                         and not meta.get("is_mpim"))),
            "validated_at": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"),
        }
        cfg["channel_metadata"] = stored
        if self.team_id:
            cfg["team_id"] = self.team_id
        self._store.update_connector_instance(self.instance.id, configuration=cfg)
        self.instance.configuration = cfg

    def _ensure_team_id(self) -> str:
        if self.team_id:
            return self.team_id
        identity = self.client.auth_test()
        tid = identity.get("team_id")
        if not tid:
            raise ConnectorError(
                "slack auth.test did not return team_id",
                failure_class=FailureClass.schema_change,
                human_action_required=True,
            )
        self.team_id = str(tid)
        if self._store is not None and not self._in_backfill():
            cfg = dict(self.instance.configuration or {})
            if cfg.get("team_id") != self.team_id:
                cfg["team_id"] = self.team_id
                self._store.update_connector_instance(
                    self.instance.id, configuration=cfg)
                self.instance.configuration = cfg
        return self.team_id

    def _metadata_stale(self, meta: dict[str, Any]) -> bool:
        validated_at = meta.get("validated_at")
        if not validated_at:
            return True
        try:
            dt = datetime.fromisoformat(str(validated_at).replace("Z", "+00:00"))
        except ValueError:
            return True
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        return age > self.channel_metadata_ttl_seconds

    def _resolve_channel(self, channel_id: str) -> dict[str, Any]:
        """Refresh channel kind via conversations.info before authorization.

        Persisted metadata is a cache with TTL, never an indefinite grant of
        ``public``. A failed refresh with stale/missing metadata fails closed.
        """
        if channel_id in self._channel_meta_fresh:
            return self._channel_meta[channel_id]

        cached = self._channel_meta.get(channel_id)
        try:
            info = self.client.conversations_info(channel_id)
        except ConnectorError as exc:
            if (cached and not self._metadata_stale(cached)
                    and norm.channel_kind_from_meta(cached) != "unknown"):
                # Non-expired verified metadata may bridge a transient outage.
                return cached
            # Keep transient provider failures as degraded/retryable — do not
            # collapse rate_limit/network/provider_error into unauthorized.
            if exc.failure_class in (
                FailureClass.rate_limit,
                FailureClass.network,
                FailureClass.provider_error,
            ):
                raise
            raise ConnectorError(
                f"cannot refresh metadata for channel {channel_id}: "
                f"{exc.failure_class.value}; refusing stale authorization",
                failure_class=FailureClass.authorization,
                human_action_required=True,
                retryable=exc.retryable,
            ) from exc

        if not info:
            if (cached and not self._metadata_stale(cached)
                    and norm.channel_kind_from_meta(cached) != "unknown"):
                return cached
            raise ConnectorError(
                f"slack channel {channel_id} not found or inaccessible",
                failure_class=FailureClass.authorization,
                human_action_required=True,
            )
        self._persist_channel_meta(channel_id, info)
        self._channel_meta_fresh.add(channel_id)
        return info

    def _assert_channel_authorized(self, channel_id: str) -> str:
        self._resolve_channel(channel_id)
        kind = self._channel_kind(channel_id)
        if kind in ("im", "mpim") and not self.include_dms:
            raise ConnectorError(
                f"channel {channel_id} is a DM/MPIM but "
                "include_direct_messages=false",
                failure_class=FailureClass.configuration,
                human_action_required=True,
            )
        if kind == "private" and not self.include_private:
            raise ConnectorError(
                f"channel {channel_id} is private but "
                "include_private_channels=false",
                failure_class=FailureClass.configuration,
                human_action_required=True,
            )
        if kind == "unknown":
            raise ConnectorError(
                f"channel {channel_id} kind could not be confirmed "
                "(refusing to treat as public)",
                failure_class=FailureClass.configuration,
                human_action_required=True,
            )
        return kind

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
        truncated = False
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
                    "channel_kind": norm.channel_kind_from_meta(ch),
                })
                if ch.get("id"):
                    self._channel_meta[ch["id"]] = ch
            pages += 1
            if not cursor:
                break
        else:
            if cursor:
                truncated = True
        if truncated:
            for row in out:
                row["list_truncated"] = True
        return out

    def estimate_backfill(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        known = {c["id"]: c for c in self.list_channels() if c.get("id")}
        for cid in self.channels:
            meta = known.get(cid) or {"id": cid}
            created = meta.get("created")
            out[f"channel:{cid}"] = {
                "name": meta.get("name"),
                "is_private": meta.get("is_private"),
                "channel_kind": meta.get("channel_kind") or self._channel_kind(cid),
                "num_members": meta.get("num_members"),
                "created": created,
                "created_iso": _created_to_iso(created),
            }
        return out

    def _channel_created(self, channel_id: str) -> Optional[float]:
        """Channel-creation unix ts, from cached metadata or a single
        ``conversations.info`` fetch. Best-effort: None if unknowable."""
        meta = self._channel_meta.get(channel_id)
        if not meta or meta.get("created") is None:
            try:
                info = self.client.conversations_info(channel_id)
            except ConnectorError:
                info = None
            if info:
                self._channel_meta[channel_id] = info
                meta = info
        try:
            return float(meta.get("created")) if meta else None
        except (TypeError, ValueError):
            return None

    def backfill_floor(self) -> Optional[str]:
        """Earliest date worth backfilling: the oldest channel-creation date
        across configured channels. A channel cannot hold messages before it
        existed, so anchoring here avoids planning years of empty month
        partitions (the planner's blind default is 10 years). Best-effort —
        returns None (caller keeps its default) if no dates are discoverable."""
        earliest: Optional[float] = None
        for cid in self.channels:
            created = self._channel_created(cid)
            if created is None:
                continue
            earliest = created if earliest is None else min(earliest, created)
        return _created_to_iso(earliest)

    def validate_credentials(self) -> ConnectorHealth:
        if not self.secret:
            return ConnectorHealth(status=HealthStatus.unauthorized,
                                   detail="no credential configured")
        token = self.secret
        if not (token.startswith("xoxb-") or token.startswith("xoxp-")):
            return ConnectorHealth(
                status=HealthStatus.degraded,
                detail=("token prefix is not xoxb-/xoxp-; expects a "
                        "Slack bot or user token (prefix is a signal only)"),
            )
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
        tid = identity.get("team_id")
        if tid:
            self.team_id = str(tid)
        detail = (f"authenticated as {user} on {team}"
                  + (f" (team_id={tid})" if tid else "")
                  + "; connector runs read-only Web API calls only; "
                  "credential privilege is unverified via auth.test — use a "
                  "least-privilege bot token (channels:history/read, users:read)")
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

    def _mark_hint(self, kind: str, entry: dict[str, Any]) -> None:
        hint = {"kind": kind, **entry}
        if hint not in self._pending_hint_consumptions:
            self._pending_hint_consumptions.append(hint)

    def _pending_meta(self, key: str) -> list[dict[str, Any]]:
        if self._store is None:
            return []
        state = self._store.get_connector_sync_state(self.instance.id)
        return list((state.metadata or {}).get(key) or []) if state else []

    def fetch_batch(
        self, plan: SyncPlan, cursor: Optional[dict[str, Any]],
    ) -> FetchPage:
        channel = plan.metadata["channel"]
        self._ensure_team_id()
        self._assert_channel_authorized(channel)
        self._pending_hint_consumptions = []
        self._threads_awaiting_hint_ack = {}
        # Force a fresh conversations.info for this stream's channel.
        self._channel_meta_fresh.discard(channel)

        base = cursor or plan.cursor_before or {}
        window_oldest = (
            base.get("window_oldest") if ss.in_progress(base)
            else self._window_oldest(base)
        )
        cur = ss.normalize_cursor(base, window_oldest=window_oldest)
        items: list[RawFetchItem] = []

        # Side-channel hints first — never advance history watermark from
        # tombstone original timestamps.
        for tomb in self._peek_tombstones(channel):
            items.append(tomb)
        items.extend(self._fetch_pending_refreshes(channel, cur))
        self._inject_pending_threads(channel, cur)

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

    def _resolve_tombstone_type(self, channel: str, ts: str,
                                hinted: Optional[str]) -> str:
        if hinted in ("message", "thread_reply"):
            return hinted
        if self._store is not None:
            for ext_type in ("thread_reply", "message"):
                prior = self._store.list_connector_records_for_object(
                    self.instance.id, ext_type, f"{channel}:{ts}",
                )
                if prior:
                    return ext_type
        return "message"

    def _peek_tombstones(self, channel: str) -> list[RawFetchItem]:
        items: list[RawFetchItem] = []
        for tomb in self._pending_meta("pending_tombstones"):
            if tomb.get("channel") != channel:
                continue
            ts = str(tomb.get("ts") or "0")
            ext_type = self._resolve_tombstone_type(
                channel, ts, tomb.get("external_type"),
            )
            self._mark_hint("tombstone", {"channel": channel, "ts": ts})
            obj: dict[str, Any] = {
                "ts": ts, "deleted": True, "subtype": "message_deleted",
                "text": "",
            }
            if tomb.get("thread_ts"):
                obj["thread_ts"] = tomb["thread_ts"]
            items.append(self._raw(
                channel, ext_type, f"{channel}:{ts}",
                norm.revision_for_deletion(ts), obj, deleted=True,
            ))
        return items

    def _inject_pending_threads(self, channel: str,
                                cursor: dict[str, Any]) -> None:
        thread_state = ss.substream_state(cursor, "threads")
        queue: list[str] = thread_state.setdefault("queue", [])
        seen: set[str] = set(thread_state.setdefault("seen", []))
        for hint in self._pending_meta("pending_threads"):
            if hint.get("channel") != channel:
                continue
            tts = str(hint.get("thread_ts") or "")
            if not tts:
                continue
            hint_id = hint.get("id") or (
                f"thread:{channel}:{tts}:{hint.get('event_ts') or ''}"
            )
            # Snapshot generations observed *before* replies fetch so a
            # concurrent webhook for the same thread is not consumed here.
            self._threads_awaiting_hint_ack.setdefault(tts, []).append({
                "id": hint_id,
                "channel": channel,
                "thread_ts": tts,
                "event_ts": hint.get("event_ts"),
            })
            # Force re-fetch even if previously seen — new replies may exist.
            seen.discard(tts)
            if tts not in queue:
                queue.append(tts)
        thread_state["seen"] = sorted(seen)
        thread_state["queue"] = queue

    def _fetch_pending_refreshes(
        self, channel: str, cursor: dict[str, Any],
    ) -> list[RawFetchItem]:
        items: list[RawFetchItem] = []
        for hint in self._pending_meta("pending_message_refreshes"):
            if hint.get("channel") != channel:
                continue
            target_ts = str(hint.get("ts") or "0")
            thread_ts = str(hint.get("thread_ts") or target_ts)
            hint_id = hint.get("id") or (
                f"edit:{channel}:{target_ts}:{hint.get('edited_ts') or target_ts}"
            )
            try:
                messages, _ = self.client.conversations_replies(
                    channel, thread_ts,
                )
            except ConnectorError:
                # Keep the hint for retry — do not mark consumption.
                continue
            self._mark_hint(
                "pending_message_refresh",
                {"id": hint_id, "channel": channel, "ts": target_ts,
                 "thread_ts": thread_ts,
                 "edited_ts": hint.get("edited_ts")},
            )
            for msg in messages:
                if str(msg.get("ts") or "") != target_ts:
                    continue
                is_reply = str(msg.get("thread_ts") or target_ts) != target_ts
                ext = "thread_reply" if is_reply else "message"
                items.append(self._raw(
                    channel, ext, f"{channel}:{target_ts}",
                    norm.revision_for_message(msg), msg,
                ))
                edited = (msg.get("edited") or {}).get("ts")
                if edited:
                    # Activity time, not the original message ts.
                    ss.bump_window_max(cursor, str(edited))
        return items
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
            if msg.get("subtype") == "message_deleted" or msg.get("deleted"):
                ts_del = str(msg.get("ts") or "0")
                thread_ts = msg.get("thread_ts")
                ext = "thread_reply" if (
                    thread_ts and str(thread_ts) != ts_del
                ) else "message"
                items.append(self._raw(
                    channel, ext, f"{channel}:{ts_del}",
                    norm.revision_for_deletion(ts_del), msg, deleted=True,
                ))
                # Deletion of an old message must not advance the watermark.
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
                # conversations.replies includes the parent. Skip it: history
                # (or a pending_message_refresh) owns the root. Re-emitting the
                # parent here races with volatile fields like reply_count and
                # causes revision_collision against the stored raw item.
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
            for entry in self._threads_awaiting_hint_ack.pop(thread_ts, []):
                self._mark_hint("pending_thread", entry)
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
                     "channel_kind": self._channel_kind(channel),
                     "team_id": self.team_id},
            occurred_at=norm._ts_to_iso(str(obj.get("ts") or "")),
            deleted=deleted,
        )

    def _ensure_team_id(self) -> None:
        if self.team_id:
            return
        try:
            identity = self.client.auth_test()
            tid = (identity or {}).get("team_id")
            if tid:
                self.team_id = tid
        except Exception:
            return

    def _user_label(self, user_id: Optional[str]) -> Optional[str]:
        """Resolve a Slack user id to a display name (cached)."""
        if not user_id or not str(user_id).startswith("U"):
            return None
        uid = str(user_id)
        if uid in self._user_labels:
            return self._user_labels[uid]
        try:
            info = self.client.users_info(uid)
        except Exception:
            info = None
        label = norm.display_label_for_user(info or {})
        if label:
            self._user_labels[uid] = label
            self._remember_identity(uid, label)
        return label

    def _remember_identity(self, user_id: str, label: str) -> None:
        """Best-effort: stamp display_name onto the external identity row."""
        store = self._store
        if store is None:
            return
        try:
            from twin.cognition.correlation.identity import upsert_external_identity
            from .normalize import actor_id as _actor_id

            self._ensure_team_id()
            aid = _actor_id(self.team_id, user_id)
            if not aid:
                return
            upsert_external_identity(
                store,
                actor_id=aid,
                source_account_id=self.account.id,
                vault_id=self.account.vault_id,
                source_owner=getattr(self.account.source_owner, "value",
                                     str(self.account.source_owner or "")),
                display_name=label,
                mapping_signals=["slack_users_info"],
            )
        except Exception:
            return

    def _labels_for_message(self, message: dict[str, Any]) -> dict[str, str]:
        labels: dict[str, str] = {}
        uids: set[str] = set()
        if message.get("user"):
            uids.add(str(message["user"]))
        for m in norm._MENTION.finditer(message.get("text") or ""):
            uids.add(m.group(1))
        for uid in uids:
            label = self._user_label(uid)
            if label:
                labels[uid] = label
        return labels

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
        team_id = payload.get("team_id") or self.team_id
        if kind == "channel":
            rec = norm.record_from_channel(cid, aid, obj, team_id=team_id)
        elif kind in ("message", "thread_reply"):
            self._ensure_team_id()
            meta = self._channel_meta.get(channel) or {}
            channel_label = meta.get("name")
            if channel_label:
                channel_label = f"#{channel_label}"
            labels = self._labels_for_message(obj)
            author = obj.get("user")
            rec = norm.record_from_message(
                cid, aid, channel, obj, channel_kind=channel_kind,
                is_reply=(kind == "thread_reply"), team_id=team_id,
                author_label=labels.get(str(author)) if author else None,
                channel_label=channel_label,
                user_labels=labels,
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
        # Cursor only. Sync-state hint removal happens in
        # consume_sync_hints inside _finalize_committed.
        return page.cursor_after or dict(plan.cursor_before or {})
