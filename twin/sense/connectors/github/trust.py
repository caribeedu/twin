"""Source-trust calibration for GitHub objects.

Trust follows the object's lifecycle state and its author's nature, not the
platform: a merged PR is a team's final, versioned word; a bot comment is a
notification wearing a comment costume. This is an initial calibration —
corroboration and explicit user confirmation refine it downstream.

Bots land BELOW the low-trust threshold (0.65), so every review candidate
derived from them is born needing review — preparing the invariant that
a notification never counts as independent evidence of its source object.
"""

from __future__ import annotations

from typing import Any

TRUST_MERGED_PR = 0.95
TRUST_APPROVED_REVIEW = 0.90
TRUST_ISSUE_OR_PR_BODY = 0.80
TRUST_RELEASE = 0.80
TRUST_HUMAN_COMMENT = 0.75
TRUST_CHECK_SUMMARY = 0.70
TRUST_COMMIT = 0.85
TRUST_REPOSITORY = 0.80
TRUST_BOT = 0.50


def author_kind(user: dict[str, Any] | None) -> str:
    if not user:
        return "unknown"
    if user.get("type") == "Bot" or str(user.get("login", "")).endswith("[bot]"):
        return "bot"
    return "human"


def trust_for(external_type: str, payload: dict[str, Any]) -> tuple[float, str]:
    """(source_trust, author_kind) for one GitHub object."""
    kind = author_kind(payload.get("user") or payload.get("author")
                       or payload.get("owner"))
    if kind == "bot":
        return TRUST_BOT, kind

    if external_type == "pull_request":
        if payload.get("merged") or payload.get("merged_at"):
            return TRUST_MERGED_PR, kind
        return TRUST_ISSUE_OR_PR_BODY, kind
    if external_type == "review":
        if (payload.get("state") or "").upper() == "APPROVED":
            return TRUST_APPROVED_REVIEW, kind
        return TRUST_HUMAN_COMMENT, kind
    if external_type == "issue":
        return TRUST_ISSUE_OR_PR_BODY, kind
    if external_type in ("issue_comment", "review_comment"):
        return TRUST_HUMAN_COMMENT, kind
    if external_type == "commit":
        return TRUST_COMMIT, kind
    if external_type == "release":
        return TRUST_RELEASE, kind
    if external_type == "check_summary":
        return TRUST_CHECK_SUMMARY, kind
    if external_type == "repository":
        return TRUST_REPOSITORY, kind
    return 0.7, kind
