"""PostgreSQL backend — the primary, scalable store.

- pgvector for server-side semantic search (``CREATE EXTENSION vector``);
  degrades gracefully to client-side cosine when the extension is missing.
- Native full-text search (tsvector generated column + GIN index, 'simple'
  config so pt-BR and English coexist without stemming surprises).

Requires ``pip install "twin[postgres]"`` (psycopg 3).
"""

from __future__ import annotations

import json
import threading
from typing import Any, Iterable, Optional

from ... import ids
from ...sensory.percept import Percept
from ..crypto import ContentCodec, NullCodec
from ..embeddings import to_blob
from ..models import CognitiveSession, Entity, Evidence, MemoryItem, Project, Relation
from .base import MemoryStore, now_iso

_SCHEMA_BASE = """
CREATE TABLE IF NOT EXISTS percepts (
    id TEXT PRIMARY KEY,
    percept_type TEXT NOT NULL,
    source_sensor TEXT NOT NULL,
    occurred_at TEXT,
    ingested_at TEXT NOT NULL,
    actors JSONB NOT NULL DEFAULT '[]',
    content TEXT NOT NULL,
    content_refs JSONB NOT NULL DEFAULT '[]',
    attachments JSONB NOT NULL DEFAULT '[]',
    privacy_hints JSONB NOT NULL DEFAULT '{}',
    integrity JSONB NOT NULL DEFAULT '{}',
    metadata JSONB NOT NULL DEFAULT '{}',
    source_trust REAL NOT NULL DEFAULT 0.8,
    source_scope TEXT NOT NULL DEFAULT 'work',
    source_confidentiality TEXT NOT NULL DEFAULT 'internal',
    project_id TEXT,
    content_hash TEXT NOT NULL UNIQUE
);
ALTER TABLE percepts ADD COLUMN IF NOT EXISTS source_trust REAL NOT NULL DEFAULT 0.8;
ALTER TABLE percepts ADD COLUMN IF NOT EXISTS source_scope TEXT NOT NULL DEFAULT 'work';
ALTER TABLE percepts ADD COLUMN IF NOT EXISTS source_confidentiality TEXT NOT NULL DEFAULT 'internal';
ALTER TABLE percepts ADD COLUMN IF NOT EXISTS project_id TEXT;

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
    payload JSONB NOT NULL DEFAULT '{}',
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    review_reason TEXT,
    project_id TEXT,
    fts tsvector GENERATED ALWAYS AS (to_tsvector('simple', title || ' ' || summary)) STORED
);
ALTER TABLE memories ADD COLUMN IF NOT EXISTS project_id TEXT;
CREATE INDEX IF NOT EXISTS idx_memories_domain ON memories(domain);
CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type);
CREATE INDEX IF NOT EXISTS idx_memories_fts ON memories USING GIN(fts);

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
CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_name ON entities(LOWER(name));

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

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    aliases JSONB NOT NULL DEFAULT '[]',
    repos JSONB NOT NULL DEFAULT '[]',
    goals JSONB NOT NULL DEFAULT '[]',
    milestones JSONB NOT NULL DEFAULT '[]',
    open_questions JSONB NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_name ON projects(LOWER(name));

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
    supplied_memory_ids JSONB NOT NULL DEFAULT '[]',
    pack_chars INTEGER NOT NULL DEFAULT 0,
    artifacts JSONB NOT NULL DEFAULT '[]',
    created_memory_ids JSONB NOT NULL DEFAULT '[]',
    feedback JSONB NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id);

CREATE TABLE IF NOT EXISTS firewall_log (
    id BIGSERIAL PRIMARY KEY,
    memory_id TEXT NOT NULL,
    target_domain TEXT NOT NULL,
    rule TEXT NOT NULL,
    action TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

_EMBEDDINGS_PGVECTOR = """
CREATE TABLE IF NOT EXISTS embeddings (
    ref_id TEXT NOT NULL,
    ref_type TEXT NOT NULL,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    embedding vector NOT NULL,
    PRIMARY KEY (ref_id, model)
);
"""

_EMBEDDINGS_FALLBACK = """
CREATE TABLE IF NOT EXISTS embeddings (
    ref_id TEXT NOT NULL,
    ref_type TEXT NOT NULL,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    embedding TEXT NOT NULL,
    PRIMARY KEY (ref_id, model)
);
"""


def _vec_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{v:.7g}" for v in vector) + "]"


class PostgresStore(MemoryStore):
    def __init__(self, url: str, codec: ContentCodec | None = None):
        import psycopg
        from psycopg.rows import dict_row

        self.codec = codec or NullCodec()
        self.conn = psycopg.connect(url, row_factory=dict_row, autocommit=True)
        # psycopg connections are not thread-safe; FastAPI sync endpoints run
        # in a thread pool, so serialize access.
        self._lock = threading.RLock()
        with self._lock, self.conn.cursor() as cur:
            try:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                self.has_pgvector = True
            except psycopg.Error:
                self.has_pgvector = False
            cur.execute(_SCHEMA_BASE)
            cur.execute(_EMBEDDINGS_PGVECTOR if self.has_pgvector else _EMBEDDINGS_FALLBACK)

    def close(self) -> None:
        self.conn.close()

    def _exec(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock, self.conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description:
                return cur.fetchall()
            return []

    # -- percepts ---------------------------------------------------------

    def insert_percept(self, percept: Percept) -> Optional[str]:
        percept.seal()
        if self._exec("SELECT id FROM percepts WHERE content_hash = %s", (percept.content_hash,)):
            return None
        self._exec(
            "INSERT INTO percepts (id, percept_type, source_sensor, occurred_at,"
            " ingested_at, actors, content, content_refs, attachments,"
            " privacy_hints, integrity, metadata, source_trust, source_scope,"
            " source_confidentiality, project_id, content_hash)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
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
        return percept.id

    def _row_to_percept(self, row: dict) -> Percept:
        return Percept(
            id=row["id"], percept_type=row["percept_type"],
            source_sensor=row["source_sensor"], occurred_at=row["occurred_at"],
            ingested_at=row["ingested_at"], actors=row["actors"],
            content=self.codec.decrypt(row["content"]), content_refs=row["content_refs"],
            attachments=row["attachments"], privacy_hints=row["privacy_hints"],
            integrity=row["integrity"], metadata=row["metadata"],
            source_trust=row["source_trust"], source_scope=row["source_scope"],
            source_confidentiality=row["source_confidentiality"],
            project_id=row["project_id"],
        )

    def get_percept(self, percept_id: str) -> Optional[Percept]:
        rows = self._exec("SELECT * FROM percepts WHERE id = %s", (percept_id,))
        return self._row_to_percept(rows[0]) if rows else None

    def list_percepts(self) -> list[Percept]:
        return [self._row_to_percept(r)
                for r in self._exec("SELECT * FROM percepts ORDER BY ingested_at")]

    def unprocessed_percepts(self) -> list[Percept]:
        rows = self._exec(
            "SELECT p.* FROM percepts p"
            " WHERE NOT EXISTS (SELECT 1 FROM evidence e WHERE e.percept_id = p.id)"
            " ORDER BY p.ingested_at"
        )
        return [self._row_to_percept(r) for r in rows]

    # -- memories ----------------------------------------------------------

    def insert_memory(self, mem: MemoryItem) -> str:
        ts = now_iso()
        mem.created_at = mem.created_at or ts
        mem.updated_at = ts
        self._exec(
            "INSERT INTO memories (id, type, title, summary, domain, persona,"
            " sensitivity, confidence, status, valid_from, valid_until,"
            " created_at, updated_at, payload, needs_review, review_reason,"
            " project_id)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                mem.id, mem.type.value, mem.title, mem.summary, mem.domain,
                mem.persona, mem.sensitivity.value, mem.confidence,
                mem.status.value, mem.valid_from, mem.valid_until,
                mem.created_at, mem.updated_at, json.dumps(mem.payload),
                mem.needs_review, mem.review_reason, mem.project_id,
            ),
        )
        for name in mem.entities:
            ent = self.upsert_entity(name)
            self._exec(
                "INSERT INTO memory_entities (memory_id, entity_id) VALUES (%s,%s)"
                " ON CONFLICT DO NOTHING",
                (mem.id, ent.id),
            )
        return mem.id

    def _row_to_memory(self, row: dict) -> MemoryItem:
        entities = [
            r["name"] for r in self._exec(
                "SELECT e.name FROM entities e"
                " JOIN memory_entities me ON me.entity_id = e.id"
                " WHERE me.memory_id = %s", (row["id"],)
            )
        ]
        percept_ids = [
            r["percept_id"] for r in self._exec(
                "SELECT DISTINCT percept_id FROM evidence WHERE memory_id = %s", (row["id"],)
            )
        ]
        return MemoryItem(
            id=row["id"], type=row["type"], title=row["title"], summary=row["summary"],
            domain=row["domain"], persona=row["persona"], sensitivity=row["sensitivity"],
            confidence=row["confidence"], status=row["status"],
            valid_from=row["valid_from"], valid_until=row["valid_until"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            payload=row["payload"], needs_review=row["needs_review"],
            review_reason=row["review_reason"], project_id=row["project_id"],
            entities=entities, percept_ids=percept_ids,
        )

    def get_memory(self, memory_id: str) -> Optional[MemoryItem]:
        rows = self._exec("SELECT * FROM memories WHERE id = %s", (memory_id,))
        return self._row_to_memory(rows[0]) if rows else None

    def list_memories(
        self,
        status: Optional[str] = None,
        domain: Optional[str] = None,
        type_: Optional[str] = None,
        needs_review: Optional[bool] = None,
        project_id: Optional[str] = None,
        limit: int = 200,
    ) -> list[MemoryItem]:
        query = "SELECT * FROM memories WHERE TRUE"
        params: list[Any] = []
        if project_id:
            query += " AND project_id = %s"
            params.append(project_id)
        if status:
            query += " AND status = %s"
            params.append(status)
        if domain:
            query += " AND domain = %s"
            params.append(domain)
        if type_:
            query += " AND type = %s"
            params.append(type_)
        if needs_review is not None:
            query += " AND needs_review = %s"
            params.append(needs_review)
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        return [self._row_to_memory(r) for r in self._exec(query, tuple(params))]

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
        sets = ", ".join(f"{k} = %s" for k in updates)
        params = tuple(updates.values()) + (now_iso(), memory_id)
        self._exec(f"UPDATE memories SET {sets}, updated_at = %s WHERE id = %s", params)

    # -- evidence ----------------------------------------------------------

    def insert_evidence(self, ev: Evidence) -> str:
        self._exec(
            "INSERT INTO evidence (id, memory_id, percept_id, quote) VALUES (%s,%s,%s,%s)",
            (ev.id, ev.memory_id, ev.percept_id, self.codec.encrypt(ev.quote)),
        )
        return ev.id

    def get_evidence(self, memory_id: str) -> list[Evidence]:
        rows = self._exec("SELECT id, memory_id, percept_id, quote FROM evidence"
                          " WHERE memory_id = %s", (memory_id,))
        return [Evidence(**{**r, "quote": self.codec.decrypt(r["quote"])}) for r in rows]

    # -- entities & relations ------------------------------------------------

    def upsert_entity(self, name: str, entity_type: str = "generic") -> Entity:
        name = name.strip()
        rows = self._exec("SELECT * FROM entities WHERE LOWER(name) = LOWER(%s)", (name,))
        if rows:
            return Entity(**{k: rows[0][k] for k in ("id", "name", "entity_type", "created_at")})
        ent = Entity(id=ids.entity_id(), name=name, entity_type=entity_type, created_at=now_iso())
        self._exec(
            "INSERT INTO entities (id, name, entity_type, created_at) VALUES (%s,%s,%s,%s)"
            " ON CONFLICT DO NOTHING",
            (ent.id, ent.name, ent.entity_type, ent.created_at),
        )
        return ent

    def get_entity_by_name(self, name: str) -> Optional[Entity]:
        rows = self._exec("SELECT * FROM entities WHERE LOWER(name) = LOWER(%s)", (name.strip(),))
        if not rows:
            return None
        return Entity(**{k: rows[0][k] for k in ("id", "name", "entity_type", "created_at")})

    def list_entities(self) -> list[Entity]:
        rows = self._exec("SELECT id, name, entity_type, created_at FROM entities ORDER BY name")
        return [Entity(**r) for r in rows]

    def insert_relation(self, rel: Relation) -> str:
        rel.created_at = rel.created_at or now_iso()
        self._exec(
            "INSERT INTO relations (id, subject_id, predicate, object_id, memory_id,"
            " valid_from, valid_until, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                rel.id, rel.subject_id, rel.predicate, rel.object_id,
                rel.memory_id, rel.valid_from, rel.valid_until, rel.created_at,
            ),
        )
        return rel.id

    def relations_for(self, node_id: str) -> list[Relation]:
        rows = self._exec(
            "SELECT id, subject_id, predicate, object_id, memory_id, valid_from,"
            " valid_until, created_at FROM relations"
            " WHERE subject_id = %s OR object_id = %s",
            (node_id, node_id),
        )
        return [Relation(**r) for r in rows]

    def memories_for_entity(self, entity_id: str) -> list[MemoryItem]:
        rows = self._exec(
            "SELECT m.* FROM memories m JOIN memory_entities me ON me.memory_id = m.id"
            " WHERE me.entity_id = %s ORDER BY m.created_at DESC",
            (entity_id,),
        )
        return [self._row_to_memory(r) for r in rows]

    # -- embeddings ------------------------------------------------------------

    def store_embedding(self, ref_id: str, ref_type: str, model: str,
                        vector: list[float]) -> None:
        literal = _vec_literal(vector)
        if self.has_pgvector:
            self._exec(
                "INSERT INTO embeddings (ref_id, ref_type, model, dim, embedding)"
                " VALUES (%s,%s,%s,%s,%s::vector)"
                " ON CONFLICT (ref_id, model) DO UPDATE SET embedding = EXCLUDED.embedding,"
                " dim = EXCLUDED.dim, ref_type = EXCLUDED.ref_type",
                (ref_id, ref_type, model, len(vector), literal),
            )
        else:
            self._exec(
                "INSERT INTO embeddings (ref_id, ref_type, model, dim, embedding)"
                " VALUES (%s,%s,%s,%s,%s)"
                " ON CONFLICT (ref_id, model) DO UPDATE SET embedding = EXCLUDED.embedding,"
                " dim = EXCLUDED.dim, ref_type = EXCLUDED.ref_type",
                (ref_id, ref_type, model, len(vector), literal),
            )

    def iter_embeddings(self, ref_type: str, model: str) -> Iterable[tuple[str, bytes]]:
        rows = self._exec(
            "SELECT ref_id, embedding::text AS emb FROM embeddings"
            " WHERE ref_type = %s AND model = %s",
            (ref_type, model),
        )
        for r in rows:
            yield r["ref_id"], to_blob(json.loads(r["emb"]))

    def similar(self, query_vec: list[float], ref_type: str, model: str,
                min_sim: float = 0.05) -> dict[str, float]:
        if not self.has_pgvector:
            return super().similar(query_vec, ref_type, model, min_sim)
        rows = self._exec(
            "SELECT ref_id, 1 - (embedding <=> %s::vector) AS sim FROM embeddings"
            " WHERE ref_type = %s AND model = %s AND dim = %s",
            (_vec_literal(query_vec), ref_type, model, len(query_vec)),
        )
        return {r["ref_id"]: float(r["sim"]) for r in rows if r["sim"] >= min_sim}

    # -- fts ---------------------------------------------------------------------

    def fts_search(self, query: str, limit: int = 50) -> dict[str, float]:
        terms = self.sanitize_fts_terms(query)
        if not terms:
            return {}
        tsquery = " | ".join(terms)
        rows = self._exec(
            "SELECT id, ts_rank(fts, q) AS score FROM memories,"
            " to_tsquery('simple', %s) q WHERE fts @@ q"
            " ORDER BY score DESC LIMIT %s",
            (tsquery, limit),
        )
        return {r["id"]: float(r["score"]) for r in rows}

    # -- projects -----------------------------------------------------------------

    def insert_project(self, project: Project) -> str:
        ts = now_iso()
        project.created_at = project.created_at or ts
        project.updated_at = ts
        self._exec(
            "INSERT INTO projects (id, name, aliases, repos, goals, milestones,"
            " open_questions, status, created_at, updated_at, metadata)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                project.id, project.name, json.dumps(project.aliases),
                json.dumps(project.repos), json.dumps(project.goals),
                json.dumps(project.milestones), json.dumps(project.open_questions),
                project.status, project.created_at, project.updated_at,
                json.dumps(project.metadata),
            ),
        )
        return project.id

    def update_project(self, project: Project) -> None:
        project.updated_at = now_iso()
        self._exec(
            "UPDATE projects SET name = %s, aliases = %s, repos = %s, goals = %s,"
            " milestones = %s, open_questions = %s, status = %s, updated_at = %s,"
            " metadata = %s WHERE id = %s",
            (
                project.name, json.dumps(project.aliases), json.dumps(project.repos),
                json.dumps(project.goals), json.dumps(project.milestones),
                json.dumps(project.open_questions), project.status,
                project.updated_at, json.dumps(project.metadata), project.id,
            ),
        )

    @staticmethod
    def _row_to_project(row: dict) -> Project:
        return Project(
            id=row["id"], name=row["name"], aliases=row["aliases"],
            repos=row["repos"], goals=row["goals"], milestones=row["milestones"],
            open_questions=row["open_questions"], status=row["status"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            metadata=row["metadata"],
        )

    def get_project(self, project_id: str) -> Optional[Project]:
        rows = self._exec("SELECT * FROM projects WHERE id = %s", (project_id,))
        return self._row_to_project(rows[0]) if rows else None

    def list_projects(self, status: Optional[str] = None) -> list[Project]:
        if status:
            rows = self._exec("SELECT * FROM projects WHERE status = %s ORDER BY name", (status,))
        else:
            rows = self._exec("SELECT * FROM projects ORDER BY name")
        return [self._row_to_project(r) for r in rows]

    # -- cognitive sessions ----------------------------------------------------------

    def insert_session(self, session: CognitiveSession) -> str:
        session.started_at = session.started_at or now_iso()
        self._exec(
            "INSERT INTO sessions (id, client, project_id, domain, task_profile,"
            " initial_query, status, started_at, ended_at, supplied_memory_ids,"
            " pack_chars, artifacts, created_memory_ids, feedback)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
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
        return session.id

    def update_session(self, session: CognitiveSession) -> None:
        self._exec(
            "UPDATE sessions SET client = %s, project_id = %s, domain = %s,"
            " task_profile = %s, initial_query = %s, status = %s, ended_at = %s,"
            " supplied_memory_ids = %s, pack_chars = %s, artifacts = %s,"
            " created_memory_ids = %s, feedback = %s WHERE id = %s",
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

    @staticmethod
    def _row_to_session(row: dict) -> CognitiveSession:
        return CognitiveSession(
            id=row["id"], client=row["client"], project_id=row["project_id"],
            domain=row["domain"], task_profile=row["task_profile"],
            initial_query=row["initial_query"], status=row["status"],
            started_at=row["started_at"], ended_at=row["ended_at"],
            supplied_memory_ids=row["supplied_memory_ids"], pack_chars=row["pack_chars"],
            artifacts=row["artifacts"], created_memory_ids=row["created_memory_ids"],
            feedback=row["feedback"],
        )

    def get_session(self, session_id: str) -> Optional[CognitiveSession]:
        rows = self._exec("SELECT * FROM sessions WHERE id = %s", (session_id,))
        return self._row_to_session(rows[0]) if rows else None

    def list_sessions(self, status: Optional[str] = None,
                      project_id: Optional[str] = None,
                      limit: int = 200) -> list[CognitiveSession]:
        query = "SELECT * FROM sessions WHERE TRUE"
        params: list[Any] = []
        if status:
            query += " AND status = %s"
            params.append(status)
        if project_id:
            query += " AND project_id = %s"
            params.append(project_id)
        query += " ORDER BY started_at DESC LIMIT %s"
        params.append(limit)
        return [self._row_to_session(r) for r in self._exec(query, tuple(params))]

    # -- metrics -----------------------------------------------------------------

    def count_evidence(self) -> int:
        return int(self._exec("SELECT COUNT(*) AS n FROM evidence")[0]["n"])

    def count_firewall_blocks(self) -> int:
        return int(self._exec(
            "SELECT COUNT(*) AS n FROM firewall_log WHERE action = 'block'"
        )[0]["n"])

    # -- firewall log ----------------------------------------------------------------

    def log_firewall(self, memory_id: str, target_domain: str, rule: str, action: str) -> None:
        self._exec(
            "INSERT INTO firewall_log (memory_id, target_domain, rule, action, created_at)"
            " VALUES (%s,%s,%s,%s,%s)",
            (memory_id, target_domain, rule, action, now_iso()),
        )
