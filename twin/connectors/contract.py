"""Shared §88 adapter contract matrix (v0.6 Phase 9).

Each registered adapter must declare a complete ``AdapterManifest`` and
implement the ``ProfessionalConnector`` surface. Runtime behaviour (idempotency,
partial batch, quarantine, …) is proven per-adapter in its own test module;
this helper only asserts the *shared declaration contract* so gaps stay visible.
"""

from __future__ import annotations

from typing import Any

from .protocol import AdapterManifest
from .registry import get_adapter_class, get_manifest, list_adapters

# Checklist items from the v0.6 §88 contract suite. Behavioural coverage is
# tracked per adapter; ``required`` means the matrix fails closed without it.
CONTRACT_ITEMS = (
    "manifest_complete",
    "auth_mode_declared",
    "streams_or_dynamic",
    "supported_external_types",
    "affordances_declared",
    "protocol_methods",
    "idempotent_ingest",          # proven in adapter/Fake tests
    "partial_batch_invisible",
    "revision_collision_dlq",
    "quarantine_no_percept",
    "source_deletion_event",
    "checkpoint_after_commit",
    "rate_limit_structured",
    "unauthorized_health",
    "unknown_schema_tolerated",   # GitHub + Fake; others may be partial
    "backfill_preview_safe",      # adapters that expose estimate_backfill
)

# Behavioural items already covered by the FakeConnector suite — every adapter
# inherits the framework path, so these are "framework-proven".
FRAMEWORK_PROVEN = frozenset({
    "idempotent_ingest",
    "partial_batch_invisible",
    "revision_collision_dlq",
    "quarantine_no_percept",
    "source_deletion_event",
    "checkpoint_after_commit",
    "rate_limit_structured",
    "unauthorized_health",
})

# Per-adapter notes for items that are adapter-specific or intentionally thin.
ADAPTER_NOTES: dict[str, dict[str, str]] = {
    "fake": {
        "unknown_schema_tolerated": "fixture-driven; extra fields ignored",
        "backfill_preview_safe": "estimate via fixture volume",
        "large_attachment": "not applicable (no binary fetch)",
    },
    "github": {
        "unknown_schema_tolerated": "covered in test_github_connector",
        "backfill_preview_safe": "estimate_backfill + CLI preview",
        "large_attachment": "deferred — REST polling is metadata-first",
    },
    "slack": {
        "unknown_schema_tolerated": "extra event fields ignored by normalizer",
        "backfill_preview_safe": "estimate_backfill + CLI preview",
        "large_attachment": "files metadata_only — bytes never fetched",
    },
    "gmail": {
        "backfill_preview_safe": "estimate_backfill + BackfillJob partitions",
        "large_attachment": "attachment_mode metadata_only|discovery",
    },
    "outlook": {
        "backfill_preview_safe": "estimate_backfill + BackfillJob partitions",
        "large_attachment": "attachment_mode metadata_only|discovery",
    },
    "calendar": {
        "backfill_preview_safe": "preview via calendars discovery",
        "large_attachment": "not applicable",
    },
    "fireflies": {
        "backfill_preview_safe": "preview via meetings list",
        "source_deletion_event": "provider has no deletion feed (deletions=false)",
    },
    "folder": {
        "auth_mode_declared": "auth_mode=none",
        "backfill_preview_safe": "roots discovery; full-scan sync",
        "rate_limit_structured": "local FS — no provider rate limit",
        "unauthorized_health": "unreadable roots → degraded/awaiting_configuration",
    },
}


_REQUIRED_PROTOCOL = (
    "adapter_manifest",
    "discover_accounts",
    "validate_credentials",
    "plan_sync",
    "fetch_batch",
    "normalize",
    "acknowledge",
)


def _manifest_gaps(manifest: AdapterManifest) -> list[str]:
    gaps: list[str] = []
    if not manifest.connector_type:
        gaps.append("connector_type empty")
    if not manifest.auth_mode:
        gaps.append("auth_mode missing")
    if not manifest.streams and not manifest.dynamic_streams:
        gaps.append("neither streams nor dynamic_streams")
    if not manifest.supported_external_types:
        gaps.append("supported_external_types empty")
    if not isinstance(manifest.affordances, dict):
        gaps.append("affordances not a dict")
    return gaps


def check_adapter_contract(connector_type: str) -> dict[str, Any]:
    """Return a §88 matrix row for one registered adapter."""
    cls = get_adapter_class(connector_type)
    manifest = get_manifest(connector_type)
    gaps = _manifest_gaps(manifest)
    methods_ok = all(callable(getattr(cls, name, None)) for name in _REQUIRED_PROTOCOL)
    # Protocol satisfaction (structural)
    protocol_ok = isinstance(cls, type)

    items: dict[str, str] = {}
    items["manifest_complete"] = "pass" if not gaps else f"fail:{','.join(gaps)}"
    items["auth_mode_declared"] = "pass" if manifest.auth_mode else "fail"
    items["streams_or_dynamic"] = (
        "pass" if (manifest.streams or manifest.dynamic_streams) else "fail"
    )
    items["supported_external_types"] = (
        "pass" if manifest.supported_external_types else "fail"
    )
    items["affordances_declared"] = (
        "pass" if isinstance(manifest.affordances, dict) else "fail"
    )
    items["protocol_methods"] = "pass" if methods_ok else "fail"
    for name in FRAMEWORK_PROVEN:
        items[name] = "framework"
    notes = ADAPTER_NOTES.get(connector_type, {})
    items["unknown_schema_tolerated"] = notes.get(
        "unknown_schema_tolerated", "partial — see adapter tests",
    )
    has_estimate = callable(getattr(cls, "estimate_backfill", None))
    items["backfill_preview_safe"] = (
        "pass" if has_estimate
        else notes.get("backfill_preview_safe", "preview via discovery helpers")
    )
    if "large_attachment" in notes:
        items["large_attachment"] = notes["large_attachment"]
    # Allow adapter notes to override framework-proven when provider differs
    for key, note in notes.items():
        if key in items and key in (
            "source_deletion_event", "rate_limit_structured", "unauthorized_health",
        ):
            items[key] = note

    failed = [k for k, v in items.items() if isinstance(v, str) and v.startswith("fail")]
    return {
        "connector_type": connector_type,
        "adapter_class": cls.__name__,
        "auth_mode": manifest.auth_mode,
        "dynamic_streams": bool(manifest.dynamic_streams),
        "streams": list(manifest.streams),
        "external_types": list(manifest.supported_external_types),
        "affordances": dict(manifest.affordances or {}),
        "protocol_ok": protocol_ok and methods_ok,
        "items": items,
        "gaps": gaps,
        "ok": not failed and not gaps,
    }


def contract_matrix() -> dict[str, Any]:
    """Full §88 matrix across every registered adapter."""
    rows = [check_adapter_contract(name) for name in list_adapters()]
    return {
        "contract": "v0.6 §88",
        "adapters": len(rows),
        "ok": all(r["ok"] for r in rows),
        "rows": rows,
        "checklist": list(CONTRACT_ITEMS),
    }
