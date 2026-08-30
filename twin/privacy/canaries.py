"""Leakage canaries — synthetic tokens that must never appear unauthorized."""

from __future__ import annotations

import secrets
from typing import Optional

from .. import ids
from ..clock import now_iso
from twin.store.store.base import TwinStore
from .models import LeakageCanary


def place_canary(
    store: TwinStore,
    *,
    vault_id: str = "vault_general",
    placed_in: Optional[list[str]] = None,
) -> LeakageCanary:
    token = f"CANARY-TWIN-{vault_id.upper().replace('VAULT_', '')}-{secrets.token_hex(3).upper()}"
    canary = LeakageCanary(
        id=ids.new_id("canary"),
        token=token,
        vault_id=vault_id,
        placed_in=placed_in or ["claim"],
        created_at=now_iso(),
        active=True,
    )
    store.insert_leakage_canary(canary)
    return canary


def active_canary_tokens(store: TwinStore) -> list[str]:
    if not hasattr(store, "list_leakage_canaries"):
        return []
    return [c.token for c in store.list_leakage_canaries(active=True)]


def scan_for_canaries(store: TwinStore, text: str) -> list[str]:
    """Return canary tokens found in text (leakage)."""
    found = []
    for token in active_canary_tokens(store):
        if token in (text or ""):
            found.append(token)
    return found
