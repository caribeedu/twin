"""Slack Events API receiver support (v0.6 §24 / Phase 3).

A delivery is a *hint*, never a source of truth. Valid events may:

1. nudge the scheduler with ``targeted_streams``;
2. record ``pending_tombstones`` for ``message_deleted``;
3. record ``pending_threads`` for replies on (possibly old) roots;
4. record ``pending_message_refreshes`` for ``message_changed``.

The payload is never normalized into canonical records. Polling fetches
the authoritative object. Hint consumption is at-least-once: adapters
remove entries only inside the durable finalize transaction.

Authentication is HMAC (``X-Slack-Signature``) against a dedicated
signing secret in the CredentialStore — never the bot token — with a
uniform 401 for every failure mode.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Optional

from ..sync_state_cas import add_targeted_streams, apply_sync_state

SEEN_EVENT_IDS_CAP = 200


class WebhookRejected(Exception):
    def __init__(self, status_code: int, reason: str):
        super().__init__(reason)
        self.status_code = status_code
        self.reason = reason


def verify_signature(secret: str, body: bytes, timestamp: Optional[str],
                     signature: Optional[str], *,
                     now: Optional[float] = None) -> bool:
    if not signature or not signature.startswith("v0=") or not timestamp:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    # reject stale/replayed deliveries (>5 minutes)
    if abs((now or time.time()) - ts) > 60 * 5:
        return False
    basestring = f"v0:{timestamp}:".encode("utf-8") + body
    expected = "v0=" + hmac.new(
        secret.encode("utf-8"), basestring, hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def targeted_streams(event: dict[str, Any],
                     configured_channels: set[str]) -> list[str]:
    """Map one event to streams the poller should visit. A webhook can
    never widen the allowlist."""
    channel = (event.get("channel")
               or (event.get("item") or {}).get("channel")
               or (event.get("message") or {}).get("channel"))
    if isinstance(channel, dict):
        channel = channel.get("id")
    if not channel or channel not in configured_channels:
        return []
    return [f"channel:{channel}"]


def infer_message_external_type(
    *, ts: str, thread_ts: Optional[str],
) -> str:
    if thread_ts and str(thread_ts) != str(ts):
        return "thread_reply"
    return "message"


def resolve_tombstone_type_from_store(
    store, connector_id: str, channel: str, ts: str,
) -> Optional[str]:
    """Fallback when the Events payload lacks previous_message threading."""
    external_id = f"{channel}:{ts}"
    for ext_type in ("thread_reply", "message"):
        prior = store.list_connector_records_for_object(
            connector_id, ext_type, external_id,
        )
        if prior:
            return ext_type
    return None


def set_webhook_secret(store, credentials, connector_id: str,
                       secret: str) -> str:
    from ..models import CredentialRef

    instance = store.get_connector_instance(connector_id)
    if instance is None:
        raise ValueError(f"connector {connector_id} not found")
    ref = CredentialRef(provider=getattr(credentials, "provider", "encrypted_file"),
                        scopes=["webhook:verify"])
    store.insert_credential_ref(ref)
    try:
        credentials.put(ref.id, secret)
        config = dict(instance.configuration or {})
        old_ref = config.get("webhook_secret_ref")
        config["webhook_secret_ref"] = ref.id
        store.update_connector_instance(connector_id, configuration=config)
    except Exception:
        try:
            credentials.delete(ref.id)
        except Exception:
            pass
        try:
            store.delete_credential_ref(ref.id)
        except Exception:
            pass
        raise
    if old_ref:
        try:
            credentials.delete(old_ref)
            store.delete_credential_ref(old_ref)
        except Exception:
            pass
    return ref.id


def _append_unique(pending: list[dict[str, Any]], entry: dict[str, Any],
                   *, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    identity = tuple(entry.get(k) for k in keys)
    for existing in pending:
        if tuple(existing.get(k) for k in keys) == identity:
            return pending
    pending.append(entry)
    return pending


def _remember_event_id(meta: dict[str, Any], event_id: Optional[str]) -> None:
    if not event_id:
        return
    seen = list(meta.get("seen_event_ids") or [])
    if event_id not in seen:
        seen.append(event_id)
    meta["seen_event_ids"] = seen[-SEEN_EVENT_IDS_CAP:]


def handle_slack_webhook(
    store, credentials, connector_id: str, *,
    body: bytes, timestamp: Optional[str], signature: Optional[str],
) -> dict[str, Any]:
    instance = store.get_connector_instance(connector_id)
    if instance is None or instance.connector_type != "slack":
        raise WebhookRejected(401, "unknown or unauthorized webhook target")
    ref = (instance.configuration or {}).get("webhook_secret_ref")
    secret = None
    if ref:
        try:
            secret = credentials.get(ref)
        except Exception:
            secret = None
    if not secret:
        raise WebhookRejected(401, "unknown or unauthorized webhook target")
    if not verify_signature(secret, body, timestamp, signature):
        raise WebhookRejected(401, "unknown or unauthorized webhook target")

    try:
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
    except (ValueError, UnicodeDecodeError):
        raise WebhookRejected(400, "invalid JSON payload")

    # URL verification challenge (Slack app setup) — echo the challenge
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    event_id = payload.get("event_id")
    inner = payload.get("event") if payload.get("type") == "event_callback" \
        else payload
    if not isinstance(inner, dict):
        return {"scheduled": [], "detail": "no event payload"}

    channels = set((instance.configuration or {}).get("channels") or [])
    streams = targeted_streams(inner, channels)
    event_type = inner.get("type") or ""
    subtype = inner.get("subtype") or ""

    prior = store.get_connector_sync_state(connector_id)
    seen = list((prior.metadata or {}).get("seen_event_ids") or []) if prior else []
    if event_id and event_id in seen:
        return {"scheduled": [], "detail": "duplicate event_id"}

    def _apply_hints(state) -> None:
        meta = dict(state.metadata or {})
        _remember_event_id(meta, event_id)

        if subtype == "message_deleted" or event_type == "message_deleted":
            prev = inner.get("previous_message") or {}
            deleted_ts = (inner.get("deleted_ts") or inner.get("ts")
                          or prev.get("ts"))
            channel = inner.get("channel")
            if channel in channels and deleted_ts:
                thread_ts = prev.get("thread_ts") or inner.get("thread_ts")
                ext_type = infer_message_external_type(
                    ts=str(deleted_ts), thread_ts=thread_ts,
                )
                if thread_ts is None:
                    resolved = resolve_tombstone_type_from_store(
                        store, connector_id, channel, str(deleted_ts),
                    )
                    if resolved:
                        ext_type = resolved
                entry = {
                    "channel": channel,
                    "ts": str(deleted_ts),
                    "thread_ts": str(thread_ts) if thread_ts else None,
                    "external_type": ext_type,
                }
                pending = list(meta.get("pending_tombstones") or [])
                meta["pending_tombstones"] = _append_unique(
                    pending, entry, keys=("channel", "ts"),
                )
                meta["last_webhook_event"] = "message_deleted"

        elif subtype == "message_changed" or event_type == "message_changed":
            message = inner.get("message") or {}
            channel = inner.get("channel") or message.get("channel")
            ts = message.get("ts") or inner.get("ts")
            if channel in channels and ts:
                thread_ts = message.get("thread_ts") or ts
                entry = {
                    "channel": channel,
                    "ts": str(ts),
                    "thread_ts": str(thread_ts),
                }
                pending = list(meta.get("pending_message_refreshes") or [])
                meta["pending_message_refreshes"] = _append_unique(
                    pending, entry, keys=("channel", "ts"),
                )
                meta["last_webhook_event"] = "message_changed"

        elif event_type == "message" and subtype not in (
            "message_deleted", "message_changed", "message_replied",
        ):
            # New message or reply — schedule a targeted thread fetch when
            # this is a reply so roots outside the history lookback are not
            # missed.
            channel = inner.get("channel")
            ts = inner.get("ts")
            thread_ts = inner.get("thread_ts")
            if (channel in channels and ts and thread_ts
                    and str(thread_ts) != str(ts)):
                entry = {
                    "channel": channel,
                    "thread_ts": str(thread_ts),
                    "event_ts": str(ts),
                }
                pending = list(meta.get("pending_threads") or [])
                meta["pending_threads"] = _append_unique(
                    pending, entry, keys=("channel", "thread_ts"),
                )
                meta["last_webhook_event"] = "message_reply"
            elif channel in channels:
                meta["last_webhook_event"] = "message"

        state.metadata = meta

    apply_sync_state(store, connector_id, _apply_hints)

    if subtype == "message_deleted" or event_type == "message_deleted":
        channel = inner.get("channel")
        if channel in channels and not streams:
            streams = [f"channel:{channel}"]

    if not streams:
        return {"scheduled": [], "detail": "event not mapped to a configured stream"}

    add_targeted_streams(store, connector_id, streams, event=event_type or subtype)
    return {"scheduled": streams}
