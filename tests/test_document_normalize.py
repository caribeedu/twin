"""Unit tests for shared document model / normalize (Phase 6)."""

from __future__ import annotations

from twin.connectors.documents import (
    DocumentRecord,
    DocumentRevision,
    records_from_document,
    revision_for_document,
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


def test_records_preserve_document_and_revision_identity():
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
        ),
    )
    recs = records_from_document(
        connector_id="c", account_id="a", account_key="local",
        document=doc,
    )
    assert len(recs) == 1
    rec = recs[0]
    assert rec.external_type == "document_revision"
    assert rec.external_id == "folder:eng:rfc.md"
    assert rec.source_metadata["revision_id"] == "2026-07-15T10:00:00Z.deadbeef"
    assert rec.source_metadata["lineage_root"] == "folder:eng:rfc.md"
    assert rec.thread_key == "document:folder:local:folder:eng:rfc.md"
    assert "Postgres" in rec.content
    assert rec.actor_ids == ["document:folder:person:edu"]


def test_delete_tombstone():
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
        document=doc,
    )
    assert len(recs) == 1
    assert recs[0].deleted
    assert recs[0].external_revision.endswith(".deleted")
