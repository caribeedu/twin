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
from ..models import (
    Artifact, CognitiveSession, DetectionSignal, Entity, Evidence, MemoryItem,
    MemoryOperation, PerceptInterpretation, Project, Relation, ReviewBatch,
    ReviewFinding,
)
from .base import MemoryStore, now_iso
from .connector_mixin import ConnectorStoreMixin
from .correlation_mixin import CORRELATION_SCHEMA, CorrelationStoreMixin
from .host_binding_mixin import HOST_BINDING_SCHEMA, HostBindingStoreMixin
from .judgment_mixin import JudgmentStoreMixin
from .privacy_mixin import PrivacyStoreMixin
from .workspace_ops_mixin import WORKSPACE_OPS_SCHEMA, WorkspaceOpsStoreMixin

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

CREATE TABLE IF NOT EXISTS percept_interpretations (
    percept_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'deferred',
    failure_class TEXT NOT NULL DEFAULT '',
    interpretation_attempted BOOLEAN NOT NULL DEFAULT FALSE,
    terminal BOOLEAN NOT NULL DEFAULT FALSE,
    next_attempt_at TEXT NOT NULL DEFAULT '',
    interpreter TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',
    schema_version TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0,
    items_catalogued INTEGER NOT NULL DEFAULT 0,
    unresolved_count INTEGER NOT NULL DEFAULT 0,
    detail TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    stage_counts JSONB NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
ALTER TABLE percept_interpretations ADD COLUMN IF NOT EXISTS failure_class TEXT NOT NULL DEFAULT '';
ALTER TABLE percept_interpretations ADD COLUMN IF NOT EXISTS interpretation_attempted BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE percept_interpretations ADD COLUMN IF NOT EXISTS terminal BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE percept_interpretations ADD COLUMN IF NOT EXISTS next_attempt_at TEXT NOT NULL DEFAULT '';
ALTER TABLE percept_interpretations ADD COLUMN IF NOT EXISTS stage_counts JSONB NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS detection_signals (
    id TEXT PRIMARY KEY,
    percept_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    span TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'
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
    created_memory_ids JSONB NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id);
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS last_activity_at TEXT NOT NULL DEFAULT '';
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS consolidation_status TEXT NOT NULL DEFAULT 'none';
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS consolidation_error TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS summary_percept_id TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS judgment_snapshot_id TEXT;

-- append-only: concurrent observers never rewrite each other's rows
CREATE TABLE IF NOT EXISTS session_artifacts (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    ref TEXT,
    note TEXT,
    percept_id TEXT,
    observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_session_artifacts ON session_artifacts(session_id);

CREATE TABLE IF NOT EXISTS session_feedback (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'session',
    verdict TEXT NOT NULL,
    memory_id TEXT,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_session_feedback ON session_feedback(session_id);

CREATE TABLE IF NOT EXISTS firewall_log (
    id BIGSERIAL PRIMARY KEY,
    memory_id TEXT NOT NULL,
    target_domain TEXT NOT NULL,
    rule TEXT NOT NULL,
    action TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- v0.3 quality / provenance / review
ALTER TABLE memories ADD COLUMN IF NOT EXISTS review_priority REAL NOT NULL DEFAULT 0;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS quality_score REAL NOT NULL DEFAULT 0;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS quality_flags JSONB NOT NULL DEFAULT '[]';
ALTER TABLE memories ADD COLUMN IF NOT EXISTS impact TEXT NOT NULL DEFAULT 'medium';
ALTER TABLE memories ADD COLUMN IF NOT EXISTS reviewed_at TEXT;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS review_batch_id TEXT;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS canonical_claim JSONB NOT NULL DEFAULT '{}';
ALTER TABLE memories ADD COLUMN IF NOT EXISTS extractor_version JSONB NOT NULL DEFAULT '{}';
ALTER TABLE memories ADD COLUMN IF NOT EXISTS last_reconciled_at TEXT;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS retrieval_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS last_retrieved_at TEXT;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS deleted_at TEXT;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS deletion_reason TEXT;

ALTER TABLE evidence ADD COLUMN IF NOT EXISTS evidence_type TEXT NOT NULL DEFAULT 'verbatim';
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS directness REAL NOT NULL DEFAULT 1.0;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS source_trust REAL NOT NULL DEFAULT 0.8;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS independence_group TEXT;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS supports BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS span_start INTEGER;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS span_end INTEGER;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS artifact_id TEXT;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS deleted_at TEXT;

ALTER TABLE entities ADD COLUMN IF NOT EXISTS aliases JSONB NOT NULL DEFAULT '[]';
ALTER TABLE entities ADD COLUMN IF NOT EXISTS canonical_id TEXT;

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
    content_destroyed BOOLEAN NOT NULL DEFAULT FALSE,
    metadata JSONB NOT NULL DEFAULT '{}'
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
    requires_human_review BOOLEAN NOT NULL DEFAULT TRUE,
    resolved BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    metadata JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'open',
    analyzer_version TEXT NOT NULL DEFAULT 'quality-v1',
    resolution_operation_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_findings_memory ON review_findings(memory_id);
ALTER TABLE review_findings ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'open';
ALTER TABLE review_findings ADD COLUMN IF NOT EXISTS analyzer_version TEXT NOT NULL DEFAULT 'quality-v1';
ALTER TABLE review_findings ADD COLUMN IF NOT EXISTS resolution_operation_id TEXT;

CREATE TABLE IF NOT EXISTS review_batches (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    query JSONB NOT NULL DEFAULT '{}',
    memory_ids JSONB NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    progress_total INTEGER NOT NULL DEFAULT 0,
    progress_reviewed INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS memory_operations (
    id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'user',
    at TEXT NOT NULL,
    inputs JSONB NOT NULL DEFAULT '[]',
    output TEXT,
    before_state JSONB NOT NULL DEFAULT '{}',
    after_state JSONB NOT NULL DEFAULT '{}',
    undoable BOOLEAN NOT NULL DEFAULT TRUE,
    undone_at TEXT
);

CREATE TABLE IF NOT EXISTS judgment_items (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    statement TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    domain TEXT NOT NULL DEFAULT 'technical',
    persona TEXT NOT NULL DEFAULT 'individual',
    scope JSONB NOT NULL DEFAULT '{}',
    strength DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    stability TEXT NOT NULL DEFAULT 'evolving',
    status TEXT NOT NULL DEFAULT 'candidate',
    valid_from TEXT,
    valid_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    approved_at TEXT,
    approved_by TEXT,
    provenance JSONB NOT NULL DEFAULT '{}',
    exceptions JSONB NOT NULL DEFAULT '[]',
    conflicts_with JSONB NOT NULL DEFAULT '[]',
    supersedes TEXT,
    tradeoff TEXT,
    lean DOUBLE PRECISION,
    current_revision_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1,
    metadata JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_judgment_status ON judgment_items(status);
CREATE INDEX IF NOT EXISTS idx_judgment_kind ON judgment_items(kind);
CREATE INDEX IF NOT EXISTS idx_judgment_domain ON judgment_items(domain);

CREATE TABLE IF NOT EXISTS judgment_revisions (
    id TEXT PRIMARY KEY,
    judgment_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    payload JSONB NOT NULL,
    created_at TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'user',
    reason TEXT NOT NULL DEFAULT '',
    UNIQUE(judgment_id, revision)
);
CREATE INDEX IF NOT EXISTS idx_jrev_judgment ON judgment_revisions(judgment_id);

CREATE TABLE IF NOT EXISTS judgment_proposals (
    id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    target_judgment_id TEXT,
    expected_revision_id TEXT,
    proposed_item JSONB NOT NULL DEFAULT '{}',
    reason TEXT NOT NULL DEFAULT '',
    supporting_memory_ids JSONB NOT NULL DEFAULT '[]',
    contradicting_memory_ids JSONB NOT NULL DEFAULT '[]',
    support_count INTEGER NOT NULL DEFAULT 0,
    contradiction_count INTEGER NOT NULL DEFAULT 0,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    scope JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    expires_at TEXT,
    preview_token TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_jprop_status ON judgment_proposals(status);

CREATE TABLE IF NOT EXISTS judgment_versions (
    id TEXT PRIMARY KEY,
    version INTEGER NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    parent_version_id TEXT,
    active INTEGER NOT NULL DEFAULT 0,
    revision_ids JSONB NOT NULL DEFAULT '[]',
    item_ids JSONB NOT NULL DEFAULT '[]',
    actor TEXT NOT NULL DEFAULT 'user',
    metadata JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_jver_active ON judgment_versions(active);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jver_one_active ON judgment_versions ((active)) WHERE active != 0;

CREATE TABLE IF NOT EXISTS judgment_snapshots (
    id TEXT PRIMARY KEY,
    judgment_version_id TEXT NOT NULL,
    item_ids JSONB NOT NULL DEFAULT '[]',
    applied_revisions JSONB NOT NULL DEFAULT '[]',
    target_domain TEXT NOT NULL DEFAULT 'technical',
    persona TEXT NOT NULL DEFAULT 'individual',
    task_profile TEXT NOT NULL DEFAULT 'general',
    project_id TEXT,
    audience TEXT,
    client TEXT,
    project_stage TEXT,
    application_engine TEXT NOT NULL DEFAULT 'judgment-app-v2',
    created_at TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS judgment_conflicts (
    id TEXT PRIMARY KEY,
    judgment_id TEXT NOT NULL,
    memory_ids JSONB NOT NULL DEFAULT '[]',
    other_judgment_id TEXT,
    type TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'open',
    suggested_resolution TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution_operation_id TEXT,
    proposal_id TEXT,
    analyzer_version TEXT NOT NULL DEFAULT 'conflict-v1',
    evidence_fingerprint TEXT NOT NULL DEFAULT '',
    metadata JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_jconf_status ON judgment_conflicts(status);

CREATE TABLE IF NOT EXISTS judgment_traces (
    id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    applied_items JSONB NOT NULL DEFAULT '[]',
    blocked_options JSONB NOT NULL DEFAULT '[]',
    exceptions_used JSONB NOT NULL DEFAULT '[]',
    result JSONB NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS privacy_policies (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    effect TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    enabled INTEGER NOT NULL DEFAULT 1,
    overrideable INTEGER NOT NULL DEFAULT 1,
    constitutional INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS privacy_policy_sets (
    id TEXT PRIMARY KEY,
    version INTEGER NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    policy_ids TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 1,
    actor TEXT NOT NULL DEFAULT 'user',
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS privacy_decisions (
    id TEXT PRIMARY KEY,
    request_fingerprint TEXT NOT NULL DEFAULT '',
    effect TEXT NOT NULL,
    payload TEXT NOT NULL,
    policy_set_version_id TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS permission_grants (
    id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    persona TEXT NOT NULL DEFAULT 'individual',
    purpose TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    uses INTEGER NOT NULL DEFAULT 0,
    max_uses INTEGER,
    version INTEGER NOT NULL DEFAULT 1,
    valid_from TEXT NOT NULL DEFAULT '',
    valid_until TEXT,
    revoked_at TEXT,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS consent_records (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS quarantine_records (
    id TEXT PRIMARY KEY,
    artifact_id TEXT,
    percept_id TEXT,
    status TEXT NOT NULL DEFAULT 'quarantined',
    content_fingerprint TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_quarantine_fp ON quarantine_records(content_fingerprint);
CREATE TABLE IF NOT EXISTS leakage_canaries (
    id TEXT PRIMARY KEY,
    token TEXT NOT NULL UNIQUE,
    vault_id TEXT NOT NULL DEFAULT 'vault_general',
    active INTEGER NOT NULL DEFAULT 1,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS deletion_requests (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'preview',
    mode TEXT NOT NULL DEFAULT 'delete',
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS export_records (
    id TEXT PRIMARY KEY,
    purpose TEXT NOT NULL DEFAULT 'backup',
    destination TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS redaction_plans (
    id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS privacy_principals (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS privacy_tools (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS privacy_vaults (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS privacy_client_bindings (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL UNIQUE,
    tool_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS privacy_policy_revisions (
    id TEXT PRIMARY KEY,
    policy_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ''
);
"""

_CONNECTOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS connector_source_accounts (
    id TEXT PRIMARY KEY,
    connector_type TEXT NOT NULL,
    source_owner TEXT NOT NULL DEFAULT 'unknown',
    vault_id TEXT NOT NULL DEFAULT 'vault_general',
    enabled INTEGER NOT NULL DEFAULT 1,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS connector_instances (
    id TEXT PRIMARY KEY,
    connector_type TEXT NOT NULL,
    account_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    credential_ref TEXT,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS connector_credential_refs (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'encrypted_file',
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS connector_checkpoints (
    id TEXT PRIMARY KEY,
    connector_id TEXT NOT NULL,
    stream TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL,
    UNIQUE(connector_id, stream)
);
CREATE TABLE IF NOT EXISTS connector_batches (
    id TEXT PRIMARY KEY,
    connector_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    created_at TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cbatch_conn ON connector_batches(connector_id);
CREATE TABLE IF NOT EXISTS connector_raw_items (
    id TEXT PRIMARY KEY,
    connector_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    content_hash TEXT NOT NULL DEFAULT '',
    deleted INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_craw_conn ON connector_raw_items(connector_id);
CREATE TABLE IF NOT EXISTS connector_records (
    id TEXT PRIMARY KEY,
    connector_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    external_type TEXT NOT NULL DEFAULT '',
    external_id TEXT NOT NULL DEFAULT '',
    deleted INTEGER NOT NULL DEFAULT 0,
    percept_id TEXT,
    quarantined INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crec_conn ON connector_records(connector_id);
CREATE INDEX IF NOT EXISTS idx_crec_object ON connector_records(connector_id, external_type, external_id);
CREATE TABLE IF NOT EXISTS connector_dead_letters (
    id TEXT PRIMARY KEY,
    connector_id TEXT NOT NULL,
    external_id TEXT NOT NULL DEFAULT '',
    failure_class TEXT NOT NULL DEFAULT 'normalization',
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cdlq_conn ON connector_dead_letters(connector_id);
CREATE TABLE IF NOT EXISTS connector_sync_state (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'healthy',
    next_run_at TEXT,
    version INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL
);
ALTER TABLE connector_sync_state ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 0;
-- one worker per (connector, stream); leases expire so crashes cannot wedge a stream
CREATE TABLE IF NOT EXISTS connector_stream_leases (
    connector_id TEXT NOT NULL,
    stream TEXT NOT NULL,
    lease_owner TEXT NOT NULL,
    lease_expires_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (connector_id, stream)
);
-- provider tombstones resolved against prior lineage, awaiting the deletion planner
CREATE TABLE IF NOT EXISTS connector_deletion_events (
    id TEXT PRIMARY KEY,
    connector_id TEXT NOT NULL,
    external_type TEXT NOT NULL DEFAULT '',
    external_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cdel_conn ON connector_deletion_events(connector_id);
CREATE TABLE IF NOT EXISTS connector_backfill_jobs (
    id TEXT PRIMARY KEY,
    connector_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    created_at TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL
);
ALTER TABLE connector_backfill_jobs ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_cbf_conn ON connector_backfill_jobs(connector_id);
-- Phase 9: exactly-once counter contributions per terminal batch
CREATE TABLE IF NOT EXISTS connector_counter_batches (
    connector_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    counted_at TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (connector_id, batch_id)
);
CREATE INDEX IF NOT EXISTS idx_ccb_conn ON connector_counter_batches(connector_id);
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


class PostgresStore(
    PrivacyStoreMixin, JudgmentStoreMixin, CorrelationStoreMixin,
    HostBindingStoreMixin, WorkspaceOpsStoreMixin, ConnectorStoreMixin,
    MemoryStore,
):
    def __init__(self, url: str, codec: ContentCodec | None = None):
        import psycopg
        from psycopg.rows import dict_row

        self.codec = codec or NullCodec()
        self.conn = psycopg.connect(url, row_factory=dict_row, autocommit=True)
        # psycopg connections are not thread-safe; FastAPI sync endpoints run
        # in a thread pool, so serialize access.
        self._lock = threading.RLock()
        self._tx_depth = 0
        with self._lock, self.conn.cursor() as cur:
            try:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                self.has_pgvector = True
            except psycopg.Error:
                self.has_pgvector = False
            cur.execute(_SCHEMA_BASE)
            cur.execute(_CONNECTOR_SCHEMA)
            cur.execute(CORRELATION_SCHEMA)
            cur.execute(HOST_BINDING_SCHEMA)
            cur.execute(WORKSPACE_OPS_SCHEMA)
            for stmt in (
                "ALTER TABLE workspace_ticks ADD COLUMN IF NOT EXISTS "
                "error_stage TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE consolidation_runs ADD COLUMN IF NOT EXISTS "
                "error_stage TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE host_session_bindings ADD COLUMN IF NOT EXISTS "
                "occurrence INTEGER NOT NULL DEFAULT 1",
                "ALTER TABLE host_session_bindings ADD COLUMN IF NOT EXISTS "
                "vault_id TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE host_session_bindings ADD COLUMN IF NOT EXISTS "
                "domain TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE host_session_bindings ADD COLUMN IF NOT EXISTS "
                "persona TEXT NOT NULL DEFAULT 'individual'",
                "ALTER TABLE host_session_bindings ADD COLUMN IF NOT EXISTS "
                "purpose TEXT NOT NULL DEFAULT 'task_execution'",
                "ALTER TABLE host_session_bindings ADD COLUMN IF NOT EXISTS "
                "audience TEXT NOT NULL DEFAULT 'self'",
                "ALTER TABLE host_session_bindings ADD COLUMN IF NOT EXISTS "
                "task_profile TEXT NOT NULL DEFAULT ''",
                "DROP INDEX IF EXISTS uq_hsb_host_ext",
            ):
                try:
                    cur.execute(stmt)
                except Exception:
                    pass
            cur.execute(_EMBEDDINGS_PGVECTOR if self.has_pgvector else _EMBEDDINGS_FALLBACK)

    def _begin_transaction(self) -> None:
        with self._lock:
            self.conn.autocommit = False

    def _commit_transaction(self) -> None:
        with self._lock:
            self.conn.commit()
            self.conn.autocommit = True

    def _rollback_transaction(self) -> None:
        with self._lock:
            self.conn.rollback()
            self.conn.autocommit = True

    def _maybe_commit(self) -> None:
        # Postgres runs with autocommit=True outside explicit transactions.
        if getattr(self, "_tx_depth", 0) > 0:
            return
        # no-op when autocommit

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

    # -- interpretation state (v0.7) --------------------------------------

    def _row_to_interpretation(self, row: dict) -> PerceptInterpretation:
        return PerceptInterpretation(
            percept_id=row["percept_id"], status=row["status"],
            failure_class=row["failure_class"],
            interpretation_attempted=bool(row["interpretation_attempted"]),
            terminal=bool(row["terminal"]), next_attempt_at=row["next_attempt_at"],
            interpreter=row["interpreter"], model=row["model"],
            prompt_version=row["prompt_version"], schema_version=row["schema_version"],
            attempts=row["attempts"], items_catalogued=row["items_catalogued"],
            unresolved_count=row["unresolved_count"], detail=row["detail"],
            content_hash=row["content_hash"],
            stage_counts=row["stage_counts"] or {},
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def record_interpretation(self, state: PerceptInterpretation) -> None:
        ts = now_iso()
        state.updated_at = ts
        state.created_at = state.created_at or ts
        self._exec(
            "INSERT INTO percept_interpretations (percept_id, status, failure_class,"
            " interpretation_attempted, terminal, next_attempt_at, interpreter,"
            " model, prompt_version, schema_version, attempts, items_catalogued,"
            " unresolved_count, detail, content_hash, stage_counts, created_at,"
            " updated_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (percept_id) DO UPDATE SET status=EXCLUDED.status,"
            " failure_class=EXCLUDED.failure_class,"
            " interpretation_attempted=EXCLUDED.interpretation_attempted,"
            " terminal=EXCLUDED.terminal, next_attempt_at=EXCLUDED.next_attempt_at,"
            " interpreter=EXCLUDED.interpreter, model=EXCLUDED.model,"
            " prompt_version=EXCLUDED.prompt_version,"
            " schema_version=EXCLUDED.schema_version, attempts=EXCLUDED.attempts,"
            " items_catalogued=EXCLUDED.items_catalogued,"
            " unresolved_count=EXCLUDED.unresolved_count, detail=EXCLUDED.detail,"
            " content_hash=EXCLUDED.content_hash, stage_counts=EXCLUDED.stage_counts,"
            " updated_at=EXCLUDED.updated_at",
            (
                state.percept_id, state.status, state.failure_class,
                state.interpretation_attempted, state.terminal,
                state.next_attempt_at, state.interpreter, state.model,
                state.prompt_version, state.schema_version, state.attempts,
                state.items_catalogued, state.unresolved_count, state.detail,
                state.content_hash, json.dumps(state.stage_counts),
                state.created_at, state.updated_at,
            ),
        )

    # -- detection signals (v0.7 heuristic mode) --------------------------

    def insert_detection_signal(self, signal: DetectionSignal) -> str:
        signal.created_at = signal.created_at or now_iso()
        self._exec(
            "INSERT INTO detection_signals (id, percept_id, kind, span, reason,"
            " confidence, created_at, metadata) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (signal.id, signal.percept_id, signal.kind, signal.span,
             signal.reason, signal.confidence, signal.created_at,
             json.dumps(signal.metadata)),
        )
        return signal.id

    def list_detection_signals(self, percept_id: Optional[str] = None,
                               limit: int = 500) -> list[DetectionSignal]:
        if percept_id:
            rows = self._exec(
                "SELECT * FROM detection_signals WHERE percept_id = %s"
                " ORDER BY created_at LIMIT %s", (percept_id, limit))
        else:
            rows = self._exec(
                "SELECT * FROM detection_signals ORDER BY created_at DESC LIMIT %s",
                (limit,))
        return [DetectionSignal(
            id=r["id"], percept_id=r["percept_id"], kind=r["kind"], span=r["span"],
            reason=r["reason"], confidence=r["confidence"], created_at=r["created_at"],
            metadata=r["metadata"] or {}) for r in rows]

    def get_interpretation(self, percept_id: str) -> Optional[PerceptInterpretation]:
        rows = self._exec(
            "SELECT * FROM percept_interpretations WHERE percept_id = %s",
            (percept_id,),
        )
        return self._row_to_interpretation(rows[0]) if rows else None

    def list_interpretations(
        self, status: Optional[str] = None, limit: int = 200,
    ) -> list[PerceptInterpretation]:
        if status:
            rows = self._exec(
                "SELECT * FROM percept_interpretations WHERE status = %s"
                " ORDER BY updated_at DESC LIMIT %s", (status, limit),
            )
        else:
            rows = self._exec(
                "SELECT * FROM percept_interpretations"
                " ORDER BY updated_at DESC LIMIT %s", (limit,),
            )
        return [self._row_to_interpretation(r) for r in rows]

    def percepts_pending_interpretation(
        self, *, max_attempts: int, limit: int = 500,
    ) -> list[Percept]:
        # See SqliteStore for the semantics: outage ('deferred') is always
        # eligible and never consumes the attempt budget; only 'error' is
        # bounded by max_attempts, gated by next_attempt_at backoff.
        now = now_iso()
        rows = self._exec(
            "SELECT p.* FROM percepts p"
            " LEFT JOIN percept_interpretations i ON i.percept_id = p.id"
            " WHERE i.percept_id IS NULL"
            "    OR (i.terminal = FALSE"
            "        AND i.status IN ('deferred','error')"
            "        AND (i.content_hash = '' OR i.content_hash = p.content_hash)"
            "        AND (i.status = 'deferred' OR i.attempts < %s)"
            "        AND (i.next_attempt_at = '' OR i.next_attempt_at <= %s))"
            " ORDER BY p.ingested_at LIMIT %s",
            (max_attempts, now, limit),
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
        from ..models import CanonicalClaim, ExtractorVersion
        entities = [
            r["name"] for r in self._exec(
                "SELECT e.name FROM entities e"
                " JOIN memory_entities me ON me.entity_id = e.id"
                " WHERE me.memory_id = %s", (row["id"],)
            )
        ]
        percept_ids = [
            r["percept_id"] for r in self._exec(
                "SELECT DISTINCT percept_id FROM evidence WHERE memory_id = %s"
                " AND deleted_at IS NULL", (row["id"],)
            )
        ]
        claim_raw = row.get("canonical_claim") or {}
        ext_raw = row.get("extractor_version") or {}
        if isinstance(claim_raw, str):
            claim_raw = json.loads(claim_raw)
        if isinstance(ext_raw, str):
            ext_raw = json.loads(ext_raw)
        flags = row.get("quality_flags") or []
        if isinstance(flags, str):
            flags = json.loads(flags)
        return MemoryItem(
            id=row["id"], type=row["type"], title=row["title"], summary=row["summary"],
            domain=row["domain"], persona=row["persona"], sensitivity=row["sensitivity"],
            confidence=row["confidence"], status=row["status"],
            valid_from=row["valid_from"], valid_until=row["valid_until"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            payload=row["payload"], needs_review=row["needs_review"],
            review_reason=row["review_reason"], project_id=row["project_id"],
            entities=entities, percept_ids=percept_ids,
            review_priority=float(row.get("review_priority") or 0),
            quality_score=float(row.get("quality_score") or 0),
            quality_flags=flags,
            impact=row.get("impact") or "medium",
            reviewed_at=row.get("reviewed_at"),
            review_batch_id=row.get("review_batch_id"),
            canonical_claim=CanonicalClaim(**claim_raw) if claim_raw else None,
            extractor_version=ExtractorVersion(**ext_raw) if ext_raw else None,
            last_reconciled_at=row.get("last_reconciled_at"),
            retrieval_count=int(row.get("retrieval_count") or 0),
            last_retrieved_at=row.get("last_retrieved_at"),
            deleted_at=row.get("deleted_at"),
            deletion_reason=row.get("deletion_reason"),
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
            "payload", "project_id", "review_priority", "quality_score", "quality_flags",
            "impact", "reviewed_at", "review_batch_id", "canonical_claim",
            "extractor_version", "last_reconciled_at", "retrieval_count",
            "last_retrieved_at", "deleted_at", "deletion_reason",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        for key in ("payload", "quality_flags", "canonical_claim", "extractor_version"):
            if key in updates and not isinstance(updates[key], str):
                val = updates[key]
                if hasattr(val, "model_dump"):
                    val = val.model_dump()
                updates[key] = json.dumps(val or ({} if key != "quality_flags" else []))
        sets = ", ".join(f"{k} = %s" for k in updates)
        params = list(updates.values()) + [now_iso(), memory_id]
        self._exec(f"UPDATE memories SET {sets}, updated_at = %s WHERE id = %s", tuple(params))

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
        session.last_activity_at = session.last_activity_at or session.started_at
        self._exec(
            "INSERT INTO sessions (id, client, project_id, domain, task_profile,"
            " initial_query, status, started_at, ended_at, last_activity_at,"
            " supplied_memory_ids, pack_chars, created_memory_ids,"
            " consolidation_status, consolidation_error, summary_percept_id,"
            " judgment_snapshot_id)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                session.id, session.client, session.project_id, session.domain,
                session.task_profile, session.initial_query,
                getattr(session.status, "value", session.status),
                session.started_at, session.ended_at, session.last_activity_at,
                json.dumps(session.supplied_memory_ids), session.pack_chars,
                json.dumps(session.created_memory_ids),
                getattr(session.consolidation_status, "value", session.consolidation_status),
                session.consolidation_error, session.summary_percept_id,
                session.judgment_snapshot_id,
            ),
        )
        return session.id

    def update_session(self, session: CognitiveSession) -> None:
        self._exec(
            "UPDATE sessions SET client = %s, project_id = %s, domain = %s,"
            " task_profile = %s, initial_query = %s, status = %s, ended_at = %s,"
            " last_activity_at = %s, supplied_memory_ids = %s, pack_chars = %s,"
            " created_memory_ids = %s, consolidation_status = %s,"
            " consolidation_error = %s, summary_percept_id = %s,"
            " judgment_snapshot_id = %s WHERE id = %s",
            (
                session.client, session.project_id, session.domain,
                session.task_profile, session.initial_query,
                getattr(session.status, "value", session.status),
                session.ended_at, session.last_activity_at or now_iso(),
                json.dumps(session.supplied_memory_ids), session.pack_chars,
                json.dumps(session.created_memory_ids),
                getattr(session.consolidation_status, "value", session.consolidation_status),
                session.consolidation_error, session.summary_percept_id,
                session.judgment_snapshot_id,
                session.id,
            ),
        )

    def append_session_artifact(self, session_id: str, artifact: dict) -> None:
        with self._lock, self.conn.transaction(), self.conn.cursor() as cur:
            cur.execute(
                "UPDATE sessions SET last_activity_at = %s"
                " WHERE id = %s AND status = 'active'",
                (now_iso(), session_id),
            )
            if cur.rowcount == 0:
                cur.execute("SELECT status FROM sessions WHERE id = %s", (session_id,))
                row = cur.fetchone()
                if row is None:
                    raise ValueError(f"session {session_id} not found")
                raise ValueError(f"session {session_id} is {row['status']}, not active")
            cur.execute(
                "INSERT INTO session_artifacts (session_id, kind, ref, note,"
                " percept_id, observed_at) VALUES (%s,%s,%s,%s,%s,%s)",
                (session_id, artifact.get("kind", "artifact"), artifact.get("ref"),
                 artifact.get("note"), artifact.get("percept_id"),
                 artifact.get("at") or now_iso()),
            )

    def append_session_feedback(self, session_id: str, feedback: dict) -> None:
        with self._lock, self.conn.transaction(), self.conn.cursor() as cur:
            cur.execute(
                "UPDATE sessions SET last_activity_at = %s WHERE id = %s",
                (now_iso(), session_id),
            )
            if cur.rowcount == 0:
                raise ValueError(f"session {session_id} not found")
            cur.execute(
                "INSERT INTO session_feedback (session_id, scope, verdict, memory_id,"
                " note, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
                (session_id, feedback.get("scope", "session"), feedback["verdict"],
                 feedback.get("memory_id"), feedback.get("note", ""),
                 feedback.get("at") or now_iso()),
            )

    def transition_session(self, session_id: str, from_status: str,
                           to_status: str, ended_at: Optional[str] = None) -> bool:
        with self._lock, self.conn.cursor() as cur:
            cur.execute(
                "UPDATE sessions SET status = %s, ended_at = COALESCE(%s, ended_at),"
                " last_activity_at = %s WHERE id = %s AND status = %s",
                (to_status, ended_at, now_iso(), session_id, from_status),
            )
            return cur.rowcount > 0

    def _session_artifacts(self, session_id: str) -> list[dict]:
        rows = self._exec(
            "SELECT kind, ref, note, percept_id, observed_at FROM session_artifacts"
            " WHERE session_id = %s ORDER BY id", (session_id,)
        )
        return [
            {k: r[k] for k in ("kind", "ref", "note", "percept_id") if r[k] is not None}
            | {"at": r["observed_at"]}
            for r in rows
        ]

    def _session_feedback(self, session_id: str) -> list[dict]:
        rows = self._exec(
            "SELECT scope, verdict, memory_id, note, created_at FROM session_feedback"
            " WHERE session_id = %s ORDER BY id", (session_id,)
        )
        return [
            {"scope": r["scope"], "verdict": r["verdict"], "memory_id": r["memory_id"],
             "note": r["note"], "at": r["created_at"]}
            for r in rows
        ]

    def _row_to_session(self, row: dict) -> CognitiveSession:
        return CognitiveSession(
            id=row["id"], client=row["client"], project_id=row["project_id"],
            domain=row["domain"], task_profile=row["task_profile"],
            initial_query=row["initial_query"], status=row["status"],
            started_at=row["started_at"], ended_at=row["ended_at"],
            last_activity_at=row["last_activity_at"],
            supplied_memory_ids=row["supplied_memory_ids"], pack_chars=row["pack_chars"],
            artifacts=self._session_artifacts(row["id"]),
            created_memory_ids=row["created_memory_ids"],
            feedback=self._session_feedback(row["id"]),
            consolidation_status=row["consolidation_status"],
            consolidation_error=row["consolidation_error"],
            summary_percept_id=row["summary_percept_id"],
            judgment_snapshot_id=row.get("judgment_snapshot_id"),
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

    # -- v0.3 artifacts / findings / batches / operations -------------------------

    def delete_embedding(self, ref_id: str) -> None:
        self._exec("DELETE FROM embeddings WHERE ref_id = %s", (ref_id,))

    def insert_artifact(self, art: Artifact) -> str:
        art.created_at = art.created_at or now_iso()
        self._exec(
            "INSERT INTO artifacts (id, kind, external_id, source_system, uri,"
            " content_hash, occurred_at, created_at, deleted_at, deletion_reason,"
            " content_destroyed, metadata) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                art.id, art.kind, art.external_id, art.source_system, art.uri,
                art.content_hash, art.occurred_at, art.created_at, art.deleted_at,
                art.deletion_reason, art.content_destroyed, json.dumps(art.metadata),
            ),
        )
        return art.id

    def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        rows = self._exec("SELECT * FROM artifacts WHERE id = %s", (artifact_id,))
        return self._row_to_artifact(rows[0]) if rows else None

    def find_artifact_by_hash(self, content_hash: str) -> Optional[Artifact]:
        rows = self._exec(
            "SELECT * FROM artifacts WHERE content_hash = %s AND deleted_at IS NULL",
            (content_hash,),
        )
        return self._row_to_artifact(rows[0]) if rows else None

    def list_artifacts(self) -> list[Artifact]:
        return [self._row_to_artifact(r) for r in self._exec(
            "SELECT * FROM artifacts ORDER BY created_at"
        )]

    @staticmethod
    def _row_to_artifact(row: dict) -> Artifact:
        return Artifact(
            id=row["id"], kind=row["kind"], external_id=row["external_id"],
            source_system=row["source_system"], uri=row["uri"],
            content_hash=row["content_hash"], occurred_at=row["occurred_at"],
            created_at=row["created_at"], deleted_at=row["deleted_at"],
            deletion_reason=row["deletion_reason"],
            content_destroyed=bool(row["content_destroyed"]),
            metadata=row["metadata"] if isinstance(row["metadata"], dict)
            else json.loads(row["metadata"] or "{}"),
        )

    def tombstone_artifact(self, artifact_id: str, *, reason: str,
                           destroy_content: bool = True) -> None:
        self._exec(
            "UPDATE artifacts SET deleted_at = %s, deletion_reason = %s,"
            " content_destroyed = %s WHERE id = %s",
            (now_iso(), reason, destroy_content, artifact_id),
        )

    def tombstone_percept(self, percept_id: str, *, reason: str,
                          destroy_content: bool = True) -> None:
        rows = self._exec("SELECT metadata FROM percepts WHERE id = %s", (percept_id,))
        if not rows:
            return
        meta = rows[0]["metadata"] if isinstance(rows[0]["metadata"], dict) else json.loads(rows[0]["metadata"] or "{}")
        meta["tombstoned"] = True
        meta["deletion_reason"] = reason
        if destroy_content:
            self._exec(
                "UPDATE percepts SET content = %s, metadata = %s WHERE id = %s",
                (self.codec.encrypt("[content destroyed]"), json.dumps(meta), percept_id),
            )
        else:
            self._exec("UPDATE percepts SET metadata = %s WHERE id = %s",
                       (json.dumps(meta), percept_id))

    def tombstone_evidence(self, evidence_id: str, *, reason: str) -> None:
        self._exec(
            "UPDATE evidence SET deleted_at = %s, quote = %s WHERE id = %s",
            (now_iso(), f"[tombstoned:{reason}]", evidence_id),
        )

    def list_evidence_for_artifact(self, artifact_id: str) -> list[Evidence]:
        rows = self._exec("SELECT * FROM evidence WHERE artifact_id = %s", (artifact_id,))
        out = []
        for r in rows:
            r = dict(r)
            r["quote"] = self.codec.decrypt(r["quote"])
            r.pop("deleted_at", None)
            out.append(Evidence(**{k: v for k, v in r.items() if k in Evidence.model_fields}))
        return out

    def replace_findings(self, memory_id: str, findings: list[ReviewFinding]) -> None:
        self._exec("DELETE FROM review_findings WHERE memory_id = %s", (memory_id,))
        for f in findings:
            self.insert_finding(f)

    def insert_finding(self, finding: ReviewFinding, commit: bool = True) -> str:
        finding.created_at = finding.created_at or now_iso()
        status = getattr(finding.status, "value", finding.status) or "open"
        resolved = bool(finding.resolved or status != "open")
        self._exec(
            "INSERT INTO review_findings (id, memory_id, type, related_memory_id,"
            " confidence, reason, suggested_action, requires_human_review, resolved,"
            " created_at, resolved_at, metadata, status, analyzer_version,"
            " resolution_operation_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                finding.id, finding.memory_id, finding.type.value, finding.related_memory_id,
                finding.confidence, finding.reason, finding.suggested_action.value,
                finding.requires_human_review, resolved,
                finding.created_at, finding.resolved_at, json.dumps(finding.metadata),
                status, finding.analyzer_version, finding.resolution_operation_id,
            ),
        )
        return finding.id

    def update_finding(self, finding: ReviewFinding, commit: bool = True) -> None:
        status = getattr(finding.status, "value", finding.status) or "open"
        resolved = bool(finding.resolved or status != "open")
        self._exec(
            "UPDATE review_findings SET memory_id = %s, type = %s, related_memory_id = %s,"
            " confidence = %s, reason = %s, suggested_action = %s, requires_human_review = %s,"
            " resolved = %s, resolved_at = %s, metadata = %s, status = %s, analyzer_version = %s,"
            " resolution_operation_id = %s WHERE id = %s",
            (
                finding.memory_id, finding.type.value, finding.related_memory_id,
                finding.confidence, finding.reason, finding.suggested_action.value,
                finding.requires_human_review, resolved, finding.resolved_at,
                json.dumps(finding.metadata), status, finding.analyzer_version,
                finding.resolution_operation_id, finding.id,
            ),
        )

    def get_findings(self, memory_id: str, unresolved_only: bool = True) -> list[ReviewFinding]:
        q = "SELECT * FROM review_findings WHERE memory_id = %s"
        if unresolved_only:
            q += " AND (status = 'open' OR (status IS NULL AND resolved = FALSE))"
        rows = self._exec(q, (memory_id,))
        return [self._row_to_finding(r) for r in rows]

    @staticmethod
    def _row_to_finding(row) -> ReviewFinding:
        keys = set(row.keys())
        meta = row["metadata"]
        if isinstance(meta, str):
            meta = json.loads(meta or "{}")
        status = row["status"] if "status" in keys and row["status"] else (
            "resolved" if row["resolved"] else "open"
        )
        return ReviewFinding(
            id=row["id"], memory_id=row["memory_id"], type=row["type"],
            related_memory_id=row["related_memory_id"],
            confidence=row["confidence"], reason=row["reason"] or "",
            suggested_action=row["suggested_action"] or "none",
            requires_human_review=bool(row["requires_human_review"]),
            status=status,
            resolved=bool(row["resolved"]), created_at=row["created_at"],
            resolved_at=row["resolved_at"],
            analyzer_version=(row["analyzer_version"] if "analyzer_version" in keys
                              else "quality-v1"),
            resolution_operation_id=(row["resolution_operation_id"]
                                     if "resolution_operation_id" in keys else None),
            metadata=meta or {},
        )

    def insert_review_batch(self, batch: ReviewBatch) -> str:
        self._exec(
            "INSERT INTO review_batches (id, name, query, memory_ids, created_at,"
            " completed_at, progress_total, progress_reviewed, metadata)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                batch.id, batch.name, json.dumps(batch.query),
                json.dumps(batch.memory_ids), batch.created_at, batch.completed_at,
                batch.progress_total, batch.progress_reviewed, json.dumps(batch.metadata),
            ),
        )
        return batch.id

    def get_review_batch(self, batch_id: str) -> Optional[ReviewBatch]:
        rows = self._exec("SELECT * FROM review_batches WHERE id = %s", (batch_id,))
        if not rows:
            return None
        row = rows[0]
        return ReviewBatch(
            id=row["id"], name=row["name"],
            query=row["query"] if isinstance(row["query"], dict) else json.loads(row["query"]),
            memory_ids=row["memory_ids"] if isinstance(row["memory_ids"], list)
            else json.loads(row["memory_ids"]),
            created_at=row["created_at"], completed_at=row["completed_at"],
            progress_total=row["progress_total"], progress_reviewed=row["progress_reviewed"],
            metadata=row["metadata"] if isinstance(row["metadata"], dict)
            else json.loads(row["metadata"] or "{}"),
        )

    def update_review_batch(self, batch_id: str, **fields: Any) -> None:
        allowed = {"completed_at", "progress_total", "progress_reviewed", "memory_ids", "metadata"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        for key in ("memory_ids", "metadata"):
            if key in updates and not isinstance(updates[key], str):
                updates[key] = json.dumps(updates[key])
        if not updates:
            return
        sets = ", ".join(f"{k} = %s" for k in updates)
        self._exec(f"UPDATE review_batches SET {sets} WHERE id = %s",
                   tuple(list(updates.values()) + [batch_id]))

    def insert_operation(self, op: MemoryOperation) -> str:
        self._exec(
            "INSERT INTO memory_operations (id, operation, actor, at, inputs, output,"
            " before_state, after_state, undoable, undone_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                op.id, op.operation, op.actor, op.at, json.dumps(op.inputs), op.output,
                json.dumps(op.before), json.dumps(op.after), op.undoable, op.undone_at,
            ),
        )
        return op.id

    def get_operation(self, operation_id: str) -> Optional[MemoryOperation]:
        rows = self._exec("SELECT * FROM memory_operations WHERE id = %s", (operation_id,))
        if not rows:
            return None
        row = rows[0]
        return MemoryOperation(
            id=row["id"], operation=row["operation"], actor=row["actor"], at=row["at"],
            inputs=row["inputs"] if isinstance(row["inputs"], list) else json.loads(row["inputs"]),
            output=row["output"],
            before=row["before_state"] if isinstance(row["before_state"], dict)
            else json.loads(row["before_state"]),
            after=row["after_state"] if isinstance(row["after_state"], dict)
            else json.loads(row["after_state"]),
            undoable=bool(row["undoable"]), undone_at=row["undone_at"],
        )

    def mark_operation_undone(self, operation_id: str) -> None:
        self._exec(
            "UPDATE memory_operations SET undone_at = %s, undoable = FALSE WHERE id = %s",
            (now_iso(), operation_id),
        )

    def bump_retrieval(self, memory_id: str) -> None:
        self._exec(
            "UPDATE memories SET retrieval_count = retrieval_count + 1,"
            " last_retrieved_at = %s WHERE id = %s",
            (now_iso(), memory_id),
        )

    # -- judgment mixin hooks -----------------------------------------------

    def _j_sql(self, sql: str) -> str:
        return sql.replace("?", "%s")

    def _j_exec(self, sql: str, params: tuple):
        # Return a lightweight object with rowcount for CAS callers
        with self._lock, self.conn.cursor() as cur:
            cur.execute(self._j_sql(sql), params)
            class _Result:
                rowcount = cur.rowcount
            return _Result()

    def _consume_grant_row(
        self,
        grant_id: str,
        expected_version: int,
        new_uses: int,
        new_version: int,
        new_status: str,
        new_payload: dict,
    ) -> bool:
        import json
        with self._lock, self.conn.cursor() as cur:
            cur.execute(
                "UPDATE permission_grants SET uses = %s, version = %s, status = %s, payload = %s"
                " WHERE id = %s AND version = %s AND status = 'active'"
                " RETURNING id",
                (
                    new_uses, new_version, new_status,
                    json.dumps(new_payload, default=str),
                    grant_id, expected_version,
                ),
            )
            row = cur.fetchone()
            return row is not None

    def _j_fetchone(self, sql: str, params: tuple):
        rows = self._exec(self._j_sql(sql), params)
        return rows[0] if rows else None

    def _j_fetchall(self, sql: str, params: tuple) -> list:
        return self._exec(self._j_sql(sql), params)

    def _j_commit(self) -> None:
        self._maybe_commit()
