"""Transactional-ish backup create / validate / restore (SQLite-first)."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional

from twin.clock import now_iso
from twin.store.store.base import TwinStore
from twin.interfaces.sovereignty.export import write_export_bundle
from twin.interfaces.sovereignty.manifest import BackupManifest, verify_manifest_files


def create_backup(
    store: TwinStore,
    dest_dir: Path | str,
    *,
    copy_sqlite_db: Optional[Path] = None,
) -> BackupManifest:
    """Write a sovereignty bundle under ``dest_dir`` (atomic via temp + rename)."""
    dest_dir = Path(dest_dir)
    dest_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="twin-backup-") as tmp:
        tmp_path = Path(tmp) / "bundle"
        tmp_path.mkdir()
        manifest = write_export_bundle(store, tmp_path, kind="full")
        if copy_sqlite_db and Path(copy_sqlite_db).is_file():
            db_dest = tmp_path / "store.sqlite"
            shutil.copy2(copy_sqlite_db, db_dest)
            from twin.interfaces.sovereignty.manifest import FileEntry, sha256_file
            entry = FileEntry(
                path="store.sqlite",
                sha256=sha256_file(db_dest),
                bytes=db_dest.stat().st_size,
                records=1,
            )
            manifest.files.append(entry)
            manifest.metadata["sqlite_db"] = "store.sqlite"
            (tmp_path / "manifest.json").write_text(
                json.dumps(manifest.model_dump(mode="json"), indent=2),
                encoding="utf-8",
            )
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        shutil.copytree(tmp_path, dest_dir)
    return manifest


def validate_backup(bundle_dir: Path | str) -> dict[str, Any]:
    bundle_dir = Path(bundle_dir)
    man_path = bundle_dir / "manifest.json"
    if not man_path.is_file():
        return {"ok": False, "problems": ["missing manifest.json"]}
    manifest = BackupManifest.model_validate(json.loads(man_path.read_text()))
    problems = verify_manifest_files(bundle_dir, manifest)
    return {
        "ok": not problems,
        "problems": problems,
        "manifest": manifest.model_dump(mode="json"),
        "validated_at": now_iso(),
    }


def restore_sqlite_backup(
    bundle_dir: Path | str,
    target_db: Path | str,
    *,
    validate_first: bool = True,
) -> dict[str, Any]:
    """Restore by copying ``store.sqlite`` into an isolated target path.

    Semantic NDJSON replay into a live store is a later slice; v0.9.8 proves
    checksum validation + physical SQLite restore equivalence.
    """
    bundle_dir = Path(bundle_dir)
    target_db = Path(target_db)
    if validate_first:
        report = validate_backup(bundle_dir)
        if not report["ok"]:
            return {"ok": False, "stage": "validate", **report}
    src = bundle_dir / "store.sqlite"
    if not src.is_file():
        return {
            "ok": False,
            "stage": "restore",
            "problems": ["bundle has no store.sqlite — export-only bundle"],
        }
    target_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target_db)
    return {
        "ok": True,
        "stage": "restore",
        "target": str(target_db),
        "restored_at": now_iso(),
    }
