"""Redact secrets from host-observed tool inputs before persistence."""

from __future__ import annotations

import re
from typing import Any

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("authorization", re.compile(
        r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?([^\s'\"]+)"
    )),
    ("bearer", re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._\-+=/]{8,})")),
    ("api_key", re.compile(
        r"(?i)((?:api[_-]?key|apikey)\s*[:=]\s*['\"]?)([^\s'\"]+)"
    )),
    ("token", re.compile(
        r"(?i)((?:access[_-]?token|refresh[_-]?token|token)\s*[:=]\s*['\"]?)([^\s'\"]+)"
    )),
    ("password", re.compile(
        r"(?i)((?:password|passwd|pwd)\s*[:=]\s*['\"]?)([^\s'\"]+)"
    )),
    ("secret", re.compile(
        r"(?i)((?:client[_-]?secret|secret)\s*[:=]\s*['\"]?)([^\s'\"]+)"
    )),
    ("cookie", re.compile(r"(?i)(cookie\s*[:=]\s*)(\S+)")),
    ("private_key", re.compile(
        r"(-----BEGIN [A-Z ]*PRIVATE KEY-----)(.*?)(-----END [A-Z ]*PRIVATE KEY-----)",
        re.S,
    )),
    ("signed_url", re.compile(
        r"(?i)([?&](?:X-Amz-Signature|Signature|sig|token)=)([^&\s'\"]+)"
    )),
]


def redact_text(text: str) -> tuple[str, list[str]]:
    """Return (redacted_text, categories_hit)."""
    if not text:
        return text, []
    out = text
    cats: list[str] = []
    for name, pat in _PATTERNS:
        if name == "private_key":
            new, n = pat.subn(r"\1[REDACTED]\3", out)
        elif name == "bearer":
            new, n = pat.subn("Bearer [REDACTED]", out)
        elif name == "authorization":
            new, n = pat.subn(r"\1\2[REDACTED]", out)
        else:
            new, n = pat.subn(r"\1[REDACTED]", out)
        if n:
            out = new
            if name not in cats:
                cats.append(name)
    return out, cats


def redact_payload(value: Any) -> tuple[Any, list[str]]:
    """Recursively redact string leaves in dict/list structures."""
    cats: list[str] = []
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key_l = str(k).lower()
            if any(s in key_l for s in (
                "password", "secret", "token", "authorization",
                "api_key", "apikey", "cookie", "private_key",
            )):
                out[k] = "[REDACTED]"
                if "secret_field" not in cats:
                    cats.append("secret_field")
                continue
            rv, rc = redact_payload(v)
            out[k] = rv
            for c in rc:
                if c not in cats:
                    cats.append(c)
        return out, cats
    if isinstance(value, list):
        items = []
        for v in value:
            rv, rc = redact_payload(v)
            items.append(rv)
            for c in rc:
                if c not in cats:
                    cats.append(c)
        return items, cats
    return value, cats
