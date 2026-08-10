"""Shared document model and normalize helpers."""
from __future__ import annotations

from twin.sense.connectors.documents import (
    DocumentRecord,
    DocumentRevision,
    records_from_document,
    revision_for_document,
)
from twin.sense.connectors.documents.normalize import (
    AUTHOR_LABEL_CONFIDENCE,
    MAX_CHUNK_CHARS,
    chunk_document_body,
)


def test_revision_changes_with_content_hash():
    a = {
        "external_id": "folder:r:a.md",
        "title": "A",
        "revision": {
            "revision_id": "t1.aaa",
            "content_hash": "aaa",
            "content": "one",
        },
    }
    b = dict(a)
    b["revision"] = {
        "revision_id": "t2.bbb",
        "content_hash": "bbb",
        "content": "two",
    }
    assert revision_for_document(a) != revision_for_document(b)


def test_records_emit_manifest_and_chunk_with_scoped_author_label():
    doc = DocumentRecord(
        provider="folder",
        external_id="folder:eng:rfc.md",
        title="RFC",
        path="rfc.md",
        parent_folder=".",
        revision=DocumentRevision(
            revision_id="2026-07-15T10:00:00Z.deadbeef",
            content_hash="deadbeef" * 4,
            modified_at="2026-07-15T10:00:00Z",
            author="Edu",
            mime_type="text/markdown",
            content="# Decision\n\nUse Postgres.\n",
            content_status="complete",
            content_available=True,
        ),
    )
    recs = records_from_document(
        connector_id="c", account_id="a", account_key="local",
        document=doc,
    )
    types = {r.external_type for r in recs}
    assert types == {"document_manifest", "document_revision_chunk"}
    manifest = next(r for r in recs if r.external_type == "document_manifest")
    chunk = next(r for r in recs if r.external_type == "document_revision_chunk")
    assert manifest.external_id == "folder:eng:rfc.md:manifest"
    assert chunk.external_id == "folder:eng:rfc.md:chunk:0"
    assert chunk.source_metadata["revision_id"] == "2026-07-15T10:00:00Z.deadbeef"
    assert chunk.source_metadata["lineage_root"] == "folder:eng:rfc.md"
    assert chunk.thread_key == "document:folder:local:folder:eng:rfc.md"
    assert "Postgres" in chunk.content
    # Front-matter label is NOT a global person / not auto-promoted.
    assert chunk.actor_ids == []
    assert manifest.actor_ids == []
    author = chunk.source_metadata["author"]
    assert author["author_label"] == "Edu"
    assert author["actor_id"] is None
    assert author["confidence"] == AUTHOR_LABEL_CONFIDENCE
    assert author["author_label_id"].startswith("document:folder:local:author-label:")


def test_email_author_promoted_to_mail_actor():
    doc = DocumentRecord(
        provider="folder",
        external_id="folder:eng:a.md",
        title="A",
        path="a.md",
        revision=DocumentRevision(
            revision_id="r1",
            content_hash="abc",
            author="edu@acme.com",
            content="# hi\n",
            mime_type="text/markdown",
        ),
    )
    recs = records_from_document(
        connector_id="c", account_id="a", account_key="vault1", document=doc,
    )
    chunk = next(r for r in recs if r.external_type == "document_revision_chunk")
    assert chunk.actor_ids == ["mail:edu@acme.com"]


def test_chunking_preserves_all_content_once():
    sections = []
    for i in range(80):
        sections.append(f"## Section-{i}-END\n\n" + (f"token-{i}-x " * 500))
    body = "\n".join(sections)
    assert len(body) > MAX_CHUNK_CHARS
    chunks = chunk_document_body(body)
    assert len(chunks) > 1
    joined = "".join(chunks)
    # Every section marker appears exactly once across the partition.
    for i in range(80):
        marker = f"## Section-{i}-END"
        assert joined.count(marker) == 1
        assert body.count(f"token-{i}-x ") == joined.count(f"token-{i}-x ")


def test_size_omitted_emits_manifest_only():
    doc = DocumentRecord(
        provider="folder",
        external_id="folder:eng:big.md",
        title="Big",
        path="big.md",
        revision=DocumentRevision(
            revision_id="r1",
            content_hash="hash",
            size_bytes=5_000_000,
            content="",
            content_status="size_omitted",
            content_available=False,
            content_truncated=True,
            mime_type="text/markdown",
        ),
    )
    recs = records_from_document(
        connector_id="c", account_id="a", account_key="local", document=doc,
    )
    assert len(recs) == 1
    assert recs[0].external_type == "document_manifest"
    assert recs[0].source_metadata["content_available"] is False
    assert recs[0].source_metadata["evidence_role"] == "artifact_metadata"
    assert recs[0].source_metadata["content_omitted_reason"] == "size_limit"


def test_chunk_shrink_emits_tombstones():
    doc = DocumentRecord(
        provider="folder",
        external_id="folder:eng:shrink.md",
        title="S",
        path="shrink.md",
        revision=DocumentRevision(
            revision_id="r2",
            content_hash="h2",
            content="# short\n",
            mime_type="text/markdown",
            content_status="complete",
        ),
    )
    recs = records_from_document(
        connector_id="c", account_id="a", account_key="local",
        document=doc, previous={"chunk_count": 3},
    )
    tombs = [r for r in recs if r.deleted]
    assert len(tombs) == 2  # chunks 1 and 2
    assert all(r.external_type == "document_revision_chunk" for r in tombs)


def test_decode_lossy_not_primary():
    doc = DocumentRecord(
        provider="folder",
        external_id="folder:eng:lossy.md",
        title="L",
        path="lossy.md",
        revision=DocumentRevision(
            revision_id="r1",
            content_hash="h",
            content="bad\ufffdtext",
            content_status="decode_lossy",
            decode_status="replacement_characters",
            mime_type="text/markdown",
        ),
    )
    recs = records_from_document(
        connector_id="c", account_id="a", account_key="local", document=doc,
    )
    chunk = next(r for r in recs if r.external_type == "document_revision_chunk")
    assert chunk.source_metadata["evidence_role"] == "operational"
    assert chunk.source_metadata["requires_review"] is True


def test_delete_tombstone_structural_artifacts():
    doc = DocumentRecord(
        provider="folder",
        external_id="folder:eng:gone.md",
        title="gone",
        path="gone.md",
        deleted=True,
        revision=DocumentRevision(
            revision_id="gone.deleted",
            content_hash="abc",
        ),
    )
    recs = records_from_document(
        connector_id="c", account_id="a", account_key="local",
        document=doc, previous={"chunk_count": 2},
    )
    assert any(r.deleted and r.external_type == "document_manifest" for r in recs)
    assert sum(
        1 for r in recs
        if r.deleted and r.external_type == "document_revision_chunk"
    ) == 2
    assert any(
        r.deleted and r.external_type == "document_revision"
        and r.external_id == "folder:eng:gone.md"
        for r in recs
    )
