"""Email classification heuristics (v0.6 §37).

Classes are metadata for governance and extraction priority — never used to
infer ``source_owner``. Only cognitively relevant classes should become
memory candidates by default; newsletters/notifications stay searchable
artifacts.
"""

from __future__ import annotations

import re
from typing import Any, Optional

CLASS_HUMAN = "human_authored"
CLASS_NOTIFICATION = "automated_notification"
CLASS_NEWSLETTER = "newsletter"
CLASS_RECEIPT = "receipt"
CLASS_CALENDAR = "calendar"
CLASS_SECURITY = "security_alert"
CLASS_CODE_REVIEW = "code_review_notification"
CLASS_SUPPORT = "support_ticket"
CLASS_TRANSACTIONAL = "transactional"

_NOREPLY = re.compile(
    r"(no[-_.]?reply|do[-_.]?not[-_.]?reply|mailer[-_.]?daemon|notifications?@)",
    re.I,
)
_NEWSLETTER = re.compile(
    r"(unsubscribe|email preferences|view in browser|mailing list)",
    re.I,
)
_RECEIPT = re.compile(
    r"\b(receipt|invoice|order\s*#|payment\s+received|your\s+purchase)\b",
    re.I,
)
_CALENDAR = re.compile(
    r"(invitation:|updated invitation|canceled event|text/calendar|"
    r"has invited you|accepted:|declined:)",
    re.I,
)
_SECURITY = re.compile(
    r"\b(security alert|sign[- ]in attempt|new login|2fa|mfa|"
    r"password reset|suspicious activity)\b",
    re.I,
)
_CODE_REVIEW = re.compile(
    r"(github\.com|gitlab\.com|bitbucket\.org|pull request|merge request|"
    r"\[ci\]|codecov|dependabot)",
    re.I,
)
_SUPPORT = re.compile(
    r"\b(ticket\s*#|case\s*#|support request|helpdesk|zendesk)\b",
    re.I,
)


def classify_message(
    *, subject: str = "", body: str = "",
    from_addr: str = "", headers: Optional[dict[str, Any]] = None,
) -> str:
    headers = headers or {}
    blob = f"{subject}\n{body}\n{from_addr}"
    auto = str(headers.get("Auto-Submitted") or headers.get("auto-submitted") or "")
    list_unsub = headers.get("List-Unsubscribe") or headers.get("list-unsubscribe")
    precedence = str(headers.get("Precedence") or "").lower()

    if _CODE_REVIEW.search(blob) or _CODE_REVIEW.search(from_addr):
        return CLASS_CODE_REVIEW
    if _SECURITY.search(blob):
        return CLASS_SECURITY
    if _CALENDAR.search(blob) or "text/calendar" in blob.lower():
        return CLASS_CALENDAR
    if _RECEIPT.search(blob):
        return CLASS_RECEIPT
    if _SUPPORT.search(blob):
        return CLASS_SUPPORT
    if (list_unsub or precedence in ("bulk", "list")
            or _NEWSLETTER.search(blob)):
        return CLASS_NEWSLETTER
    if (auto and auto.lower() not in ("", "no")
            or _NOREPLY.search(from_addr)
            or _NOREPLY.search(blob[:500])):
        return CLASS_NOTIFICATION
    if headers.get("X-GitHub-Sender") or headers.get("X-GitLab-Event"):
        return CLASS_CODE_REVIEW
    return CLASS_HUMAN


def is_memory_relevant(classification: str) -> bool:
    """Default: only human-authored mail feeds memory candidates."""
    return classification == CLASS_HUMAN
