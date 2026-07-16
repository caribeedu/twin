"""Slack API objects → ConnectorRecords (v0.6 §27–31).

One record per message (root or reply). Conventions:

- ``actor_ids``: ``slack:{user_id}`` — stable keys for identity resolution;
- ``thread_key``: ``slack:{channel}:{thread_ts}`` shared by a root and its
  replies — cross-source correlation anchors here;
- ``source_metadata.lineage_root``: informational root for the thread;
- ``external_revision``: ``edited.ts`` when present, else message ``ts`` —
  an edit becomes a NEW revision, never a silent overwrite;
- bots / notification-like posts carry ``derived=likely_notification``.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Optional

from ..models import ConnectorRecord
from .trust import is_notification_like, trust_for

MAX_CONTENT_CHARS = 4000
_GH_URL = re.compile(
    r"https?://github\.com/([\w.-]+/[\w.-]+)/(?:pull|issues)/(\d+)",
    re.I,
)
_GH_REPO_NUM = re.compile(
    r"\b([\w.-]+/[\w.-]+)(?:#|/pull/|/issues/)(\d+)\b",
    re.I,
)
_GH_PR = re.compile(r"\bPR\s*#(\d+)\b", re.I)
_GH_REPO = re.compile(r"\b([\w.-]+/[\w.-]+)\b")


def _hash8(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:8]


def revision_for_message(message: dict[str, Any]) -> str:
    edited = message.get("edited") or {}
    if isinstance(edited, dict) and edited.get("ts"):
        return f"{edited['ts']}.{_hash8(message.get('text') or '')}"
    return str(message.get("ts") or "0")


def revision_for_deletion(ts: str) -> str:
    """Tombstones must not reuse the live message revision (idempotency key)."""
    return f"{ts}.deleted"


def _actor(user: Optional[str]) -> Optional[str]:
    if not user:
        return None
    return f"slack:{user}"


def _clip(text: Optional[str]) -> str:
    text = (text or "").strip()
    if len(text) > MAX_CONTENT_CHARS:
        return text[: MAX_CONTENT_CHARS - 1] + "…"
    return text


def _github_refs(text: str) -> list[dict[str, str]]:
    """Extract GitHub issue/PR refs from URLs, ``org/repo#N``, or ``PR #N`` + repo."""
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(repo: str, number: str) -> None:
        key = (repo.lower(), number)
        if key in seen:
            return
        seen.add(key)
        refs.append({"repo": repo, "number": number})

    body = text or ""
    for m in _GH_URL.finditer(body):
        _add(m.group(1), m.group(2))
    for m in _GH_REPO_NUM.finditer(body):
        _add(m.group(1), m.group(2))
    if not refs:
        numbers = _GH_PR.findall(body)
        repos = [r for r in _GH_REPO.findall(body) if "/" in r]
        for number in numbers:
            for repo in repos:
                _add(repo, number)
    return refs

def _record(
    *, connector_id: str, account_id: str, external_type: str,
    external_id: str, external_revision: str, occurred_at: Optional[str],
    content: str, payload: dict[str, Any], channel: str,
    thread_key: Optional[str] = None, actors: Optional[list[str]] = None,
    lineage_root: Optional[str] = None, channel_kind: Optional[str] = None,
) -> ConnectorRecord:
    trust, kind = trust_for(external_type, payload)
    source_metadata: dict[str, Any] = {
        "channel": channel,
        "author_kind": kind,
        "ts": payload.get("ts"),
        "thread_ts": payload.get("thread_ts") or payload.get("ts"),
    }
    if channel_kind:
        source_metadata["channel_kind"] = channel_kind
    if lineage_root:
        source_metadata["lineage_root"] = lineage_root
    if kind == "bot" or is_notification_like(payload):
        source_metadata["derived"] = "likely_notification"
    refs = _github_refs(payload.get("text") or "")
    if refs:
        source_metadata["github_refs"] = refs
    return ConnectorRecord(
        connector_id=connector_id,
        source_account_id=account_id,
        external_type=external_type,
        external_id=external_id,
        external_revision=external_revision,
        occurred_at=occurred_at,
        actor_ids=actors or [],
        participant_ids=actors or [],
        project_hint=channel,
        thread_key=thread_key,
        artifact_refs=[{"kind": external_type, "channel": channel,
                        "ts": payload.get("ts")}],
        content=content,
        source_metadata=source_metadata,
        confidentiality={"source_trust": trust},
    )


def record_from_channel(connector_id: str, account_id: str,
                        channel: dict[str, Any]) -> ConnectorRecord:
    cid = channel.get("id") or "?"
    name = channel.get("name") or cid
    kind = ("private" if channel.get("is_private")
            else "im" if channel.get("is_im")
            else "mpim" if channel.get("is_mpim")
            else "public")
    return _record(
        connector_id=connector_id, account_id=account_id,
        external_type="channel", external_id=str(cid),
        external_revision=str(channel.get("updated") or channel.get("created")
                              or "0"),
        occurred_at=None,
        content=f"Slack channel #{name} ({kind})",
        payload=channel, channel=str(cid), channel_kind=kind,
    )


def record_from_message(connector_id: str, account_id: str, channel: str,
                        message: dict[str, Any], *,
                        channel_kind: Optional[str] = None,
                        is_reply: bool = False) -> ConnectorRecord:
    ts = str(message.get("ts") or "0")
    thread_ts = str(message.get("thread_ts") or ts)
    thread_key = f"slack:{channel}:{thread_ts}"
    user = message.get("user") or (message.get("bot_profile") or {}).get("name")
    actor = _actor(message.get("user"))
    if not actor and message.get("bot_id"):
        actor = f"slack:bot:{message['bot_id']}"
    ext_type = "thread_reply" if is_reply else "message"
    if message.get("files") and not (message.get("text") or "").strip():
        ext_type = "file_share"
    header = (f"Slack {'reply' if is_reply else 'message'} in {channel}"
              f" by {user or '?'}")
    body = _clip(message.get("text"))
    if message.get("subtype") == "message_deleted" or message.get("deleted"):
        body = body or "[deleted]"
    return _record(
        connector_id=connector_id, account_id=account_id,
        external_type=ext_type,
        external_id=f"{channel}:{ts}",
        external_revision=revision_for_message(message),
        occurred_at=_ts_to_iso(ts),
        content=f"{header}:\n{body}",
        payload=message, channel=channel, thread_key=thread_key,
        actors=[actor] if actor else [],
        lineage_root=thread_key, channel_kind=channel_kind,
    )


def _ts_to_iso(ts: str) -> Optional[str]:
    try:
        seconds = float(ts)
    except (TypeError, ValueError):
        return None
    from datetime import datetime, timezone
    return (datetime.fromtimestamp(seconds, tz=timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"))
