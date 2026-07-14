"""High-level connector operations shared by CLI, API and MCP.

Registration enforces explicit ownership + vault at configure time; credentials
are stored only via the CredentialStore; sync builds the adapter from the
registry and delegates to the runtime.
"""

from __future__ import annotations

from typing import Any, Optional

from ..clock import now_iso
from .credentials import CredentialStore, generate_token
from .models import (
    ConnectorInstance,
    ConnectorStatus,
    CredentialRef,
    HealthStatus,
    OwnershipClass,
    SourceAccount,
    SyncMode,
)
from .ownership import (
    default_vault_for,
    ensure_vault_for_account,
    validate_account_vault,
)
from .registry import build_adapter, get_manifest
from .runtime import SyncResult, run_sync


def register_source_account(
    store,
    *,
    connector_type: str,
    source_owner: str,
    vault_id: Optional[str] = None,
    org_key: Optional[str] = None,
    owner_principal_id: str = "principal_local_cli",
    persona: str = "individual",
    default_domain: str = "work",
    confidentiality: str = "internal",
    source_scope: str = "work",
    source_trust: float = 0.8,
    sync_mode: str = SyncMode.manual.value,
    external_account_id: str = "",
    display_name: str = "",
    metadata: Optional[dict[str, Any]] = None,
) -> SourceAccount:
    """Create an account with declared ownership. Fails closed on bad ownership."""
    if vault_id is None:
        vault_id = default_vault_for(source_owner, org_key)
    validate_account_vault(source_owner, vault_id)
    ensure_vault_for_account(store, source_owner, vault_id, org_key)

    account = SourceAccount(
        connector_type=connector_type,
        external_account_id=external_account_id,
        display_name=display_name or external_account_id or connector_type,
        owner_principal_id=owner_principal_id,
        source_owner=source_owner,
        org_key=org_key,
        persona=persona,
        vault_id=vault_id,
        default_domain=default_domain,
        confidentiality=confidentiality,
        source_scope=source_scope,
        source_trust=source_trust,
        sync_mode=sync_mode,
        metadata=metadata or {},
    )
    store.insert_source_account(account)
    return account


def set_credential(
    store,
    credentials: CredentialStore,
    connector_id: str,
    secret: Optional[str] = None,
    *,
    scopes: Optional[list[str]] = None,
    expires_at: Optional[str] = None,
) -> str:
    """Store a secret via the CredentialStore; DB keeps only the ref + metadata."""
    instance = store.get_connector_instance(connector_id)
    if instance is None:
        raise ValueError(f"connector {connector_id} not found")
    ref = CredentialRef(
        provider=getattr(credentials, "provider", "encrypted_file"),
        scopes=scopes or get_manifest(instance.connector_type).default_scopes,
        expires_at=expires_at,
    )
    store.insert_credential_ref(ref)
    credentials.put(ref.id, secret or generate_token())
    store.update_connector_instance(
        connector_id, credential_ref=ref.id,
        status=ConnectorStatus.active.value,
    )
    return ref.id


def add_connector_instance(
    store,
    credentials: CredentialStore,
    *,
    account_id: str,
    secret: Optional[str] = None,
    scopes: Optional[list[str]] = None,
    configuration: Optional[dict[str, Any]] = None,
    adapter_version: str = "1.0",
) -> ConnectorInstance:
    account = store.get_source_account(account_id)
    if account is None:
        raise ValueError(f"source account {account_id} not found")
    instance = ConnectorInstance(
        connector_type=account.connector_type,
        account_id=account_id,
        adapter_version=adapter_version,
        configuration=configuration or {},
    )
    store.insert_connector_instance(instance)
    set_credential(store, credentials, instance.id, secret, scopes=scopes)
    return store.get_connector_instance(instance.id)  # reload with credential_ref


def _load_adapter(store, credentials: CredentialStore, connector_id: str):
    instance = store.get_connector_instance(connector_id)
    if instance is None:
        raise ValueError(f"connector {connector_id} not found")
    account = store.get_source_account(instance.account_id)
    if account is None:
        raise ValueError(f"account {instance.account_id} not found")
    secret = (
        credentials.get(instance.credential_ref) if instance.credential_ref else None
    )
    return build_adapter(instance, account, secret), instance, account


def validate_connector(store, credentials: CredentialStore, connector_id: str):
    adapter, instance, _ = _load_adapter(store, credentials, connector_id)
    health = adapter.validate_credentials()
    store.update_connector_instance(connector_id, last_health_check=now_iso())
    if instance.credential_ref:
        store.update_credential_ref(instance.credential_ref, last_used_at=now_iso())
    return health


def sync_connector(
    store,
    credentials: CredentialStore,
    connector_id: str,
    *,
    streams: Optional[list[str]] = None,
    emit_percepts: bool = True,
) -> SyncResult:
    adapter, instance, account = _load_adapter(store, credentials, connector_id)
    return run_sync(
        store, adapter, instance, account,
        streams=streams, emit_percepts=emit_percepts,
    )


def pause_connector(store, connector_id: str) -> ConnectorInstance:
    return store.update_connector_instance(
        connector_id, status=ConnectorStatus.paused.value
    )


def resume_connector(store, connector_id: str) -> ConnectorInstance:
    return store.update_connector_instance(
        connector_id, status=ConnectorStatus.active.value
    )


def revoke_connector(
    store, credentials: CredentialStore, connector_id: str,
) -> ConnectorInstance:
    """Remove secret material and stop the connector permanently."""
    instance = store.get_connector_instance(connector_id)
    if instance is None:
        raise ValueError(f"connector {connector_id} not found")
    if instance.credential_ref:
        credentials.delete(instance.credential_ref)
        store.delete_credential_ref(instance.credential_ref)
    updated = store.update_connector_instance(
        connector_id,
        status=ConnectorStatus.revoked.value,
        credential_ref=None,
        revoked_at=now_iso(),
    )
    state = store.get_connector_sync_state(connector_id)
    if state is None:
        from .models import ConnectorSyncState
        state = ConnectorSyncState(id=connector_id)
    state.paused = True
    state.status = HealthStatus.revoked.value
    store.upsert_connector_sync_state(state)
    return updated
