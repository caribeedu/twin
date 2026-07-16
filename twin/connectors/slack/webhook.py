"""Slack Events API receiver support (v0.6 §24 / Phase 3).

A delivery is a *hint*, never a source of truth: the only effects of a
valid event are (1) nudging the scheduler with ``targeted_streams`` and
(2) recording pending tombstones for ``message_deleted`` so the next
poll can emit a durable deletion. The payload is never normalized into
canonical records.

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

EVENT_TYPES_MESSAGE = {
    "message",
    "message.channels",
    "message.groups",
    "message.im",
    "message.mpim",
}


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
               or (event.get("item") or {}).get("channel"))
    if isinstance(channel, dict):
        channel = channel.get("id")
    if not channel or channel not in configured_channels:
        return []
    return [f"channel:{channel}"]


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

    inner = payload.get("event") if payload.get("type") == "event_callback" \
        else payload
    if not isinstance(inner, dict):
        return {"scheduled": [], "detail": "no event payload"}

    channels = set((instance.configuration or {}).get("channels") or [])
    streams = targeted_streams(inner, channels)
    event_type = inner.get("type") or ""
    subtype = inner.get("subtype") or ""

    if subtype == "message_deleted" or event_type == "message_deleted":
        deleted_ts = (inner.get("deleted_ts") or inner.get("ts")
                      or (inner.get("previous_message") or {}).get("ts"))
        channel = inner.get("channel")
        if channel in channels and deleted_ts:
            def _apply(state) -> None:
                meta = dict(state.metadata or {})
                pending = list(meta.get("pending_tombstones") or [])
                entry = {"channel": channel, "ts": str(deleted_ts)}
                if entry not in pending:
                    pending.append(entry)
                meta["pending_tombstones"] = pending
                meta["last_webhook_event"] = "message_deleted"
                state.metadata = meta

            apply_sync_state(store, connector_id, _apply)
            if not streams:
                streams = [f"channel:{channel}"]

    if not streams:
        return {"scheduled": [], "detail": "event not mapped to a configured stream"}

    add_targeted_streams(store, connector_id, streams, event=event_type or subtype)
    return {"scheduled": streams}
