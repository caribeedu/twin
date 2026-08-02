"""Resolve opaque actor / channel ids to human labels at the source of text.

Slack ``U…`` → ``@Name``, ``C…`` → ``#channel``. Labels come from connector
``source_metadata`` (set at normalize) and ``external_identities.display_name``.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from ..sensory.percept import Percept

_SLACK_UID = re.compile(r"\b(U[A-Z0-9]{8,})\b")
_SLACK_CID = re.compile(r"\b(C[A-Z0-9]{8,})\b")
_MENTION = re.compile(r"<@(U[A-Z0-9]+)(?:\|([^>]+))?>")


def _as_at(label: str) -> str:
    text = str(label or "").strip()
    if not text:
        return text
    return text if text.startswith("@") else f"@{text}"


def _as_hash(label: str) -> str:
    text = str(label or "").strip()
    if not text:
        return text
    return text if text.startswith("#") else f"#{text}"


def _labels_from_meta(sm: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    raw = sm.get("user_labels") or {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k and v:
                out[str(k)] = str(v)
    author = sm.get("author_name")
    if author and sm.get("user"):
        out.setdefault(str(sm["user"]), str(author))
    return out


def _labels_from_percept(percept: Percept) -> dict[str, str]:
    sm = (percept.metadata or {}).get("source_metadata") or {}
    out = _labels_from_meta(sm if isinstance(sm, dict) else {})
    author = sm.get("author_name") if isinstance(sm, dict) else None
    if author:
        for actor in percept.actors or []:
            if ":U" in actor:
                uid = actor.rsplit(":", 1)[-1]
                if uid.startswith("U"):
                    out.setdefault(uid, str(author))
    return out


def _labels_from_store(store, actor_ids: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    if not hasattr(store, "find_external_identity"):
        return out
    for actor in actor_ids or []:
        try:
            parts = str(actor).split(":")
            if parts[0] != "slack" or len(parts) < 2:
                continue
            external_id = ":".join(parts[1:])
            hit = store.find_external_identity(
                provider="slack", external_id=external_id,
            )
            if hit and getattr(hit, "display_name", None):
                out[parts[-1]] = hit.display_name
        except Exception:
            continue
    return out


def _channel_labels_from_store(store, channel_ids: set[str]) -> dict[str, str]:
    """Map ``C…`` → ``#name`` via Slack connector cache / channel records."""
    out: dict[str, str] = {}
    if not channel_ids or not hasattr(store, "list_connector_instances"):
        return out
    try:
        for inst in store.list_connector_instances():
            if getattr(inst, "connector_type", None) != "slack":
                continue
            # Continuous-sync cache written by the Slack adapter.
            cfg = getattr(inst, "configuration", None) or {}
            cached = cfg.get("channel_metadata") or {}
            if isinstance(cached, dict):
                for cid, info in cached.items():
                    if cid not in channel_ids or cid in out:
                        continue
                    name = info.get("name") if isinstance(info, dict) else None
                    if name:
                        out[str(cid)] = _as_hash(str(name))
            for rec in store.list_connector_records(inst.id):
                if getattr(rec, "external_type", None) != "channel":
                    continue
                cid = str(getattr(rec, "external_id", "") or "")
                if cid not in channel_ids or cid in out:
                    continue
                sm = getattr(rec, "source_metadata", None) or {}
                name = sm.get("channel_name") or sm.get("name")
                if not name:
                    content = getattr(rec, "content", "") or ""
                    if "#" in content:
                        token = content.split("#", 1)[1].split()[0]
                        name = token.strip("()[],.")
                if name:
                    out[cid] = _as_hash(str(name).lstrip("#"))
    except Exception:
        return out
    return out


def labels_for_record(store, rec: Any) -> tuple[dict[str, str], dict[str, str]]:
    """Return (user_labels, channel_labels) for a connector record."""
    sm = getattr(rec, "source_metadata", None) or {}
    users = _labels_from_meta(sm if isinstance(sm, dict) else {})
    actors = list(getattr(rec, "actor_ids", None) or [])
    users.update(_labels_from_store(store, actors))
    channels: dict[str, str] = {}
    if isinstance(sm, dict):
        cid = sm.get("channel")
        cname = sm.get("channel_name")
        if cid and cname:
            channels[str(cid)] = _as_hash(str(cname))
    return users, channels


