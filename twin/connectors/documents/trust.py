"""Source-trust calibration for shared documents (v0.6 §69)."""

from __future__ import annotations

from typing import Any

TRUST_TECHNICAL_DOC = 0.80
TRUST_TRUNCATED = 0.65
TRUST_DELETED = 0.40
TRUST_UNKNOWN = 0.55


def trust_for_document(external_type: str, payload: dict[str, Any]) -> tuple[float, str]:
    if payload.get("deleted") or external_type.endswith("_deleted"):
        return TRUST_DELETED, "deleted"
    rev = payload.get("revision") or {}
    if isinstance(rev, dict) and rev.get("content_truncated"):
        return TRUST_TRUNCATED, "truncated"
    mime = str(
        (rev.get("mime_type") if isinstance(rev, dict) else None)
        or payload.get("mime_type")
        or ""
    ).lower()
    if mime.startswith("text/") or mime in (
        "text/markdown", "text/x-markdown", "application/json",
    ) or (payload.get("path") or "").endswith((".md", ".txt", ".rst", ".markdown")):
        return TRUST_TECHNICAL_DOC, "technical_doc"
    return TRUST_UNKNOWN, "document"
