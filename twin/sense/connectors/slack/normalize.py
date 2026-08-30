"""Slack API objects → ConnectorRecords.

One record per message (root or reply). Conventions:

- ``actor_ids``: ``slack:{team_id}:{user_id}`` — workspace-qualified;
- ``thread_key``: ``slack:{team_id}:{channel}:{thread_ts}`` shared by a
 root and its replies — cross-source correlation anchors here;
- ``source_metadata.lineage_root``: informational root for the thread;
- ``external_revision``: ``edited.ts`` when present, else message ``ts`` —
 an edit becomes a NEW revision, never a silent overwrite;
- bots / notification-like posts carry ``derived=likely_notification``;
- file attachments appear as ``artifact_refs`` with ``download_status=
 metadata_only`` ( does not fetch file bytes).
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


def actor_id(team_id: Optional[str], user: Optional[str]) -> Optional[str]:
    if not user:
        return None
    if team_id:
        return f"slack:{team_id}:{user}"
    return f"slack:{user}"


def bot_actor_id(team_id: Optional[str], bot_id: str) -> str:
    if team_id:
        return f"slack:{team_id}:bot:{bot_id}"
    return f"slack:bot:{bot_id}"


def thread_key(team_id: Optional[str], channel: str, thread_ts: str) -> str:
    if team_id:
        return f"slack:{team_id}:{channel}:{thread_ts}"
    return f"slack:{channel}:{thread_ts}"


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


def _file_artifact_refs(message: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for f in message.get("files") or []:
        if not isinstance(f, dict):
            continue
        refs.append({
            "kind": "slack_file",
            "external_id": f.get("id"),
            "name": f.get("name") or f.get("title"),
            "mimetype": f.get("mimetype"),
            "size": f.get("size"),
            "mode": f.get("mode"),
            "permalink": f.get("permalink"),
            "download_status": "metadata_only",
        })
    return refs


def channel_kind_from_meta(channel: dict[str, Any]) -> str:
    """Fail closed: ``public`` only with positive confirmation."""
    if channel.get("is_im"):
        return "im"
    if channel.get("is_mpim"):
        return "mpim"
    if channel.get("is_private"):
        return "private"
    if channel.get("is_channel") is True and not channel.get("is_private"):
        return "public"
    if ("is_private" in channel and channel.get("is_private") is False
            and not channel.get("is_im") and not channel.get("is_mpim")):
        return "public"
    return "unknown"


def _record(
    *, connector_id: str, account_id: str, external_type: str,
    external_id: str, external_revision: str, occurred_at: Optional[str],
    content: str, payload: dict[str, Any], channel: str,
    thread_key_value: Optional[str] = None,
    actors: Optional[list[str]] = None,
    lineage_root: Optional[str] = None, channel_kind: Optional[str] = None,
    team_id: Optional[str] = None,
    artifact_refs: Optional[list[dict[str, Any]]] = None,
) -> ConnectorRecord:
    trust, kind = trust_for(external_type, payload)
    source_metadata: dict[str, Any] = {
        "channel": channel,
        "author_kind": kind,
        "ts": payload.get("ts"),
        "thread_ts": payload.get("thread_ts") or payload.get("ts"),
    }
    if team_id:
        source_metadata["team_id"] = team_id
        source_metadata["workspace_id"] = team_id
    if channel_kind:
        source_metadata["channel_kind"] = channel_kind
    if lineage_root:
        source_metadata["lineage_root"] = lineage_root
    if kind == "bot" or is_notification_like(payload):
        source_metadata["derived"] = "likely_notification"
        if lineage_root:
            source_metadata["notification_of"] = lineage_root
    refs = _github_refs(payload.get("text") or "")
    if refs:
        source_metadata["github_refs"] = refs
        if source_metadata.get("derived") == "likely_notification":
            # Prefer the first explicit GitHub object as the informational root.
            source_metadata.setdefault("notification_of", refs[0])
            source_metadata.setdefault("lineage_root", refs[0])
    arts = list(artifact_refs or [])
    if not arts:
        arts = [{"kind": external_type, "channel": channel,
                 "ts": payload.get("ts")}]
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
        thread_key=thread_key_value,
        artifact_refs=arts,
        content=content,
        source_metadata=source_metadata,
        confidentiality={"source_trust": trust},
    )


def record_from_channel(connector_id: str, account_id: str,
                        channel: dict[str, Any], *,
                        team_id: Optional[str] = None) -> ConnectorRecord:
    cid = channel.get("id") or "?"
    name = channel.get("name") or cid
    kind = channel_kind_from_meta(channel)
    return _record(
        connector_id=connector_id, account_id=account_id,
        external_type="channel", external_id=str(cid),
        external_revision=str(channel.get("updated") or channel.get("created")
                              or "0"),
        occurred_at=None,
        content=f"Slack channel #{name} ({kind})",
        payload=channel, channel=str(cid), channel_kind=kind, team_id=team_id,
    )


_MENTION = re.compile(r"<@(U[A-Z0-9]+)(?:\|([^>]+))?>")


def display_label_for_user(user_obj: dict[str, Any]) -> Optional[str]:
    """Pick the most human Slack label from a ``users.info`` payload."""
    if not isinstance(user_obj, dict):
        return None
    profile = user_obj.get("profile") or {}
    for candidate in (
        profile.get("display_name"),
        profile.get("real_name"),
        user_obj.get("real_name"),
        user_obj.get("name"),
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    return None


def _as_at(label: str) -> str:
    text = str(label or "").strip()
    if not text:
        return text
    return text if text.startswith("@") else f"@{text}"


def rewrite_mentions(text: str, labels: dict[str, str]) -> str:
    """Replace ``<@U…>`` / bare user ids with ``@Name`` when known."""
    if not text:
        return text

    def _sub(m: re.Match) -> str:
        uid, pipe = m.group(1), m.group(2)
        if pipe:
            return _as_at(pipe)
        label = labels.get(uid)
        return _as_at(label) if label else m.group(0)

    out = _MENTION.sub(_sub, text)
    # Also rewrite bare U… tokens that Slack puts in our own headers.
    for uid, label in sorted(labels.items(), key=lambda kv: -len(kv[0])):
        if uid and label and uid in out:
            out = out.replace(uid, _as_at(label))
    return out


def record_from_message(connector_id: str, account_id: str, channel: str,
                        message: dict[str, Any], *,
                        channel_kind: Optional[str] = None,
                        is_reply: bool = False,
                        team_id: Optional[str] = None,
                        author_label: Optional[str] = None,
                        channel_label: Optional[str] = None,
                        user_labels: Optional[dict[str, str]] = None) -> ConnectorRecord:
    ts = str(message.get("ts") or "0")
    thread_ts = str(message.get("thread_ts") or ts)
    tkey = thread_key(team_id, channel, thread_ts)
    user = message.get("user") or (message.get("bot_profile") or {}).get("name")
    actor = actor_id(team_id, message.get("user"))
    if not actor and message.get("bot_id"):
        actor = bot_actor_id(team_id, message["bot_id"])
    ext_type = "thread_reply" if is_reply else "message"
    labels = dict(user_labels or {})
    if user and author_label:
        labels.setdefault(str(user), author_label)
    # Source text always uses @user / #channel — never bare Slack ids.
    if author_label:
        who = _as_at(author_label)
    else:
        who = user or "?"
    if channel_label:
        where = (
            channel_label if str(channel_label).startswith("#")
            else f"#{channel_label}"
        )
    else:
        where = channel
    header = (f"Slack {'reply' if is_reply else 'message'} in {where}"
              f" by {who}")
    body = _clip(message.get("text"))
    if message.get("subtype") == "message_deleted" or message.get("deleted"):
        body = body or "[deleted]"
    body = rewrite_mentions(body, labels)
    header = rewrite_mentions(header, labels)
    file_refs = _file_artifact_refs(message)
    artifact_refs = (
        [{"kind": ext_type, "channel": channel, "ts": ts}] + file_refs
    )
    rec = _record(
        connector_id=connector_id, account_id=account_id,
        external_type=ext_type,
        external_id=f"{channel}:{ts}",
        external_revision=revision_for_message(message),
        occurred_at=_ts_to_iso(ts),
        content=f"{header}:\n{body}",
        payload=message, channel=channel, thread_key_value=tkey,
        actors=[actor] if actor else [],
        lineage_root=tkey, channel_kind=channel_kind, team_id=team_id,
        artifact_refs=artifact_refs,
    )
    if author_label:
        rec.source_metadata["author_name"] = author_label
    if channel_label:
        rec.source_metadata["channel_name"] = channel_label
    if labels:
        rec.source_metadata["user_labels"] = labels
    return rec


def _ts_to_iso(ts: str) -> Optional[str]:
    try:
        seconds = float(ts)
    except (TypeError, ValueError):
        return None
    from datetime import datetime, timezone
    return (datetime.fromtimestamp(seconds, tz=timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"))
