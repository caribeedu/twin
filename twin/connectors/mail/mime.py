"""MIME body normalization helpers.

Split new authored content from quoted history / signatures when possible.
Never execute HTML; produce plain text + a sanitized HTML stub.
"""

from __future__ import annotations

import base64
import re
from email import message_from_bytes, policy
from email.message import EmailMessage, Message
from typing import Any, Optional

_QUOTE_MARKERS = (
    re.compile(r"^On .+wrote:\s*$", re.M | re.I),
    re.compile(r"^From:\s+.+$", re.M),
    re.compile(r"^-{2,}\s*Original Message\s*-{2,}", re.M | re.I),
    re.compile(r"^>{1,}\s?", re.M),
)
_SIG_MARKERS = (
    re.compile(r"^--\s*$", re.M),
    re.compile(r"^Sent from my (iPhone|iPad|Android)", re.M | re.I),
    re.compile(r"^Get Outlook for", re.M | re.I),
)
_HTML_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"(?is)<(script|style|iframe|object|embed).*?>.*?</\1>")


def b64url_decode(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def strip_html(html: str) -> str:
    text = _SCRIPT.sub(" ", html or "")
    text = _HTML_TAG.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def sanitize_html(html: str) -> str:
    """Legacy alias — NOT safe for UI render. Prefer ``untrusted_html_stub``."""
    return untrusted_html_stub(html)


def untrusted_html_stub(html: str) -> str:
    """Truncated HTML kept only as provenance — never treat as safe-to-render.

    Strips a few active tags for storage hygiene but is NOT an allowlist
    sanitizer. Downstream UIs must not render this field as trusted HTML.
    """
    cleaned = _SCRIPT.sub("", html or "")
    if len(cleaned) > 8000:
        cleaned = cleaned[:8000] + "…"
    return cleaned


def split_authored(body: str) -> dict[str, str]:
    """Best-effort split into authored / quoted / signature regions."""
    text = (body or "").replace("\r\n", "\n")
    authored = text
    quoted = ""
    signature = ""

    sig_cut: Optional[int] = None
    for pat in _SIG_MARKERS:
        m = pat.search(text)
        if m and (sig_cut is None or m.start() < sig_cut):
            sig_cut = m.start()
    if sig_cut is not None and sig_cut > 0:
        signature = text[sig_cut:].strip()
        text = text[:sig_cut].rstrip()

    quote_cut: Optional[int] = None
    for pat in _QUOTE_MARKERS[:3]:
        m = pat.search(text)
        if m and (quote_cut is None or m.start() < quote_cut):
            quote_cut = m.start()
    if quote_cut is not None and quote_cut > 0:
        quoted = text[quote_cut:].strip()
        authored = text[:quote_cut].rstrip()
    else:
        # leading ">" lines treated as quoted when majority
        lines = text.split("\n")
        quoted_lines = [ln for ln in lines if ln.startswith(">")]
        if lines and len(quoted_lines) >= max(3, len(lines) // 2):
            authored = "\n".join(
                ln for ln in lines if not ln.startswith(">")
            ).strip()
            quoted = "\n".join(quoted_lines).strip()
        else:
            authored = text.strip()

    return {
        "authored": authored,
        "quoted": quoted,
        "signature": signature,
    }


def parts_from_gmail_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Walk a Gmail API message payload into text/html/attachments."""
    text_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[dict[str, Any]] = []

    def walk(part: dict[str, Any]) -> None:
        mime = (part.get("mimeType") or "").lower()
        filename = part.get("filename") or ""
        body = part.get("body") or {}
        data = body.get("data")
        att_id = body.get("attachmentId")
        headers = {
            (h.get("name") or "").lower(): h.get("value")
            for h in (part.get("headers") or [])
            if isinstance(h, dict)
        }
        if filename or att_id:
            attachments.append({
                "filename": filename or "attachment",
                "mime_type": mime or "application/octet-stream",
                "size": int(body.get("size") or 0),
                "attachment_id": att_id,
                "content_id": headers.get("content-id"),
                "download_status": "metadata_only",
            })
        elif data and mime.startswith("text/plain"):
            try:
                text_parts.append(b64url_decode(data).decode("utf-8", "replace"))
            except Exception:
                pass
        elif data and mime.startswith("text/html"):
            try:
                html_parts.append(b64url_decode(data).decode("utf-8", "replace"))
            except Exception:
                pass
        for child in part.get("parts") or []:
            if isinstance(child, dict):
                walk(child)

    if payload:
        walk(payload)
    plain = "\n".join(text_parts).strip()
    html = "\n".join(html_parts).strip()
    if not plain and html:
        plain = strip_html(html)
    regions = split_authored(plain)
    return {
        "body_text": plain,
        "body_html_untrusted_stub": untrusted_html_stub(html) if html else "",
        "authored": regions["authored"],
        "quoted": regions["quoted"],
        "signature": regions["signature"],
        "attachments": attachments,
    }


def parts_from_raw_rfc822(raw: bytes) -> dict[str, Any]:
    msg: Message = message_from_bytes(raw, policy=policy.default)
    text_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[dict[str, Any]] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            filename = part.get_filename()
            ctype = part.get_content_type()
            if filename:
                payload = part.get_payload(decode=True) or b""
                attachments.append({
                    "filename": filename,
                    "mime_type": ctype,
                    "size": len(payload),
                    "download_status": "metadata_only",
                })
            elif ctype == "text/plain":
                try:
                    text_parts.append(part.get_content())
                except Exception:
                    pass
            elif ctype == "text/html":
                try:
                    html_parts.append(part.get_content())
                except Exception:
                    pass
    else:
        ctype = msg.get_content_type()
        try:
            content = msg.get_content()
        except Exception:
            content = ""
        if ctype == "text/html":
            html_parts.append(str(content))
        else:
            text_parts.append(str(content))
    plain = "\n".join(str(t) for t in text_parts).strip()
    html = "\n".join(str(h) for h in html_parts).strip()
    if not plain and html:
        plain = strip_html(html)
    regions = split_authored(plain)
    return {
        "body_text": plain,
        "body_html_untrusted_stub": untrusted_html_stub(html) if html else "",
        "authored": regions["authored"],
        "quoted": regions["quoted"],
        "signature": regions["signature"],
        "attachments": attachments,
        "internet_message_id": msg.get("Message-ID"),
        "in_reply_to": msg.get("In-Reply-To"),
        "references": msg.get("References"),
        "subject": msg.get("Subject"),
        "from": msg.get("From"),
    }
