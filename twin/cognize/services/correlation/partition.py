"""Vault / ownership partition helpers for correlation."""

from __future__ import annotations

from typing import Any, Optional


def vault_for_account(account: Any) -> str:
    if account is None:
        return "vault_unknown"
    return str(getattr(account, "vault_id", None) or "vault_unknown")


def vault_for_record(store, record: Any) -> str:
    """Resolve the vault partition for a connector record.

    Prefer sealed ownership on the record, then the SourceAccount vault.
    """
    ownership = getattr(record, "ownership", None) or {}
    if isinstance(ownership, dict) and ownership.get("vault_id"):
        return str(ownership["vault_id"])
    conf = getattr(record, "confidentiality", None) or {}
    if isinstance(conf, dict) and conf.get("vault_id"):
        return str(conf["vault_id"])
    account_id = getattr(record, "source_account_id", None)
    if account_id and hasattr(store, "get_source_account"):
        acc = store.get_source_account(account_id)
        if acc is not None:
            return vault_for_account(acc)
    return "vault_unknown"


def account_meta(store, record: Any) -> dict[str, str]:
    """Return vault_id / source_owner / org_key for a record."""
    vault = vault_for_record(store, record)
    owner = ""
    org = ""
    ownership = getattr(record, "ownership", None) or {}
    if isinstance(ownership, dict):
        owner = str(ownership.get("source_owner") or "")
        org = str(ownership.get("org_key") or "")
    account_id = getattr(record, "source_account_id", None)
    if account_id and hasattr(store, "get_source_account"):
        acc = store.get_source_account(account_id)
        if acc is not None:
            if not owner:
                so = getattr(acc, "source_owner", None)
                owner = getattr(so, "value", so) or ""
            if not org:
                org = str(getattr(acc, "org_key", None) or "")
            if vault == "vault_unknown":
                vault = vault_for_account(acc)
    return {"vault_id": vault, "source_owner": str(owner), "org_key": str(org)}


def qualify_anchor(
    vault_id: str,
    anchor_type: str,
    value: str,
    *,
    provider: str = "",
    source_account_id: str = "",
) -> str:
    """Vault-qualified anchor string used for clustering and episode keys."""
    parts = [vault_id or "vault_unknown", anchor_type]
    if provider:
        parts.append(provider)
    if source_account_id:
        parts.append(source_account_id)
    parts.append(str(value))
    return ":".join(parts)


def partition_records(
    store, records: list[Any],
) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for rec in records:
        vault = vault_for_record(store, rec)
        out.setdefault(vault, []).append(rec)
    return out
