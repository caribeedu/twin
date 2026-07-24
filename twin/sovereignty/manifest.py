"""Backup / export manifest."""

from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, Field

from twin.clock import now_iso

SCHEMA_VERSION = "twin-sovereignty-1"


class FileEntry(BaseModel):
    path: str
    sha256: str
    bytes: int = 0
    records: int = 0


class BackupManifest(BaseModel):
    schema_version: str = SCHEMA_VERSION
    created_at: str = Field(default_factory=now_iso)
    kind: str = "full"  # full | incremental | export
    store_backend: str = "sqlite"
    sections: list[str] = Field(default_factory=list)
    files: list[FileEntry] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    since: str = ""
    encrypted: bool = False
    secrets_included: bool = False
    notes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_manifest_files(root, manifest: BackupManifest) -> list[str]:
    """Return list of problems (empty = ok)."""
    from pathlib import Path

    root = Path(root)
    problems: list[str] = []
    if manifest.schema_version != SCHEMA_VERSION:
        problems.append(
            f"schema_version {manifest.schema_version} != {SCHEMA_VERSION}"
        )
    for entry in manifest.files:
        fp = root / entry.path
        if not fp.is_file():
            problems.append(f"missing file {entry.path}")
            continue
        digest = sha256_file(fp)
        if digest != entry.sha256:
            problems.append(f"checksum mismatch {entry.path}")
        size = fp.stat().st_size
        if entry.bytes and size != entry.bytes:
            problems.append(f"size mismatch {entry.path}")
    return problems
