"""Ownership classification and organization vaults.

Ownership is declared, never inferred from an email domain. Employer/client
data lands in a dedicated ``vault_work_{org}`` and may never default to the
personal or general vault.
"""

from __future__ import annotations

from typing import Optional

from ..privacy.models import Vault
from .models import OwnershipClass

OWNERSHIP_CLASSES = frozenset(o.value for o in OwnershipClass)

# Owners whose data must be physically/logically separated from personal life.
_ORG_OWNERS = {OwnershipClass.employer.value, OwnershipClass.client.value}

# Vaults an org account may never use as its default.
_FORBIDDEN_ORG_VAULTS = {"vault_personal", "vault_general"}


def normalize_org_key(org_key: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in (org_key or "")).strip("_")


def org_vault_id(org_key: str) -> str:
    return f"vault_work_{normalize_org_key(org_key)}"


def default_vault_for(source_owner: str, org_key: Optional[str] = None) -> str:
    """Recommended default vault for an ownership class."""
    if source_owner in _ORG_OWNERS:
        if not org_key:
            raise ValueError(f"{source_owner} account requires an org_key")
        return org_vault_id(org_key)
    if source_owner == OwnershipClass.personal.value:
        return "vault_personal"
    if source_owner == OwnershipClass.opensource.value:
        return "vault_open_source"
    if source_owner == OwnershipClass.shared.value:
        return "vault_general"
    return "vault_restricted"  # unknown → most restrictive


def validate_account_vault(source_owner: str, vault_id: str) -> None:
    """Hard check at configure time. Fail closed on mismatched ownership."""
    if source_owner not in OWNERSHIP_CLASSES:
        raise ValueError(
            f"unknown source_owner {source_owner!r}; expected one of "
            f"{sorted(OWNERSHIP_CLASSES)}"
        )
    if source_owner in _ORG_OWNERS and vault_id in _FORBIDDEN_ORG_VAULTS:
        raise ValueError(
            f"{source_owner} account may not target {vault_id}; "
            "use a dedicated vault_work_{org}"
        )


def ensure_org_vault(
    store,
    org_key: str,
    *,
    source_owner: str = OwnershipClass.employer.value,
    personas: Optional[list[str]] = None,
) -> Vault:
    """Create (or return) the isolated work vault for an organization."""
    vault_id = org_vault_id(org_key)
    existing = store.get_vault(vault_id)
    if existing is not None:
        return existing
    vault = Vault(
        id=vault_id,
        name=f"Work — {org_key}",
        encryption_key_id=f"key_{normalize_org_key(org_key)}",
        storage_backend="shared_db",
        physical_boundary="shared_db",
        storage_namespace=f"ns_work_{normalize_org_key(org_key)}",
        backup_class="employer",
        source_owner=source_owner,
        allowed_personas=personas or ["professional", "individual"],
    )
    store.insert_vault(vault)
    return vault


def ensure_vault_for_account(store, source_owner: str, vault_id: str,
                             org_key: Optional[str] = None) -> None:
    """Guarantee the target vault exists before an account is bound to it."""
    if source_owner in _ORG_OWNERS and org_key:
        ensure_org_vault(store, org_key, source_owner=source_owner)
        return
    if store.get_vault(vault_id) is None:
        store.insert_vault(Vault(id=vault_id, name=vault_id, source_owner=source_owner))
