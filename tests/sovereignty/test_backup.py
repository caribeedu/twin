"""Sovereignty backup create / validate / restore round-trip."""

from pathlib import Path

from twin.store.models import MemoryItem, MemoryStatus, MemoryType
from twin.store.store.sqlite import SqliteStore
from twin.interfaces.sovereignty.backup import create_backup, restore_sqlite_backup, validate_backup
from twin.interfaces.sovereignty.integrity import run_integrity_checks
from twin.sense.sensory.percept import Percept
from twin.clock import now_iso
from twin import ids


def test_backup_validate_and_sqlite_restore(store, tmp_path):
    p = Percept(
        percept_type="note", source_sensor="test",
        content="We decided on SQLite backups.",
        ingested_at=now_iso(), occurred_at=now_iso(),
        source_trust=0.9, source_scope="technical",
    ).seal()
    store.insert_percept(p)
    mem = MemoryItem(
        id=ids.memory_id(), type=MemoryType.decision,
        title="SQLite backups", summary="Use file copy + NDJSON export",
        domain="technical", confidence=0.9, status=MemoryStatus.confirmed,
    )
    store.insert_memory(mem)
    from twin.store.models import Evidence
    store.insert_evidence(Evidence(
        id=ids.evidence_id(), memory_id=mem.id, percept_id=p.id,
        quote="SQLite backups",
    ))

    dest = tmp_path / "backup1"
    manifest = create_backup(store, dest, copy_sqlite_db=store.path)
    assert manifest.counts.get("memories", 0) >= 1
    assert (dest / "manifest.json").is_file()
    assert (dest / "store.sqlite").is_file()

    report = validate_backup(dest)
    assert report["ok"] is True
    assert report["problems"] == []

    target = tmp_path / "restored.db"
    restored = restore_sqlite_backup(dest, target)
    assert restored["ok"] is True
    other = SqliteStore(target)
    try:
        assert other.get_memory(mem.id) is not None
        assert other.get_percept(p.id) is not None
    finally:
        other.close()


def test_integrity_flags_confirmed_without_evidence(store):
    mem = MemoryItem(
        id=ids.memory_id(), type=MemoryType.fact,
        title="No evidence", summary="Should flag",
        domain="technical", confidence=0.9, status=MemoryStatus.confirmed,
    )
    store.insert_memory(mem)
    report = run_integrity_checks(store)
    assert report["ok"] is False
    assert report["stats"]["confirmed_without_evidence"] >= 1
