"""DocumentRecord → ConnectorRecord (v0.6 Phase 6).

Long documents become ``document_manifest`` + ``document_revision_chunk``
records — never silent truncation of primary evidence. Oversized bodies emit
manifest metadata only (``content_available=false``).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Optional

from ..models import ConnectorRecord, idempotency_key
from .model import DocumentRecord
from .trust import trust_for_document

# Soft budget per chunk. Prefer heading / paragraph / line boundaries.
MAX_CHUNK_CHARS = 120_000

# Front-matter author labels are not confirmed identities.
AUTHOR_LABEL_CONFIDENCE = 0.30


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


_HEADING_RE = re.compile(r"(?m)^(#{1,6}\s+\S.*)$")


def _split_by_size(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text] if text else []
    return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]


def _pack_parts(parts: list[str], max_chars: int) -> list[str]:
    """Pack parts into chunks; split oversized parts with finer strategies."""
    chunks: list[str] = []
    current = ""
    for part in parts:
        if not part:
            continue
        if len(part) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            # finer: paragraphs → lines → hard
            for piece in _split_oversized(part, max_chars):
                if current and len(current) + len(piece) + 1 > max_chars:
                    chunks.append(current)
                    current = piece
                elif current:
                    current = current + "\n" + piece if not current.endswith("\n") else current + piece
                else:
                    current = piece
            continue
        sep = "\n" if current and not current.endswith("\n") else ""
        if current and len(current) + len(sep) + len(part) > max_chars:
            chunks.append(current)
            current = part
        else:
            current = current + sep + part if current else part
    if current:
        chunks.append(current)
    return chunks or ([""] if not parts else [])


def _split_oversized(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    paras = re.split(r"\n{2,}", text)
    if len(paras) > 1:
        packed = _pack_parts(paras, max_chars)
        if all(len(p) <= max_chars for p in packed):
            return packed
    lines = text.splitlines(keepends=True)
    if len(lines) > 1:
        packed = _pack_parts(lines, max_chars)
        if all(len(p) <= max_chars for p in packed):
            return packed
    return _split_by_size(text, max_chars)


def chunk_document_body(text: str, *, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Partition document body preferring semantic boundaries.

    Order: headings → paragraphs → lines → hard character limit.
    """
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    matches = list(_HEADING_RE.finditer(text))
    if matches:
        sections: list[str] = []
        if matches[0].start() > 0:
            sections.append(text[:matches[0].start()])
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            sections.append(text[m.start():end])
        return _pack_parts(sections, max_chars)
    return _split_oversized(text, max_chars)


def _author_metadata(
    rev: dict[str, Any],
    *,
    provider: str,
    account_key: str,
    doc_id: str,
) -> tuple[list[str], dict[str, Any]]:
    """Separate author_label from resolved actor identity.

    Email → ``mail:{email}`` in actor_ids (entity resolution later).
    Plain labels stay account-scoped metadata with low confidence — never
    promoted to global person ids.
    """
    actors: list[str] = []
    author_meta: dict[str, Any] = {}
    raw = rev.get("author") or rev.get("editor")
    if not isinstance(raw, str) or not raw.strip():
        return actors, author_meta
    label = raw.strip()
    if "@" in label and " " not in label.split("@", 1)[0]:
        email = label.lower()
        actors.append(f"mail:{email}")
        author_meta = {
            "author_label": label,
            "actor_id": f"mail:{email}",
            "confidence": 0.85,
            "mapping_signal": "front_matter_author_email",
        }
    else:
        slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or "unknown"
        scoped = f"document:{provider}:{account_key}:author-label:{slug}"
        author_meta = {
            "author_label": label,
            "actor_id": None,
            "author_label_id": scoped,
            "confidence": AUTHOR_LABEL_CONFIDENCE,
            "mapping_signal": "front_matter_author",
            "document_id": doc_id,
        }
    return actors, author_meta


def _content_status(rev: dict[str, Any]) -> str:
    status = str(rev.get("content_status") or "").strip()
    if status:
        return status
    if rev.get("content_truncated"):
        return "size_omitted"
    return "complete"


def _tombstone(
    *,
    connector_id: str,
    account_id: str,
    external_type: str,
    external_id: str,
    revision: str,
    provider: str,
    account_key: str,
    thread_key: str,
    doc_id: str,
    content: str,
) -> ConnectorRecord:
    return ConnectorRecord(
        connector_id=connector_id,
        source_account_id=account_id,
        external_type=external_type,
        external_id=external_id,
        external_revision=revision,
        idempotency_key=idempotency_key(
            provider, account_id, external_type, external_id, revision,
        ),
        thread_key=thread_key,
        content=content,
        deleted=True,
        source_metadata={
            "provider": provider,
            "account_key": account_key,
            "document_id": doc_id,
            "lineage_root": doc_id,
            "deleted": True,
        },
        confidentiality={"source_trust": 0.40},
    )


