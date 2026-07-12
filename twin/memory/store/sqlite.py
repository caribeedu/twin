"""SQLite backend — zero-config store for dev, tests and offline fallback."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

from ... import ids
from ...sensory.percept import Percept
from ..crypto import ContentCodec, NullCodec
from ..embeddings import to_blob
from ..models import (
    Artifact, CognitiveSession, Entity, Evidence, MemoryItem, MemoryOperation,
    Project, Relation, ReviewBatch, ReviewFinding,
)
from .base import MemoryStore, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS percepts (
    id TEXT PRIMARY KEY,
    percept_type TEXT NOT NULL,
    source_sensor TEXT NOT NULL,
    occurred_at TEXT,
    ingested_at TEXT NOT NULL,
    actors TEXT NOT NULL DEFAULT '[]',
    content TEXT NOT NULL,
    content_refs TEXT NOT NULL DEFAULT '[]',
    attachments TEXT NOT NULL DEFAULT '[]',
    privacy_hints TEXT NOT NULL DEFAULT '{}',
    integrity TEXT NOT NULL DEFAULT '{}',
    metadata TEXT NOT NULL DEFAULT '{}',
    source_trust REAL NOT NULL DEFAULT 0.8,
    source_scope TEXT NOT NULL DEFAULT 'work',
    source_confidentiality TEXT NOT NULL DEFAULT 'internal',
    project_id TEXT,
    content_hash TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    domain TEXT NOT NULL,
    persona TEXT NOT NULL DEFAULT 'individual',
    sensitivity TEXT NOT NULL DEFAULT 'internal',
    confidence REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'candidate',
    valid_from TEXT,
    valid_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    needs_review INTEGER NOT NULL DEFAULT 0,
    review_reason TEXT,
    project_id TEXT,
    review_priority REAL NOT NULL DEFAULT 0,
    quality_score REAL NOT NULL DEFAULT 0,
    quality_flags TEXT NOT NULL DEFAULT '[]',
    impact TEXT NOT NULL DEFAULT 'medium',
    reviewed_at TEXT,
    review_batch_id TEXT,
    canonical_claim TEXT NOT NULL DEFAULT '{}',
    extractor_version TEXT NOT NULL DEFAULT '{}',
    last_reconciled_at TEXT,
    retrieval_count INTEGER NOT NULL DEFAULT 0,
    last_retrieved_at TEXT,
    deleted_at TEXT,
    deletion_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_memories_domain ON memories(domain);
CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    memory_id UNINDEXED, title, summary
);

CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    percept_id TEXT NOT NULL REFERENCES percepts(id),
    quote TEXT NOT NULL,
    evidence_type TEXT NOT NULL DEFAULT 'verbatim',
    directness REAL NOT NULL DEFAULT 1.0,
    source_trust REAL NOT NULL DEFAULT 0.8,
    independence_group TEXT,
    supports INTEGER NOT NULL DEFAULT 1,
    span_start INTEGER,
    span_end INTEGER,
    artifact_id TEXT,
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_evidence_memory ON evidence(memory_id);
CREATE INDEX IF NOT EXISTS idx_evidence_percept ON evidence(percept_id);

CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'generic',
    created_at TEXT NOT NULL,
    aliases TEXT NOT NULL DEFAULT '[]',
    canonical_id TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_name ON entities(name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS memory_entities (
    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    entity_id TEXT NOT NULL REFERENCES entities(id),
    PRIMARY KEY (memory_id, entity_id)
);

CREATE TABLE IF NOT EXISTS relations (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_id TEXT NOT NULL,
    memory_id TEXT,
    valid_from TEXT,
    valid_until TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_relations_subject ON relations(subject_id);
CREATE INDEX IF NOT EXISTS idx_relations_object ON relations(object_id);

CREATE TABLE IF NOT EXISTS embeddings (
    ref_id TEXT NOT NULL,
    ref_type TEXT NOT NULL,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY (ref_id, model)
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    aliases TEXT NOT NULL DEFAULT '[]',
    repos TEXT NOT NULL DEFAULT '[]',
    goals TEXT NOT NULL DEFAULT '[]',
    milestones TEXT NOT NULL DEFAULT '[]',
    open_questions TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_name ON projects(name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    client TEXT NOT NULL DEFAULT 'unknown',
    project_id TEXT,
    domain TEXT NOT NULL DEFAULT 'technical',
    task_profile TEXT NOT NULL DEFAULT 'general',
    initial_query TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    last_activity_at TEXT NOT NULL DEFAULT '',
    supplied_memory_ids TEXT NOT NULL DEFAULT '[]',
    pack_chars INTEGER NOT NULL DEFAULT 0,
    created_memory_ids TEXT NOT NULL DEFAULT '[]',
    consolidation_status TEXT NOT NULL DEFAULT 'none',
    consolidation_error TEXT,
    summary_percept_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id);

-- append-only: concurrent observers never rewrite each other's rows
CREATE TABLE IF NOT EXISTS session_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    ref TEXT,
    note TEXT,
    percept_id TEXT,
    observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_session_artifacts ON session_artifacts(session_id);

CREATE TABLE IF NOT EXISTS session_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'session',
    verdict TEXT NOT NULL,
    memory_id TEXT,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_session_feedback ON session_feedback(session_id);

CREATE TABLE IF NOT EXISTS firewall_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id TEXT NOT NULL,
    target_domain TEXT NOT NULL,
    rule TEXT NOT NULL,
    action TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- v0.3: artifacts, quality findings, review batches, audit log
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    external_id TEXT,
    source_system TEXT NOT NULL DEFAULT 'local',
    uri TEXT,
    content_hash TEXT,
    occurred_at TEXT,
    created_at TEXT NOT NULL,
    deleted_at TEXT,
    deletion_reason TEXT,
    content_destroyed INTEGER NOT NULL DEFAULT 0,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_artifacts_hash ON artifacts(content_hash);
CREATE INDEX IF NOT EXISTS idx_artifacts_system ON artifacts(source_system);

CREATE TABLE IF NOT EXISTS review_findings (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    type TEXT NOT NULL,
    related_memory_id TEXT,
    confidence REAL NOT NULL DEFAULT 0.5,
    reason TEXT NOT NULL DEFAULT '',
    suggested_action TEXT NOT NULL DEFAULT 'none',
    requires_human_review INTEGER NOT NULL DEFAULT 1,
    resolved INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'open',
    analyzer_version TEXT NOT NULL DEFAULT 'quality-v1',
    resolution_operation_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_findings_memory ON review_findings(memory_id);

CREATE TABLE IF NOT EXISTS artifact_percepts (
    artifact_id TEXT NOT NULL,
    percept_id TEXT NOT NULL,
    PRIMARY KEY (artifact_id, percept_id)
);

CREATE TABLE IF NOT EXISTS review_batches (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    query TEXT NOT NULL DEFAULT '{}',
    memory_ids TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    progress_total INTEGER NOT NULL DEFAULT 0,
    progress_reviewed INTEGER NOT NULL DEFAULT 0,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS memory_operations (
    id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'user',
    at TEXT NOT NULL,
    inputs TEXT NOT NULL DEFAULT '[]',
    output TEXT,
    before_state TEXT NOT NULL DEFAULT '{}',
    after_state TEXT NOT NULL DEFAULT '{}',
    undoable INTEGER NOT NULL DEFAULT 1,
    undone_at TEXT
);
"""


