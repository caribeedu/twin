"""Source-trust calibration for shared documents."""

from __future__ import annotations

from typing import Any

TRUST_TECHNICAL_DOC = 0.80
TRUST_TRUNCATED = 0.65
TRUST_MANIFEST = 0.70
TRUST_METADATA_ONLY = 0.55
TRUST_LOSSY = 0.50
TRUST_DELETED = 0.40
TRUST_UNKNOWN = 0.55


def trust_for_document(external_type: str, payload: dict[str, Any]) -> tuple[float, str]:
    if payload.get("deleted") or external_type.endswith("_deleted"):
        return TRUST_DELETED, "deleted"
    if external_type == "document_manifest":
        rev = payload.get("revision") or {}
        status = str(
            (rev.get("content_status") if isinstance(rev, dict) else None)
            or payload.get("content_status")
            or ""
        )
        if status in ("size_omitted", "unsupported_mime", "read_failed"):
            return TRUST_METADATA_ONLY, "artifact_metadata"
        return TRUST_MANIFEST, "manifest"
    rev = payload.get("revision") or {}
    status = ""
    decode = "ok"
    if isinstance(rev, dict):
        status = str(rev.get("content_status") or "")
        decode = str(rev.get("decode_status") or "ok")
        if rev.get("content_truncated") and not status:
            status = "size_omitted"
    if status == "decode_lossy" or decode == "replacement_characters":
        return TRUST_LOSSY, "decode_lossy"
    if status == "size_omitted":
        return TRUST_METADATA_ONLY, "size_omitted"
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
