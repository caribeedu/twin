"""Connector framework — persisted entities and enums.

Connectors capture evidence; the cognitive core creates understanding. These
models describe *accounts*, *instances*, *sync bookkeeping* and the normalized
``ConnectorRecord`` envelope — never confirmed Memory or Judgment.

Critical fields are typed enums, not free strings: a typo like
``source_owner="employeer"`` must fail at construction, wherever the model is
built, not only in the service layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from .. import ids
from ..clock import now_iso


class OwnershipClass(str, Enum):
    """Who owns the data behind a source account. Never inferred from a domain."""
    personal = "personal"
    employer = "employer"
    client = "client"
    opensource = "opensource"
    shared = "shared"
    unknown = "unknown"


class SyncMode(str, Enum):
    continuous = "continuous"
    manual = "manual"
    paused = "paused"


class ConnectorStatus(str, Enum):
    # lifecycle — provisioning is compensable, revocation is resumable
    provisioning = "provisioning"
    provisioning_failed = "provisioning_failed"
    awaiting_auth = "awaiting_auth"      # created but no real credential yet
    active = "active"
    paused = "paused"
    revoking = "revoking"
    revoked = "revoked"
    revoked_with_residual_secret = "revoked_with_residual_secret"
    unauthorized = "unauthorized"
    degraded = "degraded"
    failed = "failed"


# Statuses under which a connector may fetch from its source.
SYNCABLE_STATUSES = frozenset({ConnectorStatus.active, ConnectorStatus.degraded})


class BatchStatus(str, Enum):
    planned = "planned"
    fetching = "fetching"
    normalizing = "normalizing"
    quarantining = "quarantining"
    persisting = "persisting"
    committed = "committed"
    partially_failed = "partially_failed"
    failed = "failed"
    aborted = "aborted"


class FailureClass(str, Enum):
    configuration = "configuration"
    authentication = "authentication"
    authorization = "authorization"
    rate_limit = "rate_limit"
    network = "network"
    provider_error = "provider_error"
    schema_change = "schema_change"
    content_error = "content_error"
    quarantine = "quarantine"
    storage = "storage"
    policy_denial = "policy_denial"
    normalization = "normalization"
    # provider returned different content under the SAME external revision —
    # a contract violation that must never silently overwrite evidence
    revision_collision = "revision_collision"


class HealthStatus(str, Enum):
    healthy = "healthy"
    degraded = "degraded"
    awaiting_configuration = "awaiting_configuration"
    paused = "paused"
    unauthorized = "unauthorized"
    revoked = "revoked"
    failed = "failed"
    # never synced / no durable health evidence yet 
    unknown = "unknown"


class DeadLetterStatus(str, Enum):
    open = "open"
    retrying = "retrying"
    resolved = "resolved"
    discarded = "discarded"


class DeletionEventStatus(str, Enum):
    pending = "pending"      # awaiting the deletion planner / review
    planned = "planned"
    applied = "applied"
    dismissed = "dismissed"


def idempotency_key(
    connector_type: str,
    account_id: str,
    external_type: str,
    external_id: str,
    external_revision: str,
) -> str:
    """Stable key: repeat fetch of the same revision must never duplicate."""
    return f"{connector_type}:{account_id}:{external_type}:{external_id}:{external_revision}"


class SourceAccount(BaseModel):
    """One external account. A person may own many across providers.

    ``owner_principal_id`` has NO default: an account created without a
    resolved principal must fail, never silently belong to the privileged
    local principal."""
    id: str = Field(default_factory=lambda: ids.new_id("srcacct"))
    connector_type: str
    external_account_id: str = ""
    display_name: str = ""
    owner_principal_id: str = Field(min_length=1)
    source_owner: OwnershipClass = OwnershipClass.unknown
    org_key: Optional[str] = None            # e.g. "shippo" → vault_work_shippo
    persona: str = "individual"
    vault_id: str = "vault_general"
    default_domain: str = "work"
    confidentiality: str = "internal"        # public|internal|private|restricted
    source_scope: str = "work"
    source_trust: float = Field(default=0.8, ge=0.0, le=1.0)
    enabled: bool = True
    sync_mode: SyncMode = SyncMode.manual
    created_at: str = Field(default_factory=now_iso)
    revoked_at: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConnectorInstance(BaseModel):
    """A concrete install of a connector type against one account."""
    id: str = Field(default_factory=lambda: ids.new_id("conn"))
    connector_type: str
    account_id: str
    adapter_version: str = "1.0"
    schema_version: int = Field(default=1, ge=1)
    credential_ref: Optional[str] = None
    status: ConnectorStatus = ConnectorStatus.provisioning
    last_health_check: Optional[str] = None
    configuration: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    revoked_at: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CredentialRef(BaseModel):
    """Credential metadata only — the secret itself lives in CredentialStore."""
    id: str = Field(default_factory=lambda: ids.new_id("cred"))
    provider: str = "encrypted_file"
    scopes: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
    rotated_at: Optional[str] = None
    last_used_at: Optional[str] = None
    expires_at: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConnectorCheckpoint(BaseModel):
    """Per-stream cursor. Advances only inside a committed batch transaction,
    guarded by compare-and-set on ``version`` so a stale worker can never
    regress a newer checkpoint."""
    id: str = Field(default_factory=lambda: ids.new_id("ckpt"))
    connector_id: str
    stream: str
    cursor_type: str = "revision_index"
    cursor: dict[str, Any] = Field(default_factory=dict)
    watermark: Optional[str] = None
    lookback_seconds: int = Field(default=0, ge=0)
    adapter_version: str = "1.0"
    committed_batch_id: Optional[str] = None
    version: int = Field(default=0, ge=0)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class ConnectorBatch(BaseModel):
    id: str = Field(default_factory=lambda: ids.new_id("cbatch"))
    connector_id: str
    stream: str = ""
    status: BatchStatus = BatchStatus.planned
    started_at: str = Field(default_factory=now_iso)
    completed_at: Optional[str] = None
    cursor_before: dict[str, Any] = Field(default_factory=dict)
    cursor_after_proposed: dict[str, Any] = Field(default_factory=dict)
    raw_count: int = Field(default=0, ge=0)
    normalized_count: int = Field(default=0, ge=0)
    deduplicated_count: int = Field(default=0, ge=0)
    quarantined_count: int = Field(default=0, ge=0)
    percept_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    failure_class: Optional[FailureClass] = None
    error: Optional[str] = None            # sanitized — never raw content
    metadata: dict[str, Any] = Field(default_factory=dict)


class RawConnectorItem(BaseModel):
    """Untrusted raw signal. Not Memory, not retrievable; passes quarantine.

    Raw items are *source cache*: they may persist even when the batch fails
    partially (the DLQ needs them for replay), because they never become
    cognitively visible — only Records/Percepts do, and those only land in a
    fully committed batch."""
    id: str = Field(default_factory=lambda: ids.new_id("rawitem"))
    connector_id: str
    source_account_id: str
    external_type: str
    external_id: str
    external_revision: str = "0"
    idempotency_key: str = ""
    content_type: str = "application/json"
    content_hash: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)  # decoded; stored encrypted
    deleted: bool = False
    fetched_at: str = Field(default_factory=now_iso)
    retention_class: str = "source_cache"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConnectorRecord(BaseModel):
    """Normalized envelope (future-compatible with a Universal Event bus).

    The persisted payload of a record is IMMUTABLE per observed revision:
    identity, content, hash, ownership and confidentiality are written once.
    Processing state (``percept_id``, ``quarantined``) lives in dedicated
    store columns and never rewrites the canonical payload."""
    id: str = Field(default_factory=lambda: ids.new_id("nsi"))
    connector_id: str
    source_account_id: str
    external_type: str
    external_id: str
    external_revision: str = "0"
    idempotency_key: str = ""
    occurred_at: Optional[str] = None
    observed_at: str = Field(default_factory=now_iso)
    actor_ids: list[str] = Field(default_factory=list)
    participant_ids: list[str] = Field(default_factory=list)
    project_hint: Optional[str] = None
    thread_key: Optional[str] = None
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list)
    content: str = ""                          # normalized text; stored encrypted
    content_hash: str = ""
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    ownership: dict[str, Any] = Field(default_factory=dict)
    confidentiality: dict[str, Any] = Field(default_factory=dict)
    # -- processing state (store columns, not part of the immutable payload)
    percept_id: Optional[str] = None
    quarantined: bool = False
    deleted: bool = False
    created_at: str = Field(default_factory=now_iso)


class ConnectorDeletionEvent(BaseModel):
    """A provider tombstone, resolved against prior lineage.

    Created when a source object is deleted upstream: it links every prior
    revision and the Percepts derived from them, and hands the decision to
    the deletion planner / review — the framework never cascades deletes on
    its own, and corroborated memories are never dropped automatically."""
    id: str = Field(default_factory=lambda: ids.new_id("cdel"))
    connector_id: str
    source_account_id: str
    external_type: str
    external_id: str
    tombstone_revision: str = "0"
    prior_record_ids: list[str] = Field(default_factory=list)
    affected_percept_ids: list[str] = Field(default_factory=list)
    vault_id: Optional[str] = None
    status: DeletionEventStatus = DeletionEventStatus.pending
    created_at: str = Field(default_factory=now_iso)
    resolved_at: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class StreamLease(BaseModel):
    """Mutual exclusion per (connector, stream): two workers never sync the
    same stream concurrently. Leases expire so a crashed worker cannot wedge
    the stream forever."""
    connector_id: str
    stream: str
    lease_owner: str
    lease_expires_at: str
    version: int = Field(default=1, ge=1)


class ConnectorDeadLetter(BaseModel):
    id: str = Field(default_factory=lambda: ids.new_id("dlq"))
    connector_id: str
    stream: str = ""
    external_id: str = ""
    external_type: str = ""
    failure_class: FailureClass = FailureClass.normalization
    attempts: int = Field(default=1, ge=0)
    last_error: str = ""                  # sanitized — never raw content/secrets
    raw_item_id: Optional[str] = None
    status: DeadLetterStatus = DeadLetterStatus.open
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConnectorSyncState(BaseModel):
    """Scheduler bookkeeping + last known health snapshot.

    ``version`` is a compare-and-set token so concurrent webhook hints and
    scheduler consumption never silently overwrite each other.

    Cumulative counters (``*_total``) are durable and monotonic — bumped when
    a batch reaches a terminal status. They must never be reconstructed from a
    sliding window of recent batches.
    """
    id: str                                    # == connector_id
    status: HealthStatus = HealthStatus.unknown
    interval_seconds: int = Field(default=300, ge=1)
    next_run_at: Optional[str] = None
    last_success_at: Optional[str] = None
    last_failure_at: Optional[str] = None
    last_checkpoint_at: Optional[str] = None
    retry_count: int = Field(default=0, ge=0)
    backoff_seconds: int = Field(default=0, ge=0)
    paused: bool = False
    # schedule lag only (max(0, now - next_run_at)); not checkpoint age
    lag_seconds: int = Field(default=0, ge=0)
    pending_items: int = Field(default=0, ge=0)
    dead_letters: int = Field(default=0, ge=0)
    # durable counters — never decrease
    fetch_total: int = Field(default=0, ge=0)
    failed_batches_total: int = Field(default=0, ge=0)
    normalized_total: int = Field(default=0, ge=0)
    deduplicated_total: int = Field(default=0, ge=0)
    quarantined_total: int = Field(default=0, ge=0)
    percepts_total: int = Field(default=0, ge=0)
    rate_limit_wait_total: int = Field(default=0, ge=0)
    deletion_events_total: int = Field(default=0, ge=0)
    counters_initialized: bool = False
    version: int = Field(default=0, ge=0)
    updated_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BackfillJobStatus(str, Enum):
    planned = "planned"
    running = "running"
    paused = "paused"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class BackfillJob(BaseModel):
    """Partitionable historical backfill  — separate from continuous sync.

    Progress.partitions is a list of year-month windows. Completing a partition
    is durable; the job can pause and resume without redoing finished months.
    ``version`` is a CAS fencing counter for partition claims.
    """
    id: str = Field(default_factory=lambda: ids.new_id("backfill"))
    connector_id: str
    status: BackfillJobStatus = BackfillJobStatus.planned
    range_start: Optional[str] = None
    range_end: Optional[str] = None
    partition_strategy: str = "year_month"
    streams: list[str] = Field(default_factory=list)
    progress: dict[str, Any] = Field(default_factory=dict)
    estimated_items: Optional[int] = None
    last_error: Optional[str] = None          # sanitized
    version: int = Field(default=0, ge=0)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    completed_at: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass
class SyncExecutionContext:
    """Per-invocation sync parameters that must NOT mutate connector config.

    Backfill bounds, job identity and attachment mode travel here so a job
    cannot race the scheduler by rewriting ``ConnectorInstance.configuration``.
    """
    mode: str = "continuous"  # continuous | backfill
    job_id: Optional[str] = None
    partition_key: Optional[str] = None
    range_start: Optional[str] = None
    range_end: Optional[str] = None
    attachment_mode: Optional[str] = None  # metadata_only | discovery
    claim_token: Optional[int] = None
    worker_id: Optional[str] = None
