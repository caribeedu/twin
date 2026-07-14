"""v0.6 connector framework — persisted entities and enums.

Connectors capture evidence; the cognitive core creates understanding. These
models describe *accounts*, *instances*, *sync bookkeeping* and the normalized
``ConnectorRecord`` envelope — never confirmed Memory or Judgment.
"""

from __future__ import annotations

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
    active = "active"
    paused = "paused"
    revoked = "revoked"
    unauthorized = "unauthorized"
    degraded = "degraded"
    failed = "failed"


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


class HealthStatus(str, Enum):
    healthy = "healthy"
    degraded = "degraded"
    paused = "paused"
    unauthorized = "unauthorized"
    revoked = "revoked"
    failed = "failed"


class DeadLetterStatus(str, Enum):
    open = "open"
    retrying = "retrying"
    resolved = "resolved"
    discarded = "discarded"


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
    """One external account. A person may own many across providers."""
    id: str = Field(default_factory=lambda: ids.new_id("srcacct"))
    connector_type: str
    external_account_id: str = ""
    display_name: str = ""
    owner_principal_id: str = "principal_local_cli"
    source_owner: str = OwnershipClass.unknown.value
    org_key: Optional[str] = None            # e.g. "shippo" → vault_work_shippo
    persona: str = "individual"
    vault_id: str = "vault_general"
    default_domain: str = "work"
    confidentiality: str = "internal"        # public|internal|private|restricted
    source_scope: str = "work"
    source_trust: float = 0.8
    enabled: bool = True
    sync_mode: str = SyncMode.manual.value
    created_at: str = Field(default_factory=now_iso)
    revoked_at: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConnectorInstance(BaseModel):
    """A concrete install of a connector type against one account."""
    id: str = Field(default_factory=lambda: ids.new_id("conn"))
    connector_type: str
    account_id: str
    adapter_version: str = "1.0"
    schema_version: int = 1
    credential_ref: Optional[str] = None
    status: str = ConnectorStatus.active.value
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
    """Per-stream cursor. Advances only after a batch commits."""
    id: str = Field(default_factory=lambda: ids.new_id("ckpt"))
    connector_id: str
    stream: str
    cursor_type: str = "revision_index"
    cursor: dict[str, Any] = Field(default_factory=dict)
    watermark: Optional[str] = None
    lookback_seconds: int = 0
    adapter_version: str = "1.0"
    committed_batch_id: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class ConnectorBatch(BaseModel):
    id: str = Field(default_factory=lambda: ids.new_id("cbatch"))
    connector_id: str
    stream: str = ""
    status: str = BatchStatus.planned.value
    started_at: str = Field(default_factory=now_iso)
    completed_at: Optional[str] = None
    cursor_before: dict[str, Any] = Field(default_factory=dict)
    cursor_after_proposed: dict[str, Any] = Field(default_factory=dict)
    raw_count: int = 0
    normalized_count: int = 0
    deduplicated_count: int = 0
    quarantined_count: int = 0
    percept_count: int = 0
    failed_count: int = 0
    failure_class: Optional[str] = None
    error: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RawConnectorItem(BaseModel):
    """Untrusted raw signal. Not Memory, not retrievable; passes quarantine."""
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
    """Normalized envelope (future-compatible with a Universal Event bus)."""
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
    percept_id: Optional[str] = None
    quarantined: bool = False
    deleted: bool = False
    created_at: str = Field(default_factory=now_iso)


class ConnectorDeadLetter(BaseModel):
    id: str = Field(default_factory=lambda: ids.new_id("dlq"))
    connector_id: str
    stream: str = ""
    external_id: str = ""
    external_type: str = ""
    failure_class: str = FailureClass.normalization.value
    attempts: int = 1
    last_error: str = ""
    raw_item_id: Optional[str] = None
    status: str = DeadLetterStatus.open.value
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConnectorSyncState(BaseModel):
    """Scheduler bookkeeping + last known health snapshot."""
    id: str                                    # == connector_id
    status: str = HealthStatus.healthy.value
    interval_seconds: int = 300
    next_run_at: Optional[str] = None
    last_success_at: Optional[str] = None
    last_failure_at: Optional[str] = None
    last_checkpoint_at: Optional[str] = None
    retry_count: int = 0
    backoff_seconds: int = 0
    paused: bool = False
    lag_seconds: int = 0
    pending_items: int = 0
    dead_letters: int = 0
    updated_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)
