"""v0.6 — Professional Connectors and Continuous Work Perception.

Framework only (Phase 1): contracts, persistence, credentials, checkpoints,
batches, scheduler, health/DLQ, ownership-aware vaults and a FakeConnector.
Connectors capture evidence; cognition creates understanding.
"""

from __future__ import annotations

from .authz import (
    CAP_BACKFILL,
    CAP_CONFIGURE,
    CAP_CREDENTIALS,
    CAP_OPERATE,
    CAP_READ,
    CAP_READ_ERRORS,
    CAP_REVOKE,
    CAP_SYNC,
    authorize_connector,
    visible_connectors,
)
from .credentials import (
    CredentialBackendUnavailable,
    CredentialStore,
    CredentialStoreCorrupted,
    build_credential_store,
    generate_token,
)
from .errors import sanitize_error
from .health import connector_health, snapshot_health
from .models import (
    ConnectorBatch,
    ConnectorCheckpoint,
    ConnectorDeadLetter,
    ConnectorInstance,
    ConnectorRecord,
    ConnectorStatus,
    ConnectorSyncState,
    CredentialRef,
    HealthStatus,
    OwnershipClass,
    RawConnectorItem,
    SourceAccount,
    SyncMode,
    idempotency_key,
)
from .ownership import default_vault_for, ensure_org_vault, validate_account_vault
from .protocol import (
    AdapterManifest,
    ConnectorError,
    ConnectorHealth,
    FetchPage,
    ProfessionalConnector,
    RawFetchItem,
    SyncPlan,
)
from .registry import (
    build_adapter,
    get_adapter_class,
    get_manifest,
    list_adapters,
    register_adapter,
)
from .models import ConnectorDeletionEvent, StreamLease  # noqa: F401
from .runtime import CheckpointConflict, LeaseLost, SyncResult, build_percept, run_sync
from .service import (
    add_connector_instance,
    discard_dead_letter,
    pause_connector,
    reclassify_source_account,
    register_source_account,
    resolve_dead_letter,
    resume_connector,
    retry_dead_letter,
    revoke_connector,
    set_credential,
    sync_connector,
    sync_fingerprint,
    validate_connector,
)

# Import adapters for their registration side effects.
from . import fake  # noqa: E402,F401

__all__ = [
    "AdapterManifest",
    "CAP_BACKFILL",
    "CAP_CONFIGURE",
    "CAP_CREDENTIALS",
    "CAP_OPERATE",
    "CAP_READ",
    "CAP_READ_ERRORS",
    "CAP_REVOKE",
    "CAP_SYNC",
    "ConnectorBatch",
    "ConnectorCheckpoint",
    "ConnectorDeadLetter",
    "ConnectorError",
    "ConnectorHealth",
    "ConnectorInstance",
    "ConnectorRecord",
    "ConnectorStatus",
    "ConnectorSyncState",
    "CredentialRef",
    "CredentialStore",
    "FetchPage",
    "HealthStatus",
    "OwnershipClass",
    "ProfessionalConnector",
    "RawConnectorItem",
    "RawFetchItem",
    "SourceAccount",
    "SyncMode",
    "SyncPlan",
    "SyncResult",
    "CheckpointConflict",
    "ConnectorDeletionEvent",
    "CredentialBackendUnavailable",
    "CredentialStoreCorrupted",
    "LeaseLost",
    "StreamLease",
    "add_connector_instance",
    "authorize_connector",
    "build_adapter",
    "build_credential_store",
    "build_percept",
    "connector_health",
    "default_vault_for",
    "discard_dead_letter",
    "ensure_org_vault",
    "generate_token",
    "get_adapter_class",
    "get_manifest",
    "idempotency_key",
    "list_adapters",
    "pause_connector",
    "reclassify_source_account",
    "register_adapter",
    "register_source_account",
    "resolve_dead_letter",
    "resume_connector",
    "retry_dead_letter",
    "revoke_connector",
    "run_sync",
    "sanitize_error",
    "set_credential",
    "snapshot_health",
    "sync_connector",
    "sync_fingerprint",
    "validate_account_vault",
    "validate_connector",
    "visible_connectors",
]
