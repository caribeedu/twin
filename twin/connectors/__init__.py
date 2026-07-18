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
    CredentialLockTimeout,
    CredentialStore,
    CredentialStoreCorrupted,
    build_credential_store,
    generate_token,
)
from .errors import sanitize_error
from .health import connector_health, snapshot_health
from .models import (
    BackfillJob,
    BackfillJobStatus,
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
    SyncExecutionContext,
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
from .runtime import (
    BackfillClaimLost,
    CheckpointConflict,
    LeaseLost,
    SyncResult,
    build_percept,
    run_sync,
)
from .service import (
    add_connector_instance,
    backfill_preview,
    create_backfill_job,
    discard_dead_letter,
    pause_connector,
    reclassify_source_account,
    register_source_account,
    resolve_dead_letter,
    resume_connector,
    retry_dead_letter,
    revoke_connector,
    run_backfill_partition,
    set_credential,
    sync_connector,
    sync_fingerprint,
    validate_connector,
)
# Import adapters for their registration side effects.
from . import fake  # noqa: E402,F401
from . import github  # noqa: E402,F401
from . import slack  # noqa: E402,F401
from . import gmail  # noqa: E402,F401
from . import outlook  # noqa: E402,F401
from . import calendar  # noqa: E402,F401
from . import fireflies  # noqa: E402,F401
from . import folder  # noqa: E402,F401


__all__ = [
    "AdapterManifest",
    "BackfillJob",
    "BackfillJobStatus",
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
    "SyncExecutionContext",
    "SyncMode",
    "SyncPlan",
    "SyncResult",
    "BackfillClaimLost",
    "CheckpointConflict",
    "ConnectorDeletionEvent",
    "CredentialBackendUnavailable",
    "CredentialLockTimeout",
    "CredentialStoreCorrupted",
    "LeaseLost",
    "StreamLease",
    "add_connector_instance",
    "authorize_connector",
    "backfill_preview",
    "build_adapter",
    "build_credential_store",
    "build_percept",
    "connector_health",
    "create_backfill_job",
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
    "run_backfill_partition",
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
