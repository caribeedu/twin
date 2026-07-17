"""Local shared-folder scanner for the FolderConnector.

Walks configured roots, computes content hashes, and emits DocumentRecords
for new/changed/deleted paths. Future cloud providers share the same
DocumentRecord shape via DocumentProvider.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..documents.model import DocumentRecord, DocumentRevision
from ..documents.provider import DocumentProvider
from ..models import FailureClass
from ..protocol import ConnectorError

DEFAULT_INCLUDE = ("**/*.md", "**/*.markdown", "**/*.txt", "**/*.rst")
DEFAULT_EXCLUDE = (
    "**/.git/**", "**/node_modules/**", "**/.twin/**", "**/__pycache__/**",
)
DEFAULT_MAX_FILE_BYTES = 2_000_000
TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".json", ".yaml", ".yml"}


def _iso_mtime(path: Path) -> str:
    ts = path.stat().st_mtime
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _match_any(rel: str, patterns: tuple[str, ...] | list[str]) -> bool:
    """Match relative paths against globs (supports ``**``).

    ``**/*.md`` must also match root-level ``file.md`` (pathlib's match does
    not treat ``**`` as matching zero directories in that case).
    """
    text = rel.replace(os.sep, "/")
    name = Path(text).name
    path = Path(text)
    for pat in patterns:
        pat_n = pat.replace(os.sep, "/").strip()
        if not pat_n:
            continue
        try:
            if path.match(pat_n):
                return True
        except ValueError:
            pass
        if fnmatch.fnmatch(text, pat_n):
            return True
        # **/ext-pattern — allow zero directories before the final segment
        if pat_n.startswith("**/"):
            rest = pat_n[3:]
            # Only promote the trailing segment when it is a file pattern
            # (*.md), never directory wildcards like .git/**
            if "/" not in rest.rstrip("/"):
                try:
                    if Path(name).match(rest) or fnmatch.fnmatch(name, rest):
                        return True
                except ValueError:
                    pass
            try:
                if path.match(rest) or fnmatch.fnmatch(text, rest):
                    return True
            except ValueError:
                pass
        elif "/" not in pat_n:
            if fnmatch.fnmatch(name, pat_n) or Path(name).match(pat_n):
                return True
    return False


def _front_matter_author(text: str) -> Optional[str]:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    for line in text[3:end].strip().splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        if k.strip().lower() == "author" and v.strip():
            return v.strip()
    return None


def _hash_file(path: Path, *, max_bytes: int) -> tuple[str, int, bytes]:
    """Return (sha256_hex, size, head_bytes for text decode if under max)."""
    h = hashlib.sha256()
    size = 0
    head = bytearray()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            h.update(chunk)
            size += len(chunk)
            if size <= max_bytes and len(head) < max_bytes:
                remain = max_bytes - len(head)
                head.extend(chunk[:remain])
    return h.hexdigest(), size, bytes(head)


