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
from ..models import CognitiveSession, Entity, Evidence, MemoryItem, Project, Relation
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
    project_id TEXT
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
    quote TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_memory ON evidence(memory_id);
CREATE INDEX IF NOT EXISTS idx_evidence_percept ON evidence(percept_id);

CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'generic',
    created_at TEXT NOT NULL
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
    supplied_memory_ids TEXT NOT NULL DEFAULT '[]',
    pack_chars INTEGER NOT NULL DEFAULT 0,
    artifacts TEXT NOT NULL DEFAULT '[]',
    created_memory_ids TEXT NOT NULL DEFAULT '[]',
    feedback TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id);

CREATE TABLE IF NOT EXISTS firewall_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id TEXT NOT NULL,
    target_domain TEXT NOT NULL,
    rule TEXT NOT NULL,
    action TEXT NOT NULL,
    created_at TEXT NOT NULL
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
        self.conn.executescript(SCHEMA)
        self._migrate()

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
        self.conn.commit()

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
        self.conn.commit()
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
        self.conn.execute(
            "INSERT INTO memories (id, type, title, summary, domain, persona,"
            " sensitivity, confidence, status, valid_from, valid_until,"
            " created_at, updated_at, payload, needs_review, review_reason,"
            " project_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                mem.id, mem.type.value, mem.title, mem.summary, mem.domain,
                mem.persona, mem.sensitivity.value, mem.confidence,
                mem.status.value, mem.valid_from, mem.valid_until,
                mem.created_at, mem.updated_at, json.dumps(mem.payload),
                int(mem.needs_review), mem.review_reason, mem.project_id,
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
        self.conn.commit()
        return mem.id

    def get_memory(self, memory_id: str) -> Optional[MemoryItem]:
        row = self.conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        if not row:
            return None
        return self._row_to_memory(row)

    def _row_to_memory(self, row: sqlite3.Row) -> MemoryItem:
        entities = [
            r["name"] for r in self.conn.execute(
                "SELECT e.name FROM entities e"
                " JOIN memory_entities me ON me.entity_id = e.id"
                " WHERE me.memory_id = ?", (row["id"],)
            ).fetchall()
        ]
        percept_ids = [
            r["percept_id"] for r in self.conn.execute(
                "SELECT DISTINCT percept_id FROM evidence WHERE memory_id = ?", (row["id"],)
            ).fetchall()
        ]
        return MemoryItem(
            id=row["id"], type=row["type"], title=row["title"], summary=row["summary"],
            domain=row["domain"], persona=row["persona"], sensitivity=row["sensitivity"],
            confidence=row["confidence"], status=row["status"],
            valid_from=row["valid_from"], valid_until=row["valid_until"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            payload=json.loads(row["payload"]), needs_review=bool(row["needs_review"]),
            review_reason=row["review_reason"], project_id=row["project_id"],
            entities=entities, percept_ids=percept_ids,
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
            "payload", "project_id",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        if "payload" in updates and not isinstance(updates["payload"], str):
            updates["payload"] = json.dumps(updates["payload"])
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
        self.conn.commit()

    # -- evidence ----------------------------------------------------------

    def insert_evidence(self, ev: Evidence) -> str:
        self.conn.execute(
            "INSERT INTO evidence (id, memory_id, percept_id, quote) VALUES (?,?,?,?)",
            (ev.id, ev.memory_id, ev.percept_id, self.codec.encrypt(ev.quote)),
        )
        self.conn.commit()
        return ev.id

    def get_evidence(self, memory_id: str) -> list[Evidence]:
        rows = self.conn.execute(
            "SELECT * FROM evidence WHERE memory_id = ?", (memory_id,)
        ).fetchall()
        return [
            Evidence(**{**dict(r), "quote": self.codec.decrypt(r["quote"])})
            for r in rows
        ]

    # -- entities & relations ------------------------------------------------

    def upsert_entity(self, name: str, entity_type: str = "generic") -> Entity:
        name = name.strip()
        row = self.conn.execute(
            "SELECT * FROM entities WHERE name = ? COLLATE NOCASE", (name,)
        ).fetchone()
        if row:
            return Entity(**dict(row))
        ent = Entity(id=ids.entity_id(), name=name, entity_type=entity_type, created_at=now_iso())
        self.conn.execute(
            "INSERT INTO entities (id, name, entity_type, created_at) VALUES (?,?,?,?)",
            (ent.id, ent.name, ent.entity_type, ent.created_at),
        )
        self.conn.commit()
        return ent

    def get_entity_by_name(self, name: str) -> Optional[Entity]:
        row = self.conn.execute(
            "SELECT * FROM entities WHERE name = ? COLLATE NOCASE", (name.strip(),)
        ).fetchone()
        return Entity(**dict(row)) if row else None

    def list_entities(self) -> list[Entity]:
        rows = self.conn.execute("SELECT * FROM entities ORDER BY name").fetchall()
        return [Entity(**dict(r)) for r in rows]

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
        self.conn.commit()
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
        self.conn.commit()

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
        self.conn.commit()
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
        self.conn.commit()

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
        self.conn.execute(
            "INSERT INTO sessions (id, client, project_id, domain, task_profile,"
            " initial_query, status, started_at, ended_at, supplied_memory_ids,"
            " pack_chars, artifacts, created_memory_ids, feedback)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                session.id, session.client, session.project_id, session.domain,
                session.task_profile, session.initial_query,
                getattr(session.status, "value", session.status),
                session.started_at, session.ended_at,
                json.dumps(session.supplied_memory_ids), session.pack_chars,
                json.dumps(session.artifacts), json.dumps(session.created_memory_ids),
                json.dumps(session.feedback),
            ),
        )
        self.conn.commit()
        return session.id

    def update_session(self, session: CognitiveSession) -> None:
        self.conn.execute(
            "UPDATE sessions SET client = ?, project_id = ?, domain = ?,"
            " task_profile = ?, initial_query = ?, status = ?, ended_at = ?,"
            " supplied_memory_ids = ?, pack_chars = ?, artifacts = ?,"
            " created_memory_ids = ?, feedback = ? WHERE id = ?",
            (
                session.client, session.project_id, session.domain,
                session.task_profile, session.initial_query,
                getattr(session.status, "value", session.status),
                session.ended_at, json.dumps(session.supplied_memory_ids),
                session.pack_chars, json.dumps(session.artifacts),
                json.dumps(session.created_memory_ids), json.dumps(session.feedback),
                session.id,
            ),
        )
        self.conn.commit()

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> CognitiveSession:
        return CognitiveSession(
            id=row["id"], client=row["client"], project_id=row["project_id"],
            domain=row["domain"], task_profile=row["task_profile"],
            initial_query=row["initial_query"], status=row["status"],
            started_at=row["started_at"], ended_at=row["ended_at"],
            supplied_memory_ids=json.loads(row["supplied_memory_ids"]),
            pack_chars=row["pack_chars"], artifacts=json.loads(row["artifacts"]),
            created_memory_ids=json.loads(row["created_memory_ids"]),
            feedback=json.loads(row["feedback"]),
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
        self.conn.commit()
