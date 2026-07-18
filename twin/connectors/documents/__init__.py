"""Shared document cognitive layer (v0.6 Phase 6).

Provider adapters live alongside this package (``folder`` now; Drive /
OneDrive / Notion later) and normalize into ``DocumentRecord``.
"""

from .model import DocumentRecord, DocumentRevision
from .normalize import (
    chunk_document_body,
    records_from_document,
    revision_for_document,
)
from .provider import DocumentProvider

__all__ = [
    "DocumentProvider",
    "DocumentRecord",
    "DocumentRevision",
    "chunk_document_body",
    "records_from_document",
    "revision_for_document",
]
