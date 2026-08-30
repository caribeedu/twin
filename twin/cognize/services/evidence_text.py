"""Evidence quote hygiene for session-summary folds.

Session consolidation folds artifacts into an extractable percept. Machine
kind tags like ``[user_message]`` must not become the stored evidence quote
the review UI shows — use human speaker labels in the fold, and strip any
legacy kind tags from quotes at write time.
"""

from __future__ import annotations

import re

# Human labels for the extractable session_summary percept (not stored kinds).
SUMMARY_KIND_LABELS: dict[str, str] = {
    "user_message": "User",
    "assistant_result": "Assistant",
    "file": "File",
    "commit": "Commit",
    "doc": "Doc",
    "note": "Note",
    "file_context": "File",
    "project_context": "Project",
}

_KIND_TAG_RE = re.compile(
    r"\[(?:user_message|assistant_result|file|commit|doc|note|"
    r"file_context|project_context)\]\s*",
    re.IGNORECASE,
)
_SPACE_RE = re.compile(r"[ \t]{2,}")
_BLANK_RE = re.compile(r"\n{3,}")


def fold_summary_line(kind: str, note: str) -> str:
    """One dialogue/observation line for the session_summary percept body."""
    label = SUMMARY_KIND_LABELS.get(kind) or kind.replace("_", " ").strip().title()
    return f"{label}: {note}"


def sanitize_evidence_quote(quote: str) -> str:
    """Strip legacy ``[kind]`` fold markers from an evidence quote."""
    if not quote:
        return ""
    cleaned = _KIND_TAG_RE.sub("", str(quote))
    cleaned = _SPACE_RE.sub(" ", cleaned)
    cleaned = _BLANK_RE.sub("\n\n", cleaned)
    return cleaned.strip()