class SqliteStore(MemoryStore):
    def __init__(self, path: str | Path, codec: ContentCodec | None = None):
        self.codec = codec or NullCodec()
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: FastAPI runs sync endpoints in a thread
        # pool; CPython's sqlite3 is compiled serialized (threadsafety=3), so
        # sharing one connection across threads is safe for this local,
        # single-user workload.
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._tx_depth = 0
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _begin_transaction(self) -> None:
        self.conn.execute("BEGIN IMMEDIATE")

    def _commit_transaction(self) -> None:
        self.conn.commit()

    def _rollback_transaction(self) -> None:
        self.conn.rollback()

    def _maybe_commit(self) -> None:
        if getattr(self, "_tx_depth", 0) == 0:
            self.conn.commit()

    def _migrate(self) -> None:
        """Additive column migrations for databases created by older versions."""
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(percepts)")}
        for name, ddl in (
            ("source_trust", "REAL NOT NULL DEFAULT 0.8"),
            ("source_scope", "TEXT NOT NULL DEFAULT 'work'"),
            ("source_confidentiality", "TEXT NOT NULL DEFAULT 'internal'"),
            ("project_id", "TEXT"),
        ):
            if name not in cols:
                self.conn.execute(f"ALTER TABLE percepts ADD COLUMN {name} {ddl}")
        mem_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(memories)")}
        if "project_id" not in mem_cols:
            self.conn.execute("ALTER TABLE memories ADD COLUMN project_id TEXT")
        for name, ddl in (
            ("review_priority", "REAL NOT NULL DEFAULT 0"),
            ("quality_score", "REAL NOT NULL DEFAULT 0"),
            ("quality_flags", "TEXT NOT NULL DEFAULT '[]'"),
            ("impact", "TEXT NOT NULL DEFAULT 'medium'"),
            ("reviewed_at", "TEXT"),
            ("review_batch_id", "TEXT"),
            ("canonical_claim", "TEXT NOT NULL DEFAULT '{}'"),
            ("extractor_version", "TEXT NOT NULL DEFAULT '{}'"),
            ("last_reconciled_at", "TEXT"),
            ("retrieval_count", "INTEGER NOT NULL DEFAULT 0"),
            ("last_retrieved_at", "TEXT"),
            ("deleted_at", "TEXT"),
            ("deletion_reason", "TEXT"),
        ):
            if name not in mem_cols:
                self.conn.execute(f"ALTER TABLE memories ADD COLUMN {name} {ddl}")
                mem_cols.add(name)
        ev_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(evidence)")}
        for name, ddl in (
            ("evidence_type", "TEXT NOT NULL DEFAULT 'verbatim'"),
            ("directness", "REAL NOT NULL DEFAULT 1.0"),
            ("source_trust", "REAL NOT NULL DEFAULT 0.8"),
            ("independence_group", "TEXT"),
            ("supports", "INTEGER NOT NULL DEFAULT 1"),
            ("span_start", "INTEGER"),
            ("span_end", "INTEGER"),
            ("artifact_id", "TEXT"),
            ("deleted_at", "TEXT"),
        ):
            if name not in ev_cols:
                self.conn.execute(f"ALTER TABLE evidence ADD COLUMN {name} {ddl}")
        ent_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(entities)")}
        for name, ddl in (
            ("aliases", "TEXT NOT NULL DEFAULT '[]'"),
            ("canonical_id", "TEXT"),
        ):
            if name not in ent_cols:
                self.conn.execute(f"ALTER TABLE entities ADD COLUMN {name} {ddl}")
        ses_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(sessions)")}
        for name, ddl in (
            ("last_activity_at", "TEXT NOT NULL DEFAULT ''"),
            ("consolidation_status", "TEXT NOT NULL DEFAULT 'none'"),
            ("consolidation_error", "TEXT"),
            ("summary_percept_id", "TEXT"),
        ):
            if name not in ses_cols:
                self.conn.execute(f"ALTER TABLE sessions ADD COLUMN {name} {ddl}")
        find_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(review_findings)")}
        for name, ddl in (
            ("status", "TEXT NOT NULL DEFAULT 'open'"),
            ("analyzer_version", "TEXT NOT NULL DEFAULT 'quality-v1'"),
            ("resolution_operation_id", "TEXT"),
        ):
            if find_cols and name not in find_cols:
                self.conn.execute(f"ALTER TABLE review_findings ADD COLUMN {name} {ddl}")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS artifact_percepts ("
            " artifact_id TEXT NOT NULL, percept_id TEXT NOT NULL,"
            " PRIMARY KEY (artifact_id, percept_id))"
        )
        self._maybe_commit()

    def close(self) -> None:
        self.conn.close()

    # -- percepts ---------------------------------------------------------

    def insert_percept(self, percept: Percept) -> Optional[str]:
        percept.seal()
        existing = self.conn.execute(
            "SELECT id FROM percepts WHERE content_hash = ?", (percept.content_hash,)
        ).fetchone()
        if existing:
            return None
        self.conn.execute(
            "INSERT INTO percepts (id, percept_type, source_sensor, occurred_at,"
            " ingested_at, actors, content, content_refs, attachments,"
            " privacy_hints, integrity, metadata, source_trust, source_scope,"
            " source_confidentiality, project_id, content_hash)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                percept.id, percept.percept_type, percept.source_sensor,
                percept.occurred_at, percept.ingested_at or now_iso(),
                json.dumps(percept.actors), self.codec.encrypt(percept.content),
                json.dumps(percept.content_refs), json.dumps(percept.attachments),
                json.dumps(percept.privacy_hints), json.dumps(percept.integrity),
                json.dumps(percept.metadata), percept.source_trust,
                percept.source_scope, percept.source_confidentiality,
                percept.project_id, percept.content_hash,
            ),
        )
        self._maybe_commit()
        return percept.id

    def _row_to_percept(self, row: sqlite3.Row) -> Percept:
        return Percept(
            id=row["id"], percept_type=row["percept_type"],
            source_sensor=row["source_sensor"], occurred_at=row["occurred_at"],
            ingested_at=row["ingested_at"], actors=json.loads(row["actors"]),
            content=self.codec.decrypt(row["content"]),
            content_refs=json.loads(row["content_refs"]),
            attachments=json.loads(row["attachments"]),
            privacy_hints=json.loads(row["privacy_hints"]),
            integrity=json.loads(row["integrity"]), metadata=json.loads(row["metadata"]),
            source_trust=row["source_trust"], source_scope=row["source_scope"],
            source_confidentiality=row["source_confidentiality"],
            project_id=row["project_id"],
        )

    def get_percept(self, percept_id: str) -> Optional[Percept]:
        row = self.conn.execute("SELECT * FROM percepts WHERE id = ?", (percept_id,)).fetchone()
        return self._row_to_percept(row) if row else None

    def list_percepts(self) -> list[Percept]:
        rows = self.conn.execute("SELECT * FROM percepts ORDER BY ingested_at").fetchall()
        return [self._row_to_percept(r) for r in rows]

    def unprocessed_percepts(self) -> list[Percept]:
        rows = self.conn.execute(
            "SELECT p.* FROM percepts p"
            " WHERE NOT EXISTS (SELECT 1 FROM evidence e WHERE e.percept_id = p.id)"
            " ORDER BY p.ingested_at"
        ).fetchall()
        return [self._row_to_percept(r) for r in rows]

    # -- memories ----------------------------------------------------------

    def insert_memory(self, mem: MemoryItem) -> str:
        ts = now_iso()
        mem.created_at = mem.created_at or ts
        mem.updated_at = ts
        claim = mem.canonical_claim.model_dump() if mem.canonical_claim else {}
        ext = mem.extractor_version.model_dump() if mem.extractor_version else {}
        self.conn.execute(
            "INSERT INTO memories (id, type, title, summary, domain, persona,"
            " sensitivity, confidence, status, valid_from, valid_until,"
            " created_at, updated_at, payload, needs_review, review_reason,"
            " project_id, review_priority, quality_score, quality_flags, impact,"
            " reviewed_at, review_batch_id, canonical_claim, extractor_version,"
            " last_reconciled_at, retrieval_count, last_retrieved_at,"
            " deleted_at, deletion_reason)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                mem.id, mem.type.value, mem.title, mem.summary, mem.domain,
                mem.persona, mem.sensitivity.value, mem.confidence,
                mem.status.value, mem.valid_from, mem.valid_until,
                mem.created_at, mem.updated_at, json.dumps(mem.payload),
                int(mem.needs_review), mem.review_reason, mem.project_id,
                mem.review_priority, mem.quality_score, json.dumps(mem.quality_flags),
                mem.impact, mem.reviewed_at, mem.review_batch_id,
                json.dumps(claim), json.dumps(ext), mem.last_reconciled_at,
                mem.retrieval_count, mem.last_retrieved_at,
                mem.deleted_at, mem.deletion_reason,
            ),
        )
        self.conn.execute(
            "INSERT INTO memories_fts (memory_id, title, summary) VALUES (?,?,?)",
            (mem.id, mem.title, mem.summary),
        )
        for name in mem.entities:
            ent = self.upsert_entity(name)
            self.conn.execute(
                "INSERT OR IGNORE INTO memory_entities (memory_id, entity_id) VALUES (?,?)",
                (mem.id, ent.id),
            )
        self._maybe_commit()
        return mem.id

    def get_memory(self, memory_id: str) -> Optional[MemoryItem]:
        row = self.conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        if not row:
            return None
        return self._row_to_memory(row)

    def _row_to_memory(self, row: sqlite3.Row) -> MemoryItem:
        from ..models import CanonicalClaim, ExtractorVersion
        entities = [
            r["name"] for r in self.conn.execute(
                "SELECT e.name FROM entities e"
                " JOIN memory_entities me ON me.entity_id = e.id"
                " WHERE me.memory_id = ?", (row["id"],)
            ).fetchall()
        ]
        percept_ids = [
            r["percept_id"] for r in self.conn.execute(
                "SELECT DISTINCT percept_id FROM evidence WHERE memory_id = ?"
                " AND (deleted_at IS NULL OR deleted_at = '')", (row["id"],)
            ).fetchall()
        ]
        keys = set(row.keys())
        claim_raw = json.loads(row["canonical_claim"]) if "canonical_claim" in keys and row["canonical_claim"] else {}
        ext_raw = json.loads(row["extractor_version"]) if "extractor_version" in keys and row["extractor_version"] else {}
        flags = json.loads(row["quality_flags"]) if "quality_flags" in keys and row["quality_flags"] else []
        return MemoryItem(
            id=row["id"], type=row["type"], title=row["title"], summary=row["summary"],
            domain=row["domain"], persona=row["persona"], sensitivity=row["sensitivity"],
            confidence=row["confidence"], status=row["status"],
            valid_from=row["valid_from"], valid_until=row["valid_until"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            payload=json.loads(row["payload"]), needs_review=bool(row["needs_review"]),
            review_reason=row["review_reason"], project_id=row["project_id"],
            entities=entities, percept_ids=percept_ids,
            review_priority=float(row["review_priority"]) if "review_priority" in keys else 0.0,
            quality_score=float(row["quality_score"]) if "quality_score" in keys else 0.0,
            quality_flags=flags,
            impact=row["impact"] if "impact" in keys and row["impact"] else "medium",
            reviewed_at=row["reviewed_at"] if "reviewed_at" in keys else None,
            review_batch_id=row["review_batch_id"] if "review_batch_id" in keys else None,
            canonical_claim=CanonicalClaim(**claim_raw) if claim_raw else None,
            extractor_version=ExtractorVersion(**ext_raw) if ext_raw else None,
            last_reconciled_at=row["last_reconciled_at"] if "last_reconciled_at" in keys else None,
            retrieval_count=int(row["retrieval_count"]) if "retrieval_count" in keys else 0,
            last_retrieved_at=row["last_retrieved_at"] if "last_retrieved_at" in keys else None,
            deleted_at=row["deleted_at"] if "deleted_at" in keys else None,
            deletion_reason=row["deletion_reason"] if "deletion_reason" in keys else None,
        )

    def list_memories(
        self,
        status: Optional[str] = None,
        domain: Optional[str] = None,
        type_: Optional[str] = None,
        needs_review: Optional[bool] = None,
        project_id: Optional[str] = None,
        limit: int = 200,
    ) -> list[MemoryItem]:
        query = "SELECT * FROM memories WHERE 1=1"
        params: list[Any] = []
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        if domain:
            query += " AND domain = ?"
            params.append(domain)
        if type_:
            query += " AND type = ?"
            params.append(type_)
        if needs_review is not None:
            query += " AND needs_review = ?"
            params.append(int(needs_review))
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [self._row_to_memory(r) for r in self.conn.execute(query, params).fetchall()]

    def update_memory(self, memory_id: str, **fields: Any) -> None:
        allowed = {
            "title", "summary", "domain", "persona", "sensitivity", "confidence",
            "status", "valid_from", "valid_until", "needs_review", "review_reason",
            "payload", "project_id", "review_priority", "quality_score", "quality_flags",
            "impact", "reviewed_at", "review_batch_id", "canonical_claim",
            "extractor_version", "last_reconciled_at", "retrieval_count",
            "last_retrieved_at", "deleted_at", "deletion_reason",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        if "payload" in updates and not isinstance(updates["payload"], str):
            updates["payload"] = json.dumps(updates["payload"])
        if "quality_flags" in updates and not isinstance(updates["quality_flags"], str):
            updates["quality_flags"] = json.dumps(updates["quality_flags"])
        if "canonical_claim" in updates and not isinstance(updates["canonical_claim"], str):
            claim = updates["canonical_claim"]
            if hasattr(claim, "model_dump"):
                claim = claim.model_dump()
            updates["canonical_claim"] = json.dumps(claim or {})
        if "extractor_version" in updates and not isinstance(updates["extractor_version"], str):
            ext = updates["extractor_version"]
            if hasattr(ext, "model_dump"):
                ext = ext.model_dump()
            updates["extractor_version"] = json.dumps(ext or {})
        if "needs_review" in updates:
            updates["needs_review"] = int(updates["needs_review"])
        sets = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [now_iso(), memory_id]
        self.conn.execute(f"UPDATE memories SET {sets}, updated_at = ? WHERE id = ?", params)
        if "title" in updates or "summary" in updates:
            row = self.conn.execute(
                "SELECT title, summary FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
            self.conn.execute("DELETE FROM memories_fts WHERE memory_id = ?", (memory_id,))
            self.conn.execute(
                "INSERT INTO memories_fts (memory_id, title, summary) VALUES (?,?,?)",
                (memory_id, row["title"], row["summary"]),
            )
        self._maybe_commit()

    # -- evidence ----------------------------------------------------------

    def insert_evidence(self, ev: Evidence) -> str:
        self.conn.execute(
            "INSERT INTO evidence (id, memory_id, percept_id, quote, evidence_type,"
            " directness, source_trust, independence_group, supports, span_start,"
            " span_end, artifact_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ev.id, ev.memory_id, ev.percept_id, self.codec.encrypt(ev.quote),
                getattr(ev.evidence_type, "value", ev.evidence_type),
                ev.directness, ev.source_trust, ev.independence_group,
                int(ev.supports), ev.span_start, ev.span_end, ev.artifact_id,
            ),
        )
        self._maybe_commit()
        return ev.id

    def get_evidence(self, memory_id: str) -> list[Evidence]:
        rows = self.conn.execute(
            "SELECT * FROM evidence WHERE memory_id = ?"
            " AND (deleted_at IS NULL OR deleted_at = '')", (memory_id,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["quote"] = self.codec.decrypt(d["quote"])
            d["supports"] = bool(d.get("supports", 1))
            d.pop("deleted_at", None)
            out.append(Evidence(**{k: v for k, v in d.items() if k in Evidence.model_fields}))
        return out

    # -- entities & relations ------------------------------------------------

    def upsert_entity(self, name: str, entity_type: str = "generic") -> Entity:
        name = name.strip()
        row = self.conn.execute(
            "SELECT * FROM entities WHERE name = ? COLLATE NOCASE", (name,)
        ).fetchone()
        if row:
            d = dict(row)
            d["aliases"] = json.loads(d["aliases"]) if isinstance(d.get("aliases"), str) else (d.get("aliases") or [])
            return Entity(**{k: v for k, v in d.items() if k in Entity.model_fields})
        ent = Entity(id=ids.entity_id(), name=name, entity_type=entity_type, created_at=now_iso())
        self.conn.execute(
            "INSERT INTO entities (id, name, entity_type, created_at, aliases) VALUES (?,?,?,?,?)",
            (ent.id, ent.name, ent.entity_type, ent.created_at, json.dumps(ent.aliases)),
        )
        self._maybe_commit()
        return ent

    def get_entity_by_name(self, name: str) -> Optional[Entity]:
        row = self.conn.execute(
            "SELECT * FROM entities WHERE name = ? COLLATE NOCASE", (name.strip(),)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["aliases"] = json.loads(d["aliases"]) if isinstance(d.get("aliases"), str) else (d.get("aliases") or [])
        return Entity(**{k: v for k, v in d.items() if k in Entity.model_fields})

    def list_entities(self) -> list[Entity]:
        rows = self.conn.execute("SELECT * FROM entities ORDER BY name").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["aliases"] = json.loads(d["aliases"]) if isinstance(d.get("aliases"), str) else (d.get("aliases") or [])
            out.append(Entity(**{k: v for k, v in d.items() if k in Entity.model_fields}))
        return out

    def insert_relation(self, rel: Relation) -> str:
        rel.created_at = rel.created_at or now_iso()
        self.conn.execute(
            "INSERT INTO relations (id, subject_id, predicate, object_id, memory_id,"
            " valid_from, valid_until, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                rel.id, rel.subject_id, rel.predicate, rel.object_id,
                rel.memory_id, rel.valid_from, rel.valid_until, rel.created_at,
            ),
        )
        self._maybe_commit()
        return rel.id

    def relations_for(self, node_id: str) -> list[Relation]:
        rows = self.conn.execute(
            "SELECT * FROM relations WHERE subject_id = ? OR object_id = ?",
            (node_id, node_id),
        ).fetchall()
        return [Relation(**dict(r)) for r in rows]

    def memories_for_entity(self, entity_id: str) -> list[MemoryItem]:
        rows = self.conn.execute(
            "SELECT m.* FROM memories m JOIN memory_entities me ON me.memory_id = m.id"
            " WHERE me.entity_id = ? ORDER BY m.created_at DESC",
            (entity_id,),
        ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    # -- embeddings ------------------------------------------------------------

    def store_embedding(self, ref_id: str, ref_type: str, model: str,
                        vector: list[float]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO embeddings (ref_id, ref_type, model, dim, vector)"
            " VALUES (?,?,?,?,?)",
            (ref_id, ref_type, model, len(vector), to_blob(vector)),
        )
        self._maybe_commit()

    def iter_embeddings(self, ref_type: str, model: str) -> Iterable[tuple[str, bytes]]:
        for row in self.conn.execute(
            "SELECT ref_id, vector FROM embeddings WHERE ref_type = ? AND model = ?",
            (ref_type, model),
        ):
            yield row["ref_id"], row["vector"]

    # -- fts ---------------------------------------------------------------------

    def fts_search(self, query: str, limit: int = 50) -> dict[str, float]:
        terms = self.sanitize_fts_terms(query)
        if not terms:
            return {}
        match = " OR ".join(terms)
        try:
            rows = self.conn.execute(
                "SELECT memory_id, bm25(memories_fts) AS score FROM memories_fts"
                " WHERE memories_fts MATCH ? ORDER BY score LIMIT ?",
                (match, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
        return {r["memory_id"]: -float(r["score"]) for r in rows}

    # -- projects -----------------------------------------------------------------

    def insert_project(self, project: Project) -> str:
        ts = now_iso()
        project.created_at = project.created_at or ts
        project.updated_at = ts
        self.conn.execute(
            "INSERT INTO projects (id, name, aliases, repos, goals, milestones,"
            " open_questions, status, created_at, updated_at, metadata)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                project.id, project.name, json.dumps(project.aliases),
                json.dumps(project.repos), json.dumps(project.goals),
                json.dumps(project.milestones), json.dumps(project.open_questions),
                project.status, project.created_at, project.updated_at,
                json.dumps(project.metadata),
            ),
        )
        self._maybe_commit()
        return project.id

    def update_project(self, project: Project) -> None:
        project.updated_at = now_iso()
        self.conn.execute(
            "UPDATE projects SET name = ?, aliases = ?, repos = ?, goals = ?,"
            " milestones = ?, open_questions = ?, status = ?, updated_at = ?,"
            " metadata = ? WHERE id = ?",
            (
                project.name, json.dumps(project.aliases), json.dumps(project.repos),
                json.dumps(project.goals), json.dumps(project.milestones),
                json.dumps(project.open_questions), project.status,
                project.updated_at, json.dumps(project.metadata), project.id,
            ),
        )
        self._maybe_commit()

    @staticmethod
    def _row_to_project(row: sqlite3.Row) -> Project:
        return Project(
            id=row["id"], name=row["name"], aliases=json.loads(row["aliases"]),
            repos=json.loads(row["repos"]), goals=json.loads(row["goals"]),
            milestones=json.loads(row["milestones"]),
            open_questions=json.loads(row["open_questions"]), status=row["status"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            metadata=json.loads(row["metadata"]),
        )

    def get_project(self, project_id: str) -> Optional[Project]:
        row = self.conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return self._row_to_project(row) if row else None

    def list_projects(self, status: Optional[str] = None) -> list[Project]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM projects WHERE status = ? ORDER BY name", (status,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM projects ORDER BY name").fetchall()
        return [self._row_to_project(r) for r in rows]

    # -- cognitive sessions ----------------------------------------------------------

    def insert_session(self, session: CognitiveSession) -> str:
        session.started_at = session.started_at or now_iso()
        session.last_activity_at = session.last_activity_at or session.started_at
        self.conn.execute(
            "INSERT INTO sessions (id, client, project_id, domain, task_profile,"
            " initial_query, status, started_at, ended_at, last_activity_at,"
            " supplied_memory_ids, pack_chars, created_memory_ids,"
            " consolidation_status, consolidation_error, summary_percept_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                session.id, session.client, session.project_id, session.domain,
                session.task_profile, session.initial_query,
                getattr(session.status, "value", session.status),
                session.started_at, session.ended_at, session.last_activity_at,
                json.dumps(session.supplied_memory_ids), session.pack_chars,
                json.dumps(session.created_memory_ids),
                getattr(session.consolidation_status, "value", session.consolidation_status),
                session.consolidation_error, session.summary_percept_id,
            ),
        )
        self._maybe_commit()
        return session.id

    def update_session(self, session: CognitiveSession) -> None:
        self.conn.execute(
            "UPDATE sessions SET client = ?, project_id = ?, domain = ?,"
            " task_profile = ?, initial_query = ?, status = ?, ended_at = ?,"
            " last_activity_at = ?, supplied_memory_ids = ?, pack_chars = ?,"
            " created_memory_ids = ?, consolidation_status = ?,"
            " consolidation_error = ?, summary_percept_id = ? WHERE id = ?",
            (
                session.client, session.project_id, session.domain,
                session.task_profile, session.initial_query,
                getattr(session.status, "value", session.status),
                session.ended_at, session.last_activity_at or now_iso(),
                json.dumps(session.supplied_memory_ids), session.pack_chars,
                json.dumps(session.created_memory_ids),
                getattr(session.consolidation_status, "value", session.consolidation_status),
                session.consolidation_error, session.summary_percept_id,
                session.id,
            ),
        )
        self._maybe_commit()

    def append_session_artifact(self, session_id: str, artifact: dict) -> None:
        with self.conn:  # one transaction: the active-guard and the append
            cur = self.conn.execute(
                "UPDATE sessions SET last_activity_at = ? WHERE id = ? AND status = 'active'",
                (now_iso(), session_id),
            )
            if cur.rowcount == 0:
                row = self.conn.execute(
                    "SELECT status FROM sessions WHERE id = ?", (session_id,)
                ).fetchone()
                if row is None:
                    raise ValueError(f"session {session_id} not found")
                raise ValueError(f"session {session_id} is {row['status']}, not active")
            self.conn.execute(
                "INSERT INTO session_artifacts (session_id, kind, ref, note,"
                " percept_id, observed_at) VALUES (?,?,?,?,?,?)",
                (session_id, artifact.get("kind", "artifact"), artifact.get("ref"),
                 artifact.get("note"), artifact.get("percept_id"),
                 artifact.get("at") or now_iso()),
            )

    def append_session_feedback(self, session_id: str, feedback: dict) -> None:
        with self.conn:
            cur = self.conn.execute(
                "UPDATE sessions SET last_activity_at = ? WHERE id = ?",
                (now_iso(), session_id),
            )
            if cur.rowcount == 0:
                raise ValueError(f"session {session_id} not found")
            self.conn.execute(
                "INSERT INTO session_feedback (session_id, scope, verdict, memory_id,"
                " note, created_at) VALUES (?,?,?,?,?,?)",
                (session_id, feedback.get("scope", "session"), feedback["verdict"],
                 feedback.get("memory_id"), feedback.get("note", ""),
                 feedback.get("at") or now_iso()),
            )

    def transition_session(self, session_id: str, from_status: str,
                           to_status: str, ended_at: Optional[str] = None) -> bool:
        cur = self.conn.execute(
            "UPDATE sessions SET status = ?, ended_at = COALESCE(?, ended_at),"
            " last_activity_at = ? WHERE id = ? AND status = ?",
            (to_status, ended_at, now_iso(), session_id, from_status),
        )
        self._maybe_commit()
        return cur.rowcount > 0

    def _session_artifacts(self, session_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT kind, ref, note, percept_id, observed_at FROM session_artifacts"
            " WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
        return [
            {k: r[k] for k in ("kind", "ref", "note", "percept_id") if r[k] is not None}
            | {"at": r["observed_at"]}
            for r in rows
        ]

    def _session_feedback(self, session_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT scope, verdict, memory_id, note, created_at FROM session_feedback"
            " WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
        return [
            {"scope": r["scope"], "verdict": r["verdict"], "memory_id": r["memory_id"],
             "note": r["note"], "at": r["created_at"]}
            for r in rows
        ]

    def _row_to_session(self, row: sqlite3.Row) -> CognitiveSession:
        return CognitiveSession(
            id=row["id"], client=row["client"], project_id=row["project_id"],
            domain=row["domain"], task_profile=row["task_profile"],
            initial_query=row["initial_query"], status=row["status"],
            started_at=row["started_at"], ended_at=row["ended_at"],
            last_activity_at=row["last_activity_at"],
            supplied_memory_ids=json.loads(row["supplied_memory_ids"]),
            pack_chars=row["pack_chars"],
            artifacts=self._session_artifacts(row["id"]),
            created_memory_ids=json.loads(row["created_memory_ids"]),
            feedback=self._session_feedback(row["id"]),
            consolidation_status=row["consolidation_status"],
            consolidation_error=row["consolidation_error"],
            summary_percept_id=row["summary_percept_id"],
        )

    def get_session(self, session_id: str) -> Optional[CognitiveSession]:
        row = self.conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return self._row_to_session(row) if row else None

    def list_sessions(self, status: Optional[str] = None,
                      project_id: Optional[str] = None,
                      limit: int = 200) -> list[CognitiveSession]:
        query = "SELECT * FROM sessions WHERE 1=1"
        params: list[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        return [self._row_to_session(r) for r in self.conn.execute(query, params).fetchall()]

    # -- metrics -----------------------------------------------------------------

    def count_evidence(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]

    def count_firewall_blocks(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM firewall_log WHERE action = 'block'"
        ).fetchone()[0]

    # -- firewall log ----------------------------------------------------------------

    def log_firewall(self, memory_id: str, target_domain: str, rule: str, action: str) -> None:
        self.conn.execute(
            "INSERT INTO firewall_log (memory_id, target_domain, rule, action, created_at)"
            " VALUES (?,?,?,?,?)",
            (memory_id, target_domain, rule, action, now_iso()),
        )
        self._maybe_commit()

    # -- v0.3 artifacts / findings / batches / operations -------------------------

    def delete_embedding(self, ref_id: str) -> None:
        self.conn.execute("DELETE FROM embeddings WHERE ref_id = ?", (ref_id,))
        self._maybe_commit()

    def insert_artifact(self, art: Artifact) -> str:
        art.created_at = art.created_at or now_iso()
        self.conn.execute(
            "INSERT INTO artifacts (id, kind, external_id, source_system, uri,"
            " content_hash, occurred_at, created_at, deleted_at, deletion_reason,"
            " content_destroyed, metadata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                art.id, art.kind, art.external_id, art.source_system, art.uri,
                art.content_hash, art.occurred_at, art.created_at, art.deleted_at,
                art.deletion_reason, int(art.content_destroyed), json.dumps(art.metadata),
            ),
        )
        self._maybe_commit()
        return art.id

    def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        row = self.conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        return self._row_to_artifact(row) if row else None

    def find_artifact_by_hash(self, content_hash: str) -> Optional[Artifact]:
        row = self.conn.execute(
            "SELECT * FROM artifacts WHERE content_hash = ? AND deleted_at IS NULL",
            (content_hash,),
        ).fetchone()
        return self._row_to_artifact(row) if row else None

    def list_artifacts(self) -> list[Artifact]:
        rows = self.conn.execute("SELECT * FROM artifacts ORDER BY created_at").fetchall()
        return [self._row_to_artifact(r) for r in rows]

    @staticmethod
    def _row_to_artifact(row: sqlite3.Row) -> Artifact:
        return Artifact(
            id=row["id"], kind=row["kind"], external_id=row["external_id"],
            source_system=row["source_system"], uri=row["uri"],
            content_hash=row["content_hash"], occurred_at=row["occurred_at"],
            created_at=row["created_at"], deleted_at=row["deleted_at"],
            deletion_reason=row["deletion_reason"],
            content_destroyed=bool(row["content_destroyed"]),
            metadata=json.loads(row["metadata"]),
        )

    def tombstone_artifact(self, artifact_id: str, *, reason: str,
                           destroy_content: bool = True) -> None:
        self.conn.execute(
            "UPDATE artifacts SET deleted_at = ?, deletion_reason = ?,"
            " content_destroyed = ? WHERE id = ?",
            (now_iso(), reason, int(destroy_content), artifact_id),
        )
        self._maybe_commit()

    def tombstone_percept(self, percept_id: str, *, reason: str,
                          destroy_content: bool = True) -> None:
        row = self.conn.execute(
            "SELECT metadata FROM percepts WHERE id = ?", (percept_id,)
        ).fetchone()
        if not row:
            return
        meta = json.loads(row["metadata"] or "{}")
        meta["tombstoned"] = True
        meta["deletion_reason"] = reason
        content = "[content destroyed]" if destroy_content else None
        if content is not None:
            self.conn.execute(
                "UPDATE percepts SET content = ?, metadata = ? WHERE id = ?",
                (self.codec.encrypt(content), json.dumps(meta), percept_id),
            )
        else:
            self.conn.execute(
                "UPDATE percepts SET metadata = ? WHERE id = ?",
                (json.dumps(meta), percept_id),
            )
        self._maybe_commit()

    def tombstone_evidence(self, evidence_id: str, *, reason: str) -> None:
        self.conn.execute(
            "UPDATE evidence SET deleted_at = ?, quote = ? WHERE id = ?",
            (now_iso(), f"[tombstoned:{reason}]", evidence_id),
        )
        self._maybe_commit()

    def list_evidence_for_artifact(self, artifact_id: str) -> list[Evidence]:
        rows = self.conn.execute(
            "SELECT * FROM evidence WHERE artifact_id = ?", (artifact_id,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["quote"] = self.codec.decrypt(d["quote"])
            d["supports"] = bool(d.get("supports", 1))
            d.pop("deleted_at", None)
            out.append(Evidence(**{k: v for k, v in d.items() if k in Evidence.model_fields}))
        return out

    def replace_findings(self, memory_id: str, findings: list[ReviewFinding]) -> None:
        # Preserve human dismissals; mark prior open findings obsolete then insert fresh.
        self.conn.execute(
            "UPDATE review_findings SET status = 'obsolete', resolved = 1,"
            " resolved_at = ? WHERE memory_id = ? AND status = 'open'",
            (now_iso(), memory_id),
        )
        for f in findings:
            self.insert_finding(f, commit=False)
        self._maybe_commit()

    def insert_finding(self, finding: ReviewFinding, commit: bool = True) -> str:
        finding.created_at = finding.created_at or now_iso()
        status = getattr(finding.status, "value", finding.status) or "open"
        resolved = int(finding.resolved or status != "open")
        self.conn.execute(
            "INSERT INTO review_findings (id, memory_id, type, related_memory_id,"
            " confidence, reason, suggested_action, requires_human_review, resolved,"
            " created_at, resolved_at, metadata, status, analyzer_version,"
            " resolution_operation_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                finding.id, finding.memory_id, finding.type.value, finding.related_memory_id,
                finding.confidence, finding.reason, finding.suggested_action.value,
                int(finding.requires_human_review), resolved,
                finding.created_at, finding.resolved_at, json.dumps(finding.metadata),
                status, finding.analyzer_version, finding.resolution_operation_id,
            ),
        )
        if commit:
            self._maybe_commit()
        return finding.id

    def get_findings(self, memory_id: str, unresolved_only: bool = True) -> list[ReviewFinding]:
        q = "SELECT * FROM review_findings WHERE memory_id = ?"
        if unresolved_only:
            q += " AND (status = 'open' OR (status IS NULL AND resolved = 0))"
        rows = self.conn.execute(q, (memory_id,)).fetchall()
        return [self._row_to_finding(r) for r in rows]

    @staticmethod
    def _row_to_finding(row: sqlite3.Row) -> ReviewFinding:
        keys = set(row.keys())
        status = row["status"] if "status" in keys and row["status"] else (
            "resolved" if row["resolved"] else "open"
        )
        return ReviewFinding(
            id=row["id"], memory_id=row["memory_id"], type=row["type"],
            related_memory_id=row["related_memory_id"], confidence=row["confidence"],
            reason=row["reason"], suggested_action=row["suggested_action"],
            requires_human_review=bool(row["requires_human_review"]),
            status=status,
            resolved=bool(row["resolved"]), created_at=row["created_at"],
            resolved_at=row["resolved_at"],
            analyzer_version=(row["analyzer_version"] if "analyzer_version" in keys
                              else "quality-v1"),
            resolution_operation_id=(row["resolution_operation_id"]
                                     if "resolution_operation_id" in keys else None),
            metadata=json.loads(row["metadata"]),
        )

    def insert_review_batch(self, batch: ReviewBatch) -> str:
        self.conn.execute(
            "INSERT INTO review_batches (id, name, query, memory_ids, created_at,"
            " completed_at, progress_total, progress_reviewed, metadata)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                batch.id, batch.name, json.dumps(batch.query),
                json.dumps(batch.memory_ids), batch.created_at, batch.completed_at,
                batch.progress_total, batch.progress_reviewed, json.dumps(batch.metadata),
            ),
        )
        self._maybe_commit()
        return batch.id

    def get_review_batch(self, batch_id: str) -> Optional[ReviewBatch]:
        row = self.conn.execute(
            "SELECT * FROM review_batches WHERE id = ?", (batch_id,)
        ).fetchone()
        if not row:
            return None
        return ReviewBatch(
            id=row["id"], name=row["name"], query=json.loads(row["query"]),
            memory_ids=json.loads(row["memory_ids"]), created_at=row["created_at"],
            completed_at=row["completed_at"], progress_total=row["progress_total"],
            progress_reviewed=row["progress_reviewed"],
            metadata=json.loads(row["metadata"]),
        )

    def update_review_batch(self, batch_id: str, **fields: Any) -> None:
        allowed = {"completed_at", "progress_total", "progress_reviewed", "memory_ids", "metadata"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if "memory_ids" in updates and not isinstance(updates["memory_ids"], str):
            updates["memory_ids"] = json.dumps(updates["memory_ids"])
        if "metadata" in updates and not isinstance(updates["metadata"], str):
            updates["metadata"] = json.dumps(updates["metadata"])
        if not updates:
            return
        sets = ", ".join(f"{k} = ?" for k in updates)
        self.conn.execute(
            f"UPDATE review_batches SET {sets} WHERE id = ?",
            list(updates.values()) + [batch_id],
        )
        self._maybe_commit()

    def list_review_batches(self) -> list[ReviewBatch]:
        rows = self.conn.execute(
            "SELECT * FROM review_batches ORDER BY created_at DESC"
        ).fetchall()
        return [self.get_review_batch(r["id"]) for r in rows]  # type: ignore[misc]

    def insert_operation(self, op: MemoryOperation) -> str:
        self.conn.execute(
            "INSERT INTO memory_operations (id, operation, actor, at, inputs, output,"
            " before_state, after_state, undoable, undone_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                op.id, op.operation, op.actor, op.at, json.dumps(op.inputs), op.output,
                json.dumps(op.before), json.dumps(op.after), int(op.undoable), op.undone_at,
            ),
        )
        self._maybe_commit()
        return op.id

    def get_operation(self, operation_id: str) -> Optional[MemoryOperation]:
        row = self.conn.execute(
            "SELECT * FROM memory_operations WHERE id = ?", (operation_id,)
        ).fetchone()
        if not row:
            return None
        return MemoryOperation(
            id=row["id"], operation=row["operation"], actor=row["actor"], at=row["at"],
            inputs=json.loads(row["inputs"]), output=row["output"],
            before=json.loads(row["before_state"]), after=json.loads(row["after_state"]),
            undoable=bool(row["undoable"]), undone_at=row["undone_at"],
        )

    def mark_operation_undone(self, operation_id: str) -> None:
        self.conn.execute(
            "UPDATE memory_operations SET undone_at = ?, undoable = 0 WHERE id = ?",
            (now_iso(), operation_id),
        )
        self._maybe_commit()

    def bump_retrieval(self, memory_id: str) -> None:
        self.conn.execute(
            "UPDATE memories SET retrieval_count = retrieval_count + 1,"
            " last_retrieved_at = ? WHERE id = ?",
            (now_iso(), memory_id),
        )
        self._maybe_commit()

    def delete_relation(self, relation_id: str) -> None:
        self.conn.execute("DELETE FROM relations WHERE id = ?", (relation_id,))
        self._maybe_commit()

    def delete_evidence_row(self, evidence_id: str) -> None:
        self.conn.execute("DELETE FROM evidence WHERE id = ?", (evidence_id,))
        self._maybe_commit()

    def hard_delete_memory(self, memory_id: str) -> None:
        self.conn.execute("DELETE FROM memories_fts WHERE memory_id = ?", (memory_id,))
        self.conn.execute("DELETE FROM memory_entities WHERE memory_id = ?", (memory_id,))
        self.conn.execute("DELETE FROM evidence WHERE memory_id = ?", (memory_id,))
        self.conn.execute("DELETE FROM embeddings WHERE ref_id = ?", (memory_id,))
        self.conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self._maybe_commit()

    def get_embedding_blob(self, ref_id: str, model: Optional[str] = None) -> Optional[tuple[str, bytes]]:
        if model:
            row = self.conn.execute(
                "SELECT model, vector FROM embeddings WHERE ref_id = ? AND model = ?",
                (ref_id, model),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT model, vector FROM embeddings WHERE ref_id = ? LIMIT 1",
                (ref_id,),
            ).fetchone()
        if not row:
            return None
        return row["model"], row["vector"]

    def restore_embedding_blob(self, ref_id: str, ref_type: str, model: str, blob: bytes) -> None:
        import struct
        # dim from blob: float32 array
        dim = len(blob) // 4
        self.conn.execute(
            "INSERT OR REPLACE INTO embeddings (ref_id, ref_type, model, dim, vector)"
            " VALUES (?,?,?,?,?)",
            (ref_id, ref_type, model, dim, blob),
        )
        self._maybe_commit()

    def list_evidence_by_percept_ids(self, percept_ids: list[str]) -> list[Evidence]:
        if not percept_ids:
            return []
        placeholders = ",".join("?" * len(percept_ids))
        rows = self.conn.execute(
            f"SELECT * FROM evidence WHERE percept_id IN ({placeholders})"
            " AND (deleted_at IS NULL OR deleted_at = '')",
            percept_ids,
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["quote"] = self.codec.decrypt(d["quote"])
            d["supports"] = bool(d.get("supports", 1))
            d.pop("deleted_at", None)
            out.append(Evidence(**{k: v for k, v in d.items() if k in Evidence.model_fields}))
        return out

    def list_percept_ids_for_artifact(self, artifact_id: str) -> list[str]:
        """Explicit lineage only — never content-hash ownership."""
        ids_set: set[str] = set()
        art = self.get_artifact(artifact_id)
        if art and art.metadata.get("percept_id"):
            ids_set.add(art.metadata["percept_id"])
        for ev in self.list_evidence_for_artifact(artifact_id):
            ids_set.add(ev.percept_id)
        # explicit link table if present
        try:
            rows = self.conn.execute(
                "SELECT percept_id FROM artifact_percepts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchall()
            for r in rows:
                ids_set.add(r["percept_id"])
        except sqlite3.OperationalError:
            pass
        return list(ids_set)

    def link_artifact_percept(self, artifact_id: str, percept_id: str) -> None:
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS artifact_percepts ("
            " artifact_id TEXT NOT NULL, percept_id TEXT NOT NULL,"
            " PRIMARY KEY (artifact_id, percept_id))"
        )
        self.conn.execute(
            "INSERT OR IGNORE INTO artifact_percepts (artifact_id, percept_id) VALUES (?,?)",
            (artifact_id, percept_id),
        )
        self._maybe_commit()

    def count_artifact_links_for_percept(self, percept_id: str) -> int:
        try:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM artifact_percepts WHERE percept_id = ?",
                (percept_id,),
            ).fetchone()
            return int(row["n"]) if row else 0
        except sqlite3.OperationalError:
            return 0

    def unlink_artifact_percept(self, artifact_id: str, percept_id: str) -> None:
        try:
            self.conn.execute(
                "DELETE FROM artifact_percepts WHERE artifact_id = ? AND percept_id = ?",
                (artifact_id, percept_id),
            )
            self._maybe_commit()
        except sqlite3.OperationalError:
            pass
