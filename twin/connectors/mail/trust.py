"""Source-trust calibration for professional email (v0.6 §69–70).

Email is more conservative than Slack: automated notifications and
newsletters sit below the review threshold and are marked derived so they
never count as independent evidence of the object they notify about.
"""

from __future__ import annotations

from typing import Any

from .classification import (
    CLASS_CALENDAR,
    CLASS_CODE_REVIEW,
    CLASS_HUMAN,
    CLASS_NEWSLETTER,
    CLASS_NOTIFICATION,
    CLASS_RECEIPT,
    CLASS_SECURITY,
    CLASS_SUPPORT,
    CLASS_TRANSACTIONAL,
    classify_message,
)

TRUST_HUMAN = 0.65
TRUST_REPLY = 0.60
TRUST_CALENDAR = 0.55
TRUST_AUTOMATED = 0.40
TRUST_NEWSLETTER = 0.35
TRUST_UNKNOWN = 0.50


def trust_for(external_type: str, payload: dict[str, Any]) -> tuple[float, str, str]:
    """Return ``(trust, author_kind, classification)``."""
    classification = payload.get("classification") or classify_message(
        subject=payload.get("subject") or "",
        body=payload.get("body_text") or payload.get("snippet") or "",
        from_addr=payload.get("from") or "",
        headers=payload.get("headers") or {},
    )
    if classification in (
        CLASS_NOTIFICATION, CLASS_CODE_REVIEW, CLASS_SECURITY,
        CLASS_TRANSACTIONAL, CLASS_RECEIPT, CLASS_SUPPORT,
    ):
        return TRUST_AUTOMATED, "automated", classification
    if classification == CLASS_NEWSLETTER:
        return TRUST_NEWSLETTER, "list", classification
    if classification == CLASS_CALENDAR:
        return TRUST_CALENDAR, "calendar", classification
    if external_type == "thread_message" or payload.get("is_reply"):
        return TRUST_REPLY, "human", CLASS_HUMAN
    if classification == CLASS_HUMAN:
        return TRUST_HUMAN, "human", CLASS_HUMAN
    return TRUST_UNKNOWN, "unknown", classification