class FolderScanner(DocumentProvider):
    """DocumentProvider backed by one or more local directory roots."""

    provider_type = "folder"

    def __init__(
        self,
        roots: list[dict[str, Any]],
        *,
        include_globs: Optional[list[str]] = None,
        exclude_globs: Optional[list[str]] = None,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    ) -> None:
        self.roots = list(roots or [])
        self.include_globs = tuple(include_globs or DEFAULT_INCLUDE)
        self.exclude_globs = tuple(exclude_globs or DEFAULT_EXCLUDE)
        self.max_file_bytes = int(max_file_bytes)

    def list_roots(self) -> list[dict[str, Any]]:
        out = []
        for root in self.roots:
            path = Path(root.get("path") or "").expanduser()
            label = root.get("label") or path.name or str(path)
            out.append({
                "id": self._root_id(root),
                "label": label,
                "path": str(path),
                "exists": path.is_dir(),
                "readable": path.is_dir() and os.access(path, os.R_OK),
            })
        return out

    def _root_id(self, root: dict[str, Any]) -> str:
        if root.get("id"):
            return str(root["id"])
        label = root.get("label")
        if label:
            return str(label)
        path = Path(root.get("path") or "").expanduser().resolve()
        return path.name or "root"

    def _root_by_id(self, root_id: str) -> dict[str, Any]:
        for root in self.roots:
            if self._root_id(root) == root_id:
                return root
        raise ConnectorError(
            f"unknown folder root: {root_id!r}",
            failure_class=FailureClass.configuration,
            human_action_required=True,
        )

    def get_document(self, external_id: str) -> Optional[DocumentRecord]:
        # external_id = folder:{root_id}:{rel_path}
        parts = external_id.split(":", 2)
        if len(parts) != 3 or parts[0] != "folder":
            return None
        root_id, rel = parts[1], parts[2]
        root = self._root_by_id(root_id)
        base = Path(root.get("path") or "").expanduser().resolve()
        path = (base / rel).resolve()
        try:
            path.relative_to(base)
        except ValueError:
            return None
        if not path.is_file():
            return DocumentRecord(
                provider="folder",
                external_id=external_id,
                title=Path(rel).name,
                path=rel,
                parent_folder=str(Path(rel).parent).replace("\\", "/"),
                deleted=True,
            )
        return self._record_for_path(root_id, base, path)

    def scan(
        self,
        root_id: str,
        *,
        cursor: Optional[dict[str, Any]] = None,
    ) -> tuple[list[DocumentRecord], dict[str, Any], bool]:
        root = self._root_by_id(root_id)
        base = Path(root.get("path") or "").expanduser()
        if not base.is_dir():
            raise ConnectorError(
                f"folder root not found or not a directory: {base}",
                failure_class=FailureClass.configuration,
                human_action_required=True,
            )
        base = base.resolve()
        prior = dict((cursor or {}).get("known_files") or {})
        seen: dict[str, dict[str, Any]] = {}
        changed: list[DocumentRecord] = []

        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(base).as_posix()
            if self.exclude_globs and _match_any(rel, self.exclude_globs):
                continue
            if self.include_globs and not _match_any(rel, self.include_globs):
                continue
            try:
                digest, size, head = _hash_file(
                    path, max_bytes=self.max_file_bytes,
                )
            except OSError as exc:
                raise ConnectorError(
                    f"cannot read {rel}: {type(exc).__name__}",
                    failure_class=FailureClass.storage,
                    retryable=True,
                    external_id=rel,
                ) from exc
            mtime = _iso_mtime(path)
            fingerprint = {
                "content_hash": digest,
                "size": size,
                "modified_at": mtime,
            }
            seen[rel] = fingerprint
            prev = prior.get(rel)
            if prev and prev.get("content_hash") == digest:
                continue
            changed.append(self._record_for_path(
                root_id, base, path,
                digest=digest, size=size, head=head, mtime=mtime,
            ))

        deleted: list[DocumentRecord] = []
        for rel in prior:
            if rel not in seen:
                deleted.append(DocumentRecord(
                    provider="folder",
                    external_id=f"folder:{root_id}:{rel}",
                    title=Path(rel).name,
                    path=rel,
                    parent_folder=str(Path(rel).parent).replace("\\", "/"),
                    deleted=True,
                    revision=DocumentRevision(
                        revision_id=f"{rel}.deleted",
                        content_hash=str((prior[rel] or {}).get("content_hash") or ""),
                        modified_at=None,
                    ),
                ))

        next_cursor = {
            "known_files": seen,
            "scanned_at": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        }
        return changed + deleted, next_cursor, True

    def _record_for_path(
        self,
        root_id: str,
        base: Path,
        path: Path,
        *,
        digest: Optional[str] = None,
        size: Optional[int] = None,
        head: Optional[bytes] = None,
        mtime: Optional[str] = None,
    ) -> DocumentRecord:
        rel = path.relative_to(base).as_posix()
        if digest is None:
            digest, size, head = _hash_file(path, max_bytes=self.max_file_bytes)
            mtime = _iso_mtime(path)
        assert size is not None and head is not None and mtime is not None
        truncated = size > self.max_file_bytes
        content = ""
        author = None
        mime = "application/octet-stream"
        if path.suffix.lower() in TEXT_SUFFIXES:
            mime = {
                ".md": "text/markdown",
                ".markdown": "text/markdown",
                ".txt": "text/plain",
                ".rst": "text/x-rst",
                ".json": "application/json",
                ".yaml": "text/yaml",
                ".yml": "text/yaml",
            }.get(path.suffix.lower(), "text/plain")
            if not truncated:
                try:
                    content = head.decode("utf-8")
                except UnicodeDecodeError:
                    content = head.decode("utf-8", errors="replace")
                    truncated = True
                author = _front_matter_author(content)
            else:
                # Hash covers full file; body omitted when over budget.
                truncated = True
        external_id = f"folder:{root_id}:{rel}"
        rev_id = f"{mtime}.{digest[:16]}"
        return DocumentRecord(
            provider="folder",
            external_id=external_id,
            title=path.stem.replace("-", " ").replace("_", " ").strip() or path.name,
            path=rel,
            parent_folder=str(Path(rel).parent).replace("\\", "/"),
            project_hint=root_id,
            permissions={"mode": "local_read", "world_readable": False},
            revision=DocumentRevision(
                revision_id=rev_id,
                content_hash=digest,
                modified_at=mtime,
                author=author,
                editor=author,
                size_bytes=size,
                mime_type=mime,
                content=content,
                content_truncated=truncated,
            ),
            raw_metadata={
                "root_id": root_id,
                "absolute_path": str(path),
            },
        )