def rewrite_labels(
    text: str,
    *,
    user_labels: Optional[dict[str, str]] = None,
    channel_labels: Optional[dict[str, str]] = None,
) -> str:
    """Rewrite Slack ids / mentions in ``text`` to ``@Name`` / ``#channel``."""
    if not text:
        return text
    users = user_labels or {}
    channels = channel_labels or {}

    def _mention(m: re.Match) -> str:
        uid, pipe = m.group(1), m.group(2)
        if pipe:
            return _as_at(pipe)
        label = users.get(uid)
        return _as_at(label) if label else m.group(0)

    out = _MENTION.sub(_mention, text)
    # Longer ids first so prefixes never partially rewrite.
    for uid, label in sorted(users.items(), key=lambda kv: -len(kv[0])):
        if uid and label and uid in out:
            out = out.replace(uid, _as_at(label))
    for cid, label in sorted(channels.items(), key=lambda kv: -len(kv[0])):
        if cid and label and cid in out:
            out = out.replace(cid, _as_hash(label))
    return out


def humanize_actor_text(store, percept: Percept, text: str) -> str:
    """Rewrite Slack user / channel ids in percept text using known labels."""
    if not text:
        return text
    labels = _labels_from_percept(percept)
    labels.update(_labels_from_store(store, list(percept.actors or [])))
    sm = (percept.metadata or {}).get("source_metadata") or {}
    channels: dict[str, str] = {}
    if isinstance(sm, dict):
        channel_name = sm.get("channel_name")
        channel_id = sm.get("channel")
        if channel_id and channel_name:
            channels[str(channel_id)] = _as_hash(str(channel_name))
        # Also catch any other C… tokens via store channel records.
        for m in _SLACK_CID.finditer(text):
            channels.setdefault(m.group(1), "")
        filled = {k: v for k, v in channels.items() if v}
        missing = {k for k, v in channels.items() if not v}
        if missing:
            filled.update(_channel_labels_from_store(store, missing))
        channels = filled
    return rewrite_labels(text, user_labels=labels, channel_labels=channels)


def humanize_record_text(store, rec: Any, text: Optional[str] = None) -> str:
    """Humanize connector-record content (or ``text``) for briefs / dossiers."""
    raw = text if text is not None else (getattr(rec, "content", None) or "")
    if not raw:
        return raw
    users, channels = labels_for_record(store, rec)
    for m in _SLACK_CID.finditer(raw):
        channels.setdefault(m.group(1), "")
    missing = {k for k, v in channels.items() if not v}
    if missing:
        channels.update({k: v for k, v in _channel_labels_from_store(store, missing).items()})
    channels = {k: v for k, v in channels.items() if v}
    # Pull any bare U… from store identities if missing in metadata.
    bare = {m.group(1) for m in _SLACK_UID.finditer(raw) if m.group(1) not in users}
    if bare and hasattr(store, "find_external_identity"):
        for uid in bare:
            for ext in (uid, f"unknown:{uid}"):
                try:
                    hit = store.find_external_identity(provider="slack", external_id=ext)
                except Exception:
                    hit = None
                if hit and getattr(hit, "display_name", None):
                    users[uid] = hit.display_name
                    break
            # Also try TEAM:UID forms via list if available — best effort below.
    if bare and hasattr(store, "list_external_identities"):
        try:
            for ident in store.list_external_identities():
                if getattr(ident, "provider", None) != "slack":
                    continue
                dn = getattr(ident, "display_name", None)
                ext = str(getattr(ident, "external_id", "") or "")
                uid = ext.rsplit(":", 1)[-1]
                if dn and uid in bare:
                    users.setdefault(uid, dn)
        except Exception:
            pass
    return rewrite_labels(raw, user_labels=users, channel_labels=channels)


def actor_label_map(store, percept: Percept) -> dict[str, str]:
    labels = _labels_from_percept(percept)
    labels.update(_labels_from_store(store, list(percept.actors or [])))
    return labels