def records_from_document(
    *,
    connector_id: str,
    account_id: str,
    account_key: str,
    document: DocumentRecord | dict[str, Any],
    previous: Optional[dict[str, Any]] = None,
) -> list[ConnectorRecord]:
    """Emit manifest + optional revision chunks; tombstone structural shrinks."""
    data = document.to_dict() if isinstance(document, DocumentRecord) else dict(document)
    provider = data.get("provider") or "document"
    doc_id = str(data.get("external_id") or "?")
    title = data.get("title") or doc_id
    tkey = document_thread_key(provider, account_key, doc_id)
    rev = data.get("revision") or {}
    rev_id = str(rev.get("revision_id") or "0")
    content_hash = str(rev.get("content_hash") or "")
    deleted = bool(data.get("deleted"))
    prev = previous or {}
    prev_chunk_count = int(prev.get("chunk_count") or 0)

    if deleted:
        records = [
            _tombstone(
                connector_id=connector_id,
                account_id=account_id,
                external_type="document_manifest",
                external_id=f"{doc_id}:manifest",
                revision=f"{doc_id}.manifest.deleted",
                provider=provider,
                account_key=account_key,
                thread_key=tkey,
                doc_id=doc_id,
                content=f"Document deleted: {title}",
            ),
        ]
        for index in range(prev_chunk_count):
            cid = f"{doc_id}:chunk:{index}"
            records.append(_tombstone(
                connector_id=connector_id,
                account_id=account_id,
                external_type="document_revision_chunk",
                external_id=cid,
                revision=f"{doc_id}.chunk{index}.deleted",
                provider=provider,
                account_key=account_key,
                thread_key=tkey,
                doc_id=doc_id,
                content=f"Document chunk removed {cid}",
            ))
        # Lineage anchor on the document id itself (deletion events / queries).
        records.append(_tombstone(
            connector_id=connector_id,
            account_id=account_id,
            external_type="document_revision",
            external_id=doc_id,
            revision=f"{doc_id}.deleted",
            provider=provider,
            account_key=account_key,
            thread_key=tkey,
            doc_id=doc_id,
            content=f"Document deleted: {title}",
        ))
        return records

    body = str(rev.get("content") or "")
    status = _content_status(rev)
    decode_status = str(rev.get("decode_status") or "ok")
    content_available = bool(rev.get("content_available", status not in (
        "size_omitted", "unsupported_mime", "read_failed",
    )))
    if status == "size_omitted" or not content_available:
        content_available = False

    actors, author_meta = _author_metadata(
        rev, provider=provider, account_key=account_key, doc_id=doc_id,
    )
    chunk_plan = chunk_document_body(body) if content_available and body else []
    # status "complete" with multi-chunk → report as chunked in metadata
    emit_status = status
    if content_available and len(chunk_plan) > 1 and status == "complete":
        emit_status = "chunked"
    chunk_count = len(chunk_plan)

    external_revision = revision_for_document(data)
    common_meta = {
        "provider": provider,
        "account_key": account_key,
        "document_id": doc_id,
        "lineage_root": doc_id,
        "revision_id": rev_id,
        "revision_lineage": rev_id,
        "content_hash": content_hash,
        "path": data.get("path"),
        "parent_folder": data.get("parent_folder"),
        "permissions": data.get("permissions") or {},
        "mime_type": rev.get("mime_type"),
        "size_bytes": rev.get("size_bytes"),
        "content_status": emit_status,
        "content_complete": content_available and status not in (
            "decode_lossy", "size_omitted", "read_failed",
        ),
        "content_available": content_available,
        "content_omitted_reason": (
            "size_limit" if status == "size_omitted"
            else ("unsupported_mime" if status == "unsupported_mime" else None)
        ),
        "decode_status": decode_status,
        "chunked": chunk_count > 1,
        "chunk_count": chunk_count,
        "identity_stability": "path_stable",
        **({"author": author_meta} if author_meta else {}),
    }

    records: list[ConnectorRecord] = []

    # --- document_manifest ---
    m_trust, m_kind = trust_for_document("document_manifest", {
        **data, "revision": {**rev, "content_status": emit_status},
    })
    if not content_available:
        evidence_role = "artifact_metadata"
    else:
        evidence_role = "index"
    manifest_lines = [
        f"# {title}",
        f"Path: {data.get('path') or '?'}",
        f"Revision: {rev_id}",
        f"Hash: {content_hash}",
        f"Content available: {content_available}",
        f"Status: {emit_status}",
        f"Chunks: {chunk_count}",
    ]
    if rev.get("modified_at"):
        manifest_lines.append(f"Modified: {rev['modified_at']}")
    if author_meta.get("author_label"):
        manifest_lines.append(f"Author label: {author_meta['author_label']}")
    if rev.get("size_bytes") is not None:
        manifest_lines.append(f"Size bytes: {rev['size_bytes']}")
    records.append(ConnectorRecord(
        connector_id=connector_id,
        source_account_id=account_id,
        external_type="document_manifest",
        external_id=f"{doc_id}:manifest",
        external_revision=f"{external_revision}.manifest",
        idempotency_key=idempotency_key(
            provider, account_id, "document_manifest", f"{doc_id}:manifest",
            f"{external_revision}.manifest",
        ),
        occurred_at=rev.get("modified_at"),
        actor_ids=list(actors),
        participant_ids=list(actors),
        project_hint=data.get("project_hint") or data.get("parent_folder"),
        thread_key=tkey,
        artifact_refs=[
            {
                "kind": "document_manifest",
                "external_id": doc_id,
                "revision_id": rev_id,
                "content_hash": content_hash,
                "chunk_count": chunk_count,
                "content_available": content_available,
            },
        ],
        content="\n".join(manifest_lines),
        source_metadata={
            **common_meta,
            "evidence_role": evidence_role,
            "author_kind": m_kind,
            "requires_review": decode_status == "replacement_characters",
        },
        confidentiality={"source_trust": m_trust},
    ))

    def _emit_chunk_tombstones(from_index: int) -> None:
        for index in range(from_index, prev_chunk_count):
            cid = f"{doc_id}:chunk:{index}"
            records.append(_tombstone(
                connector_id=connector_id,
                account_id=account_id,
                external_type="document_revision_chunk",
                external_id=cid,
                revision=f"{external_revision}.chunk{index}.deleted",
                provider=provider,
                account_key=account_key,
                thread_key=tkey,
                doc_id=doc_id,
                content=f"Document chunk removed {cid}",
            ))

    # Oversized / unavailable → manifest only; retire prior textual chunks.
    if not content_available or not chunk_plan:
        _emit_chunk_tombstones(0)
        return records

    lossy = status == "decode_lossy" or decode_status == "replacement_characters"
    chunk_evidence = "operational" if lossy else "primary"
    c_trust, c_kind = trust_for_document("document_revision_chunk", {
        **data, "revision": {**rev, "content_status": emit_status},
    })

    for chunk_index, chunk_body in enumerate(chunk_plan):
        chunk_hash = _hash16(chunk_body)
        chunk_id = f"{doc_id}:chunk:{chunk_index}"
        chunk_rev = f"{external_revision}.chunk{chunk_index}.{chunk_hash}"
        header = [
            f"# {title} (chunk {chunk_index})",
            f"Path: {data.get('path') or '?'}",
            f"Revision: {rev_id}",
            f"Hash: {content_hash}",
        ]
        content = "\n".join(header) + "\n\n" + chunk_body
        records.append(ConnectorRecord(
            connector_id=connector_id,
            source_account_id=account_id,
            external_type="document_revision_chunk",
            external_id=chunk_id,
            external_revision=chunk_rev,
            idempotency_key=idempotency_key(
                provider, account_id, "document_revision_chunk",
                chunk_id, chunk_rev,
            ),
            occurred_at=rev.get("modified_at"),
            actor_ids=list(actors),
            participant_ids=list(actors),
            project_hint=data.get("project_hint") or data.get("parent_folder"),
            thread_key=tkey,
            artifact_refs=[
                {
                    "kind": "document_revision_chunk",
                    "external_id": chunk_id,
                    "document_id": doc_id,
                    "revision_id": rev_id,
                    "chunk_index": chunk_index,
                    "content_hash": content_hash,
                    "chunk_content_hash": chunk_hash,
                },
                {"kind": "derived_from", "external_id": doc_id},
            ],
            content=content,
            source_metadata={
                **common_meta,
                "evidence_role": chunk_evidence,
                "author_kind": c_kind,
                "chunk_index": chunk_index,
                "chunk_content_hash": chunk_hash,
                "requires_review": lossy,
            },
            confidentiality={"source_trust": c_trust},
        ))

    if prev_chunk_count > chunk_count:
        _emit_chunk_tombstones(chunk_count)

    return records
