"""Local shared-folder scanner for the FolderConnector.

Walks configured roots (symlink dirs not followed), computes content hashes,
and emits DocumentRecords for new/changed/deleted paths. Future cloud
providers share the same DocumentRecord shape via DocumentProvider.

Authorization boundary: by default symlinks are rejected. When
``follow_symlinks=true``, targets must resolve inside the same root.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..documents.model import DocumentRecord, DocumentRevision
from ..documents.provider import DocumentProvider
from ..models import FailureClass
from ..protocol import ConnectorError

# Default text includes. JSON/YAML are recognized as text when explicitly
# included via ``include_globs`` — not watched by default.
DEFAULT_INCLUDE = ("**/*.md", "**/*.markdown", "**/*.txt", "**/*.rst")
DEFAULT_EXCLUDE = (
    "**/.git/**", "**/node_modules/**", "**/.twin/**", "**/__pycache__/**",
)
DEFAULT_MAX_FILE_BYTES = 2_000_000
DEFAULT_MAX_KNOWN_FILES = 50_000
TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".json", ".yaml", ".yml"}


def _iso_mtime(st_mtime: float) -> str:
    return datetime.fromtimestamp(st_mtime, tz=timezone.utc).strftime(
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
    """Best-effort front-matter author label (not a YAML parser).

    Treat result as an unconfirmed label — never a global person identity.
    """
    body = text.lstrip("\ufeff")
    if not body.startswith("---"):
        return None
    end = body.find("\n---", 3)
    if end == -1:
        return None
    for line in body[3:end].strip().splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        if k.strip().lower() == "author" and v.strip():
            return v.strip().strip("\"'")
    return None


def _permissions_for(path: Path, st: os.stat_result) -> dict[str, Any]:
    mode = st.st_mode
    # POSIX bits; Windows may not expose meaningful other/group — mark unknown.
    if os.name == "nt":
        return {
            "mode": "local_read",
            "permission_inspection": "not_evaluated",
            "platform": "nt",
        }
    return {
        "mode": "local_read",
        "permission_inspection": "posix_stat",
        "posix_mode": stat.filemode(mode),
        "world_readable": bool(mode & stat.S_IROTH),
        "group_readable": bool(mode & stat.S_IRGRP),
        "owner_readable": bool(mode & stat.S_IRUSR),
    }


def _open_file_nofollow(path: Path):
    """Open path for read, rejecting symlinks when O_NOFOLLOW is available."""
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    fd = os.open(path, flags)
    return os.fdopen(fd, "rb")


def _hash_file(
    path: Path, *, max_bytes: int, follow_symlinks: bool,
) -> tuple[str, int, bytes]:
    """Return (sha256_hex, size, head_bytes for text decode if under max)."""
    h = hashlib.sha256()
    size = 0
    head = bytearray()
    fh_ctx = open(path, "rb") if follow_symlinks else _open_file_nofollow(path)
    with fh_ctx as fh:
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


def validate_roots(
    roots: list[dict[str, Any]],
    *,
    allow_overlapping_roots: bool = False,
) -> None:
    """Fail closed on duplicate ids / nested roots unless explicitly allowed."""
    seen_ids: dict[str, str] = {}
    resolved: list[tuple[str, Path]] = []
    for root in roots:
        rid = str(root.get("id") or "").strip()
        if not rid:
            # label / path-derived ids are assigned later; empty explicit id
            # after normalization is still invalid when id key is present blank
            if "id" in root and not str(root.get("id") or "").strip():
                raise ConnectorError(
                    "folder root id must be non-empty",
                    failure_class=FailureClass.configuration,
                    human_action_required=True,
                )
            continue
        if rid in seen_ids:
            raise ConnectorError(
                f"duplicate folder root id {rid!r} "
                f"(paths {seen_ids[rid]!r} and {root.get('path')!r})",
                failure_class=FailureClass.configuration,
                human_action_required=True,
            )
        seen_ids[rid] = str(root.get("path") or "")
        path = Path(root.get("path") or "").expanduser()
        try:
            resolved.append((rid, path.resolve()))
        except OSError:
            resolved.append((rid, path))

    # Also reject duplicate derived ids among roots without explicit id
    derived: dict[str, str] = {}
    for root in roots:
        if root.get("id"):
            continue
        label = root.get("label")
        if label:
            did = str(label)
        else:
            path = Path(root.get("path") or "").expanduser()
            try:
                did = path.resolve().name or "root"
            except OSError:
                did = path.name or "root"
        if did in seen_ids or did in derived:
            raise ConnectorError(
                f"duplicate folder root id {did!r} (derived from path/label)",
                failure_class=FailureClass.configuration,
                human_action_required=True,
            )
        derived[did] = str(root.get("path") or "")

    if allow_overlapping_roots:
        return
    for i, (id_a, path_a) in enumerate(resolved):
        if not path_a.exists():
            continue
        for id_b, path_b in resolved[i + 1:]:
            if not path_b.exists():
                continue
            try:
                path_a.relative_to(path_b)
                nested = True
            except ValueError:
                try:
                    path_b.relative_to(path_a)
                    nested = True
                except ValueError:
                    nested = False
            if nested or path_a == path_b:
                raise ConnectorError(
                    f"overlapping folder roots {id_a!r} ({path_a}) and "
                    f"{id_b!r} ({path_b}); set allow_overlapping_roots=true "
                    f"to permit duplicate evidence",
                    failure_class=FailureClass.configuration,
                    human_action_required=True,
                )


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
        follow_symlinks: bool = False,
        max_known_files: int = DEFAULT_MAX_KNOWN_FILES,
        allow_overlapping_roots: bool = False,
        validate: bool = True,
    ) -> None:
        self.roots = list(roots or [])
        self.include_globs = tuple(include_globs or DEFAULT_INCLUDE)
        self.exclude_globs = tuple(exclude_globs or DEFAULT_EXCLUDE)
        self.max_file_bytes = int(max_file_bytes)
        self.follow_symlinks = bool(follow_symlinks)
        self.max_known_files = int(max_known_files)
        self.symlink_skips = 0
        if validate and self.roots:
            validate_roots(
                self.roots,
                allow_overlapping_roots=allow_overlapping_roots,
            )

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
            return str(root["id"]).strip()
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
        candidate = (base / rel)
        if candidate.is_symlink() and not self.follow_symlinks:
            return None
        try:
            path = candidate.resolve(strict=True)
            path.relative_to(base)
        except (ValueError, OSError):
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
        return self._record_for_path(root_id, base, path, rel=rel)

    def scan(
        self,
        root_id: str,
        *,
        cursor: Optional[dict[str, Any]] = None,
    ) -> tuple[list[DocumentRecord], dict[str, Any], bool]:
        """Full scan of one root (MVP — not page-budgeted).

        Each call walks the entire tree with ``os.walk(followlinks=False)``,
        hashes every matched file, and returns ``done=True``. Checkpoint
        ``known_files`` holds the inventory; ``max_known_files`` fails closed
        before the cursor can grow without bound.
        """
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
        self.symlink_skips = 0

        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            # Never descend into symlink directories (authorization boundary).
            dirnames[:] = [
                d for d in dirnames
                if not (Path(dirpath) / d).is_symlink()
            ]

            for name in filenames:
                path = Path(dirpath) / name
                rel = path.relative_to(base).as_posix()
                if self.exclude_globs and _match_any(rel, self.exclude_globs):
                    continue
                if self.include_globs and not _match_any(rel, self.include_globs):
                    continue

                is_link = path.is_symlink()
                if is_link:
                    if not self.follow_symlinks:
                        self.symlink_skips += 1
                        continue
                    try:
                        resolved = path.resolve(strict=True)
                        resolved.relative_to(base)
                    except (ValueError, OSError):
                        self.symlink_skips += 1
                        continue
                    if not resolved.is_file():
                        continue
                    read_path = resolved
                    follow = True
                else:
                    if not path.is_file():
                        continue
                    read_path = path
                    follow = False

                try:
                    digest, size, head = _hash_file(
                        read_path,
                        max_bytes=self.max_file_bytes,
                        follow_symlinks=follow,
                    )
                    st = read_path.stat()
                except OSError as exc:
                    # Broken / circular symlink or unreadable — skip, do not ingest.
                    if is_link:
                        self.symlink_skips += 1
                        continue
                    raise ConnectorError(
                        f"cannot read {rel}: {type(exc).__name__}",
                        failure_class=FailureClass.storage,
                        retryable=True,
                        external_id=rel,
                    ) from exc

                mtime = _iso_mtime(st.st_mtime)
                fingerprint = {
                    "content_hash": digest,
                    "size": size,
                    "modified_at": mtime,
                }
                seen[rel] = fingerprint
                if len(seen) > self.max_known_files:
                    raise ConnectorError(
                        f"folder root {root_id!r} exceeds max_known_files="
                        f"{self.max_known_files}; split roots or raise the limit",
                        failure_class=FailureClass.configuration,
                        human_action_required=True,
                    )
                prev = prior.get(rel)
                if prev and prev.get("content_hash") == digest:
                    continue
                changed.append(self._record_for_path(
                    root_id, base, read_path,
                    rel=rel,
                    digest=digest, size=size, head=head, mtime=mtime, st=st,
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
                        content_available=False,
                        content_status="read_failed",
                    ),
                ))

        next_cursor = {
            "known_files": seen,
            "scanned_at": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "scan_stats": {
                "files_matched": len(seen),
                "files_changed": len(changed),
                "files_deleted": len(deleted),
                "symlink_skips": self.symlink_skips,
                "mode": "full_scan",
            },
        }
        return changed + deleted, next_cursor, True

    def _record_for_path(
        self,
        root_id: str,
        base: Path,
        path: Path,
        *,
        rel: Optional[str] = None,
        digest: Optional[str] = None,
        size: Optional[int] = None,
        head: Optional[bytes] = None,
        mtime: Optional[str] = None,
        st: Optional[os.stat_result] = None,
    ) -> DocumentRecord:
        if rel is None:
            rel = path.relative_to(base).as_posix()
        if digest is None:
            digest, size, head = _hash_file(
                path, max_bytes=self.max_file_bytes,
                follow_symlinks=self.follow_symlinks,
            )
            st = path.stat()
            mtime = _iso_mtime(st.st_mtime)
        if st is None:
            st = path.stat()
        assert size is not None and head is not None and mtime is not None

        permissions = _permissions_for(path, st)
        content = ""
        author = None
        mime = "application/octet-stream"
        content_status = "complete"
        decode_status = "ok"
        content_available = True
        truncated_legacy = False

        suffix = path.suffix.lower()
        if suffix in TEXT_SUFFIXES:
            mime = {
                ".md": "text/markdown",
                ".markdown": "text/markdown",
                ".txt": "text/plain",
                ".rst": "text/x-rst",
                ".json": "application/json",
                ".yaml": "text/yaml",
                ".yml": "text/yaml",
            }.get(suffix, "text/plain")
            if size > self.max_file_bytes:
                # Hash covers full file; body omitted — metadata-only evidence.
                content_status = "size_omitted"
                content_available = False
                truncated_legacy = True
                content = ""
            else:
                try:
                    content = head.decode("utf-8")
                    decode_status = "ok"
                    content_status = "complete"
                except UnicodeDecodeError:
                    content = head.decode("utf-8", errors="replace")
                    decode_status = "replacement_characters"
                    content_status = "decode_lossy"
                    truncated_legacy = True
                author = _front_matter_author(content)
        else:
            content_status = "unsupported_mime"
            content_available = False
            truncated_legacy = True

        external_id = f"folder:{root_id}:{rel}"
        rev_id = f"{mtime}.{digest[:16]}"
        return DocumentRecord(
            provider="folder",
            external_id=external_id,
            title=path.stem.replace("-", " ").replace("_", " ").strip() or path.name,
            path=rel,
            parent_folder=str(Path(rel).parent).replace("\\", "/"),
            project_hint=root_id,
            permissions=permissions,
            revision=DocumentRevision(
                revision_id=rev_id,
                content_hash=digest,
                modified_at=mtime,
                author=author,
                editor=author,
                size_bytes=size,
                mime_type=mime,
                content=content,
                content_truncated=truncated_legacy,
                content_status=content_status,
                decode_status=decode_status,
                content_available=content_available,
            ),
            raw_metadata={
                "root_id": root_id,
                "absolute_path": str(path),
            },
        )
