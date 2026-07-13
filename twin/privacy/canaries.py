"""Leakage canaries — synthetic tokens that must never appear unauthorized."""

from __future__ import annotations

import secrets
from typing import Optional

from .. import ids
from ..clock import now_iso
from ..memory.store.base import MemoryStore
from .models import LeakageCanary


def place_canary(
    store: MemoryStore,
    *,
    vault_id: str = "vault_general",
    placed_in: Optional[list[str]] = None,
) -> LeakageCanary:
    token = f"CANARY-TWIN-{vault_id.upper().replace('VAULT_', '')}-{secrets.token_hex(3).upper()}"
    canary = LeakageCanary(
        id=ids.new_id("canary"),
        token=token,
        vault_id=vault_id,
        placed_in=placed_in or ["memory"],
        created_at=now_iso(),
        active=True,
    )
    store.insert_leakage_canary(canary)
    return canary


def active_canary_tokens(store: MemoryStore) -> list[str]:
    if not hasattr(store, "list_leakage_canaries"):
        return []
    return [c.token for c in store.list_leakage_canaries(active=True)]


def scan_for_canaries(store: MemoryStore, text: str) -> list[str]:
    """Return canary tokens found in text (leakage)."""
    found = []
    for token in active_canary_tokens(store):
        if token in (text or ""):
            found.append(token)
    return found
