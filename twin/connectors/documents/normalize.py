"""DocumentRecord → ConnectorRecord (v0.6 Phase 6)."""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from ..models import ConnectorRecord, idempotency_key
from .model import DocumentRecord
from .trust import trust_for_document

MAX_CONTENT_CHARS = 120_000  # hard ceiling for a single revision record


def _hash16(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def document_thread_key(provider: str, account_key: str, doc_id: str) -> str:
    return f"document:{provider}:{account_key}:{doc_id}"


def revision_for_document(doc: dict[str, Any]) -> str:
    rev = doc.get("revision") or {}
    if doc.get("deleted"):
        return f"{doc.get('external_id') or '?'}.deleted"
    rid = rev.get("revision_id") or rev.get("content_hash") or "0"
    return f"{rid}.{_hash16(str(rev.get('content_hash') or '') + str(doc.get('title') or ''))}"


def records_from_document(
    *,
    connector_id: str,
    account_id: str,
    account_key: str,
    document: DocumentRecord | dict[str, Any],
) -> list[ConnectorRecord]:
    data = document.to_dict() if isinstance(document, DocumentRecord) else dict(document)
    provider = data.get("provider") or "document"
    doc_id = str(data.get("external_id") or "?")
    title = data.get("title") or doc_id
    tkey = document_thread_key(provider, account_key, doc_id)
    rev = data.get("revision") or {}
    rev_id = str(rev.get("revision_id") or "0")
    content_hash = str(rev.get("content_hash") or "")
    deleted = bool(data.get("deleted"))

    if deleted:
        return [ConnectorRecord(
            connector_id=connector_id,
            source_account_id=account_id,
            external_type="document_revision",
            external_id=doc_id,
            external_revision=f"{doc_id}.deleted",
            idempotency_key=idempotency_key(
                provider, account_id, "document_revision", doc_id,
                f"{doc_id}.deleted",
            ),
            occurred_at=rev.get("modified_at"),
            actor_ids=[],
            participant_ids=[],
            project_hint=data.get("project_hint"),
            thread_key=tkey,
            artifact_refs=[{
                "kind": "document",
                "external_id": doc_id,
                "download_status": "deleted",
            }],
            content=f"Document deleted: {title}",
            deleted=True,
            source_metadata={
                "provider": provider,
                "account_key": account_key,
                "document_id": doc_id,
                "lineage_root": doc_id,
                "path": data.get("path"),
                "parent_folder": data.get("parent_folder"),
                "deleted": True,
            },
            confidentiality={"source_trust": 0.40},
        )]

    body = str(rev.get("content") or "")
    truncated = bool(rev.get("content_truncated"))
    if len(body) > MAX_CONTENT_CHARS:
        body = body[: MAX_CONTENT_CHARS - 1] + "…"
        truncated = True

    trust, kind = trust_for_document("document_revision", {
        **data, "revision": {**rev, "content_truncated": truncated},
    })
    actors: list[str] = []
    for key in ("author", "editor"):
        val = rev.get(key)
        if isinstance(val, str) and val.strip():
            if "@" in val:
                aid = f"mail:{val.lower()}"
            else:
                slug = val.strip().lower().replace(" ", "-")
                aid = f"document:{provider}:person:{slug}"
            if aid not in actors:
                actors.append(aid)

    external_revision = revision_for_document(data)
    header = [
        f"# {title}",
        f"Path: {data.get('path') or '?'}",
        f"Revision: {rev_id}",
        f"Hash: {content_hash}",
    ]
    if rev.get("modified_at"):
        header.append(f"Modified: {rev['modified_at']}")
    if rev.get("author"):
        header.append(f"Author: {rev['author']}")
    content = "\n".join(header) + "\n\n" + body

    return [ConnectorRecord(
        connector_id=connector_id,
        source_account_id=account_id,
        external_type="document_revision",
        external_id=doc_id,
        external_revision=external_revision,
        idempotency_key=idempotency_key(
            provider, account_id, "document_revision", doc_id, external_revision,
        ),
        occurred_at=rev.get("modified_at"),
        actor_ids=actors,
        participant_ids=list(actors),
        project_hint=data.get("project_hint") or data.get("parent_folder"),
        thread_key=tkey,
        artifact_refs=[
            {
                "kind": "document",
                "external_id": doc_id,
                "revision_id": rev_id,
                "content_hash": content_hash,
                "download_status": "inline",
            },
            {
                "kind": "document_revision",
                "external_id": rev_id,
                "download_status": "inline",
            },
        ],
        content=content,
        source_metadata={
            "provider": provider,
            "account_key": account_key,
            "document_id": doc_id,
            "lineage_root": doc_id,
            "revision_id": rev_id,
            "content_hash": content_hash,
            "path": data.get("path"),
            "parent_folder": data.get("parent_folder"),
            "permissions": data.get("permissions") or {},
            "mime_type": rev.get("mime_type"),
            "size_bytes": rev.get("size_bytes"),
            "content_truncated": truncated,
            "author_kind": kind,
            "evidence_role": "primary",
        },
        confidentiality={"source_trust": trust},
    )]
