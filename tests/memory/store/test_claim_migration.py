"""Forward migration: legacy memories / memory_id → store_claims / claim_id."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from twin.store.store.sqlite import SqliteStore


def _seed_legacy(db: Path) -> None:
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE memories (
          id TEXT PRIMARY KEY, type TEXT, title TEXT, summary TEXT,
          domain TEXT DEFAULT 'technical', persona TEXT DEFAULT 'individual',
          sensitivity TEXT DEFAULT 'internal', confidence REAL DEFAULT 0.5,
          status TEXT DEFAULT 'candidate', valid_from TEXT, valid_until TEXT,
          created_at TEXT, updated_at TEXT, payload TEXT DEFAULT '{}',
          needs_review INTEGER DEFAULT 0, review_reason TEXT
        );
        CREATE TABLE evidence (
          id TEXT PRIMARY KEY, memory_id TEXT NOT NULL, percept_id TEXT,
          quote TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE memories_fts USING fts5(
          memory_id UNINDEXED, title, summary
        );
        INSERT INTO memories(id, type, title, summary, created_at, updated_at)
        VALUES('mem_legacy', 'fact', 'Legacy title', 'Legacy summary',
               '2020-01-01', '2020-01-01');
        INSERT INTO evidence(id, memory_id, percept_id, quote)
        VALUES('ev1', 'mem_legacy', 'p1', 'quote');
        INSERT INTO memories_fts(memory_id, title, summary)
        VALUES('mem_legacy', 'Legacy title', 'Legacy summary');
        """
    )
    con.commit()
    con.close()


def test_sqlite_upgrades_memories_to_store_claims(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    _seed_legacy(db)
    store = SqliteStore(str(db))
    names = {
        r[0]
        for r in store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )
    }
    assert "store_claims" in names
    assert "memories" not in names
    assert "store_claims_fts" in names
    ev_cols = {r[1] for r in store.conn.execute("PRAGMA table_info(evidence)")}
    assert "claim_id" in ev_cols
    assert "memory_id" not in ev_cols
    claim = store.get_claim("mem_legacy")
    assert claim is not None
    assert claim.title == "Legacy title"
    evidence = store.get_evidence("mem_legacy")
    assert len(evidence) == 1
    assert evidence[0].claim_id == "mem_legacy"


def test_sqlite_recovers_empty_store_claims_beside_memories(tmp_path: Path) -> None:
    db = tmp_path / "collision.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE memories (
          id TEXT PRIMARY KEY, type TEXT, title TEXT, summary TEXT,
          domain TEXT DEFAULT 'technical', persona TEXT DEFAULT 'individual',
          sensitivity TEXT DEFAULT 'internal', confidence REAL DEFAULT 0.5,
          status TEXT DEFAULT 'candidate', valid_from TEXT, valid_until TEXT,
          created_at TEXT, updated_at TEXT, payload TEXT DEFAULT '{}',
          needs_review INTEGER DEFAULT 0, review_reason TEXT
        );
        CREATE TABLE store_claims (
          id TEXT PRIMARY KEY, type TEXT, title TEXT, summary TEXT,
          domain TEXT DEFAULT 'technical', persona TEXT DEFAULT 'individual',
          sensitivity TEXT DEFAULT 'internal', confidence REAL DEFAULT 0.5,
          status TEXT DEFAULT 'candidate', valid_from TEXT, valid_until TEXT,
          created_at TEXT, updated_at TEXT, payload TEXT DEFAULT '{}',
          needs_review INTEGER DEFAULT 0, review_reason TEXT
        );
        INSERT INTO memories(id, type, title, summary, created_at, updated_at)
        VALUES('mem_y', 'fact', 'Kept', 's', '2020-01-01', '2020-01-01');
        """
    )
    con.commit()
    con.close()
    store = SqliteStore(str(db))
    assert store.get_claim("mem_y") is not None
    assert store.get_claim("mem_y").title == "Kept"
