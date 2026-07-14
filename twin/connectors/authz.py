"""Capability checks for connector surfaces (MCP / HTTP API).

Connector administration is its own authority, never implied by anything
else:

    read_context_pack  does NOT imply  connector:read
    connector:read     does NOT imply  connector:sync
    connector:sync on one vault does NOT imply another vault

Every check runs against the *resolved* access context (server-side identity,
principal ∩ binding) — client-asserted capability lists are never trusted.
Optional scoped capabilities restrict further:

    connector:id:<connector_id>
    connector:type:<connector_type>
    connector:vault:<vault_id>
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

CAP_READ = "connector:read"
CAP_READ_ERRORS = "connector:read:errors"
CAP_SYNC = "connector:sync"
CAP_BACKFILL = "connector:backfill"
CAP_CONFIGURE = "connector:configure"
CAP_CREDENTIALS = "connector:credentials"
CAP_OPERATE = "connector:operate"
CAP_REVOKE = "connector:revoke"
CAP_ADMIN = "connector:admin"

_ALL_CONNECTOR_CAPS = {
    CAP_READ, CAP_READ_ERRORS, CAP_SYNC, CAP_BACKFILL, CAP_CONFIGURE,
    CAP_CREDENTIALS, CAP_OPERATE, CAP_REVOKE,
}


@dataclass
class ConnectorAuth:
    allowed: bool
    reason: str = ""
    principal_id: str = "unknown"


def _effective_caps(access) -> set[str]:
    return set((access.metadata or {}).get("resolved_capabilities") or [])


def _scope_ok(caps: set[str], prefix: str, value: Optional[str]) -> bool:
    scoped = {c for c in caps if c.startswith(prefix + ":")}
    if not scoped:
        return True  # no scopes of this kind → not restricting
    if value is None:
        return False  # declared scopes never widen when context is missing
    return f"{prefix}:{value}" in scoped or f"{prefix}:*" in scoped


def authorize_connector(
    store,
    access,
    capability: str,
    *,
    connector_id: Optional[str] = None,
) -> ConnectorAuth:
    """Resolve whether this access context may perform ``capability`` on the
    given connector (or on the connector surface at all when no id applies)."""
    if access is None or getattr(access, "is_restricted_mode", True):
        return ConnectorAuth(False, "restricted_mode: connector operations "
                                    "require a registered, authenticated client")
    caps = _effective_caps(access)
    if "*" in caps or "privacy:admin" in caps:
        return ConnectorAuth(True, "admin", access.principal_id)

    has_cap = (
        capability in caps
        or (CAP_ADMIN in caps and capability in _ALL_CONNECTOR_CAPS)
        # connector:read:errors is a narrowing of read, so read covers it
        or (capability == CAP_READ_ERRORS and CAP_READ in caps)
    )
    if not has_cap:
        return ConnectorAuth(False, f"missing capability {capability}",
                             access.principal_id)

    if connector_id is not None:
        instance = store.get_connector_instance(connector_id)
        if instance is None:
            # authorization cannot leak existence — same denial either way
            return ConnectorAuth(False, "connector not found or not authorized",
                                 access.principal_id)
        account = store.get_source_account(instance.account_id)
        vault_id = account.vault_id if account else None
        if not _scope_ok(caps, "connector:id", connector_id):
            return ConnectorAuth(False, "connector id out of scope",
                                 access.principal_id)
        if not _scope_ok(caps, "connector:type", instance.connector_type):
            return ConnectorAuth(False, "connector type out of scope",
                                 access.principal_id)
        if not _scope_ok(caps, "connector:vault", vault_id):
            return ConnectorAuth(False, "connector vault out of scope",
                                 access.principal_id)
        # the principal must also be allowed into the account's vault at all
        allowed_vaults = (access.metadata or {}).get("allowed_vaults") or []
        if allowed_vaults and vault_id and vault_id not in allowed_vaults \
                and "*" not in allowed_vaults:
            return ConnectorAuth(False, f"vault {vault_id} not authorized "
                                        "for this principal",
                                 access.principal_id)
    return ConnectorAuth(True, "ok", access.principal_id)


def visible_connectors(store, access) -> list[Any]:
    """Connector instances this access context may see under CAP_READ,
    filtered by scoped capabilities and vault allowlists."""
    out = []
    for inst in store.list_connector_instances():
        if authorize_connector(store, access, CAP_READ, connector_id=inst.id).allowed:
            out.append(inst)
    return out
