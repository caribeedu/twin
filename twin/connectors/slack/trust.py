"""Source-trust calibration for Slack objects.

Slack is more conservative than GitHub: informal channel chat is not a
team's final word. Bots and app notifications land below the review
threshold and are marked derived so they never count as independent
human evidence of the object they notify about.
"""

from __future__ import annotations

from typing import Any

TRUST_HUMAN_THREAD_ROOT = 0.70
TRUST_HUMAN_REPLY = 0.65
TRUST_FILE_SHARE = 0.60
TRUST_CHANNEL = 0.75
TRUST_BOT = 0.45
TRUST_UNKNOWN = 0.55


def author_kind(message: dict[str, Any]) -> str:
    if message.get("bot_id") or message.get("subtype") in (
        "bot_message", "bot_add", "bot_remove",
    ):
        return "bot"
    user = message.get("user") or ""
    # Slack apps sometimes set user to a bot user id with a bot_profile
    if message.get("bot_profile") or str(user).startswith("B"):
        if message.get("bot_profile") or message.get("bot_id"):
            return "bot"
    return "human" if user else "unknown"


def is_notification_like(message: dict[str, Any]) -> bool:
    """GitHub/Jira/CI bots posting into Slack are references, not new roots."""
    if author_kind(message) != "bot":
        return False
    text = (message.get("text") or "").lower()
    markers = ("pull request", "pr #", "github", "jira", "workflow",
               "deploy", "ci/", "merged", "opened a pull")
    return any(m in text for m in markers)


def trust_for(external_type: str, payload: dict[str, Any]) -> tuple[float, str]:
    kind = author_kind(payload)
    if kind == "bot":
        return TRUST_BOT, kind
    if external_type == "channel":
        return TRUST_CHANNEL, kind
    if external_type == "file_share":
        return TRUST_FILE_SHARE, kind
    if external_type == "thread_reply":
        return TRUST_HUMAN_REPLY, kind
    if external_type == "message":
        return TRUST_HUMAN_THREAD_ROOT, kind
    return TRUST_UNKNOWN, kind
