"""Shared email → ConnectorRecord normalization (v0.6 §32–37).

Gmail and Outlook share one cognitive model; only the technical adapters
differ. Conventions:

- ``actor_ids``: ``mail:{addr}`` (lowercased);
- ``thread_key``: ``mail:{provider}:{account}:{thread_id}``;
- ``external_revision``: provider etag / internalDate / lastModified;
- attachments are metadata-only artifact refs in Phase 4;
- classification + derived flags live in ``source_metadata``.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Optional

from ..models import ConnectorRecord
from .classification import is_memory_relevant
from .trust import trust_for

MAX_CONTENT_CHARS = 6000
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")


def _hash8(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:8]


def _clip(text: Optional[str]) -> str:
    text = (text or "").strip()
    if len(text) > MAX_CONTENT_CHARS:
        return text[: MAX_CONTENT_CHARS - 1] + "…"
    return text


def extract_address(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    m = _EMAIL.search(value)
    return m.group(0).lower() if m else value.strip().lower() or None


def actor_id(addr: Optional[str]) -> Optional[str]:
    extracted = extract_address(addr)
    if not extracted:
        return None
    return f"mail:{extracted}"


def thread_key(provider: str, account_key: str, thread_id: str) -> str:
    return f"mail:{provider}:{account_key}:{thread_id}"


def revision_for_message(payload: dict[str, Any]) -> str:
    for key in ("etag", "changeKey", "historyId", "internalDate",
                "lastModifiedDateTime", "receivedDateTime"):
        if payload.get(key):
            return f"{payload[key]}.{_hash8(payload.get('body_text') or payload.get('snippet') or '')}"
    return _hash8(payload.get("id") or payload.get("external_id") or "0")


def _attachment_refs(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for att in attachments or []:
        if not isinstance(att, dict):
            continue
        refs.append({
            "kind": "email_attachment",
            "external_id": att.get("attachment_id") or att.get("id"),
            "filename": att.get("filename") or att.get("name"),
            "mime_type": att.get("mime_type") or att.get("contentType"),
            "size": att.get("size") or 0,
            "download_status": att.get("download_status") or "metadata_only",
        })
    return refs


def record_from_message(
    *,
    connector_id: str,
    account_id: str,
    provider: str,
    account_key: str,
    message: dict[str, Any],
    external_type: str = "message",
) -> ConnectorRecord:
    msg_id = str(message.get("id") or message.get("external_id") or "?")
    thread_id = str(message.get("thread_id") or message.get("conversationId")
                    or message.get("threadId") or msg_id)
    subject = message.get("subject") or "(no subject)"
    from_addr = message.get("from") or message.get("from_addr") or ""
    authored = message.get("authored") or message.get("body_text") or message.get("snippet") or ""
    trust, kind, classification = trust_for(external_type, message)
    tkey = thread_key(provider, account_key, thread_id)
    actors = [a for a in [actor_id(from_addr)] if a]
    for field in ("to", "cc"):
        raw = message.get(field) or []
        if isinstance(raw, str):
            raw = [raw]
        for addr in raw:
            aid = actor_id(addr if isinstance(addr, str) else str(addr))
            if aid and aid not in actors:
                actors.append(aid)

    header = f"Email [{provider}] {subject}\nFrom: {from_addr}"
    body = _clip(authored)
    content = f"{header}\n\n{body}" if body else header

    source_metadata: dict[str, Any] = {
        "provider": provider,
        "account_key": account_key,
        "thread_id": thread_id,
        "classification": classification,
        "author_kind": kind,
        "label_ids": message.get("label_ids") or message.get("labelIds") or [],
        "folder_id": message.get("folder_id"),
        "internet_message_id": message.get("internet_message_id")
            or message.get("internetMessageId"),
        "in_reply_to": message.get("in_reply_to") or message.get("inReplyTo"),
        "has_quoted_history": bool(message.get("quoted")),
        "memory_relevant": is_memory_relevant(classification),
    }
    if kind in ("automated", "list") or not is_memory_relevant(classification):
        source_metadata["derived"] = "likely_notification"
    if message.get("is_reply"):
        source_metadata["is_reply"] = True

    artifacts = (
        [{"kind": external_type, "message_id": msg_id, "thread_id": thread_id}]
        + _attachment_refs(message.get("attachments") or [])
    )
    return ConnectorRecord(
        connector_id=connector_id,
        source_account_id=account_id,
        external_type=external_type,
        external_id=msg_id,
        external_revision=revision_for_message(message),
        occurred_at=message.get("occurred_at") or message.get("receivedDateTime")
            or message.get("internalDate_iso"),
        actor_ids=actors,
        participant_ids=actors,
        project_hint=message.get("folder_id") or (message.get("label_ids") or [None])[0],
        thread_key=tkey,
        artifact_refs=artifacts,
        content=content,
        source_metadata=source_metadata,
        confidentiality={"source_trust": trust},
    )
