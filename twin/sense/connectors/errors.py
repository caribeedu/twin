"""Error sanitization for persisted connector failures.

Adapter exceptions routinely embed URLs, request bodies, subjects, tokens and
addresses. Persisted error fields (DLQ ``last_error``, batch ``error``) must
carry enough to diagnose the *class* of failure without leaking content or
credentials into a plaintext column.
"""

from __future__ import annotations

import re

_REDACTIONS: list[tuple[re.Pattern[str], str]] = [
    # credentials in any common shape go first
    (re.compile(r"(?i)\b(authorization|bearer|token|secret|password|apikey|api_key)"
                r"\s*[:=]\s*\S+"), r"\1=[redacted]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "bearer [redacted]"),
    # URLs may carry hosts, paths, query params and embedded tokens
    (re.compile(r"https?://\S+"), "[url]"),
    # email addresses are PII
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
    # long opaque blobs (hashes, tokens, base64 payload fragments)
    (re.compile(r"[A-Za-z0-9+/_=-]{24,}"), "[blob]"),
]

MAX_SAFE_DETAIL = 200


def sanitize_error(exc: BaseException | str) -> str:
    """Type + redacted, truncated detail. Never raw content, never secrets."""
    if isinstance(exc, BaseException):
        prefix = type(exc).__name__
        detail = str(exc)
    else:
        prefix = "error"
        detail = str(exc)
    for pattern, repl in _REDACTIONS:
        detail = pattern.sub(repl, detail)
    detail = detail.replace("\n", " ").strip()
    if len(detail) > MAX_SAFE_DETAIL:
        detail = detail[: MAX_SAFE_DETAIL - 1] + "…"
    return f"{prefix}: {detail}" if detail else prefix
