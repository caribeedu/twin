"""Active vault resolution.

Connectors stamp real vault ids (``vault_personal``, ``vault_work_{org}``, …).
The literal string ``"default"`` is not a vault — treat it as unset.
"""

from __future__ import annotations

import os
from typing import Any, Optional

# Read/list fallback when nothing is configured and the store has no vaults yet.
FALLBACK_VAULT = "vault_general"

# Built-in vault ids → UI / catalog labels (ids stay machine-stable).
FACTORY_VAULT_LABELS: dict[str, str] = {
    "vault_general": "General",
    "vault_personal": "Personal",
    "vault_work": "Work",
    "vault_restricted": "Restricted",
    "vault_open_source": "Open source",
}


def _clean(value: Optional[str]) -> str:
    raw = str(value or "").strip()
    if not raw or raw == "default":
        return ""
    return raw


def vault_display_name(vault_id: str, name: Optional[str] = None) -> str:
    """Human label for a vault. Custom ``name`` wins when it differs from the id."""
    vid = _clean(vault_id) or FALLBACK_VAULT
    raw = (name or "").strip()
    if raw and raw != vid:
        return raw
    if vid in FACTORY_VAULT_LABELS:
        return FACTORY_VAULT_LABELS[vid]
    if vid.startswith("vault_work_"):
        org = vid[len("vault_work_"):].replace("_", " ").strip()
        return f"Work — {org}" if org else FACTORY_VAULT_LABELS["vault_work"]
    return raw or vid


def iter_vault_ids(store: Any) -> list[str]:
    """Known vault ids from the store catalog (sorted, stable)."""
    if store is None or not hasattr(store, "list_vaults"):
        return []
    try:
        rows = store.list_vaults() or []
    except Exception:
        return []
    ids = sorted({str(getattr(v, "id", "") or "").strip() for v in rows if getattr(v, "id", None)})
    return [vid for vid in ids if vid]


def storage_vault(explicit: Optional[str] = None) -> str:
    """Partition key for a stamped value — never invent personal/work from catalog.

    Empty / ``default`` → ``FALLBACK_VAULT``. Real ids pass through unchanged.
    """
    return _clean(explicit) or FALLBACK_VAULT


def vault_read_ids(stored: Optional[str] = None) -> list[str]:
    """Store partition keys to read for a stamped (or unset) vault.

    Legacy rows used the literal ``default`` key; new rows use ``vault_general``.
    Treat those as one partition when reading. Other vault ids stay exact.
    """
    raw = str(stored or "").strip()
    if not raw or raw == "default" or raw == FALLBACK_VAULT:
        return [FALLBACK_VAULT, "default"]
    return [raw]


def resolve_vault(
    explicit: Optional[str] = None,
    *,
    cfg: Any = None,
    store: Any = None,
) -> str:
    """Pick the active vault.

    Order: explicit arg → ``Config.vault`` / ``TWIN_VAULT`` → sole store vault →
    ``vault_general`` / ``vault_personal`` if present → first catalog id →
    ``FALLBACK_VAULT``.
    """
    for candidate in (
        _clean(explicit),
        _clean(getattr(cfg, "vault", None) if cfg is not None else None),
        _clean(os.environ.get("TWIN_VAULT", "")),
    ):
        if candidate:
            return candidate

    ids = iter_vault_ids(store)
    if len(ids) == 1:
        return ids[0]
    for preferred in ("vault_general", "vault_personal"):
        if preferred in ids:
            return preferred
    if ids:
        return ids[0]
    return FALLBACK_VAULT


def set_active_vault(home: Any, vault_id: str) -> str:
    """Persist ``TWIN_VAULT`` into ``{home}/env`` and the process environment."""
    vid = _clean(vault_id)
    if not vid:
        raise ValueError("vault_id is required")
    from pathlib import Path

    from twin.interfaces.ux import write_env_file

    home_path = Path(home)
    write_env_file(home_path / "env", {"TWIN_VAULT": vid})
    os.environ["TWIN_VAULT"] = vid
    return vid
