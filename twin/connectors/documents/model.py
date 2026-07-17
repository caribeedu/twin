"""Provider-agnostic shared document model (v0.6 Phase 6 §43–44).

Adapters (local folder now; Drive / OneDrive / Notion later) normalize into
this shape before becoming ``ConnectorRecord``s. A Memory may keep pointing
at the revision that supported it after the live document changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class DocumentRevision:
    """One immutable content snapshot of a document."""
    revision_id: str
    content_hash: str
    modified_at: Optional[str] = None
    author: Optional[str] = None
    editor: Optional[str] = None
    size_bytes: Optional[int] = None
    mime_type: Optional[str] = None
    content: str = ""
    content_truncated: bool = False


@dataclass
class DocumentRecord:
    """Stable document identity + current revision payload."""
    provider: str
    external_id: str                    # stable doc id within account
    title: str
    path: Optional[str] = None          # provider path / relative path
    parent_folder: Optional[str] = None
    project_hint: Optional[str] = None
    permissions: dict[str, Any] = field(default_factory=dict)
    revision: Optional[DocumentRevision] = None
    deleted: bool = False
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        rev = self.revision
        return {
            "provider": self.provider,
            "external_id": self.external_id,
            "title": self.title,
            "path": self.path,
            "parent_folder": self.parent_folder,
            "project_hint": self.project_hint,
            "permissions": dict(self.permissions),
            "deleted": self.deleted,
            "revision": None if rev is None else {
                "revision_id": rev.revision_id,
                "content_hash": rev.content_hash,
                "modified_at": rev.modified_at,
                "author": rev.author,
                "editor": rev.editor,
                "size_bytes": rev.size_bytes,
                "mime_type": rev.mime_type,
                "content": rev.content,
                "content_truncated": rev.content_truncated,
            },
            "raw_metadata": dict(self.raw_metadata),
        }
