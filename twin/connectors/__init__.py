"""v0.6 — Professional Connectors and Continuous Work Perception.

Framework only (Phase 1): contracts, persistence, credentials, checkpoints,
batches, scheduler, health/DLQ, ownership-aware vaults and a FakeConnector.
Connectors capture evidence; cognition creates understanding.
"""

from __future__ import annotations

from .credentials import CredentialStore, build_credential_store, generate_token
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
from .runtime import SyncResult, build_percept, run_sync
from .service import (
    add_connector_instance,
    pause_connector,
    register_source_account,
    resume_connector,
    revoke_connector,
    set_credential,
    sync_connector,
    validate_connector,
)

# Import adapters for their registration side effects.
from . import fake  # noqa: E402,F401

__all__ = [
    "AdapterManifest",
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
    "add_connector_instance",
    "build_adapter",
    "build_credential_store",
    "build_percept",
    "connector_health",
    "default_vault_for",
    "ensure_org_vault",
    "generate_token",
    "get_adapter_class",
    "get_manifest",
    "idempotency_key",
    "list_adapters",
    "pause_connector",
    "register_adapter",
    "register_source_account",
    "resume_connector",
    "revoke_connector",
    "run_sync",
    "set_credential",
    "snapshot_health",
    "sync_connector",
    "validate_account_vault",
    "validate_connector",
]
