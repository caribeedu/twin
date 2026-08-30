"""DocumentProvider — future Drive / OneDrive / Notion adapters plug here.

 ships the local folder scanner against this cognitive contract.
Cloud providers implement the same surface without changing normalize.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

from .model import DocumentRecord


@runtime_checkable
class DocumentProvider(Protocol):
    """Technical adapter surface for shared documents.

    Implementations must not decide Memory / Judgment — only fetch and
    normalize into ``DocumentRecord``.
    """

    provider_type: str

    def list_roots(self) -> list[dict[str, Any]]:
        """Discoverable containers (folders, drives, spaces)."""
        ...

    def scan(
        self,
        root_id: str,
        *,
        cursor: Optional[dict[str, Any]] = None,
    ) -> tuple[list[DocumentRecord], dict[str, Any], bool]:
        """Return changed/deleted docs, next cursor fragment, and done flag."""
        ...

    def get_document(self, external_id: str) -> Optional[DocumentRecord]:
        """Fetch one document by stable id (on-demand / reconcile)."""
        ...
