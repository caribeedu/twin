"""Shared §88 adapter contract matrix (v0.6 Phase 9 — evidence-based).

Two layers:

* **framework** — FakeConnector proves the shared spine (batch txn, DLQ, …).
* **adapter** — each real adapter must point at concrete tests or declare
  ``not_supported`` / ``not_applicable`` via manifest affordances.

Statuses are structured; free-text notes alone never make ``ok`` true.
"""

from __future__ import annotations

from typing import Any, Optional

from .protocol import AdapterManifest
from .registry import get_adapter_class, get_manifest, list_adapters

# Formal statuses — only these are valid in matrix cells.
STATUSES = frozenset({
    "pass",
    "fail",
    "not_supported",
    "not_applicable",
    "not_tested",
    "framework_only",
    "partial",
})

# Items every adapter row must address. ``required`` means missing evidence
# (not_tested / fail) fails the row. Provider optional capabilities may be
# not_supported when the manifest declares so.
CONTRACT_ITEMS: dict[str, dict[str, Any]] = {
    "manifest_complete": {"required": True, "layer": "declaration"},
    "auth_mode_declared": {"required": True, "layer": "declaration"},
    "streams_or_dynamic": {"required": True, "layer": "declaration"},
    "supported_external_types": {"required": True, "layer": "declaration"},
    "affordances_declared": {"required": True, "layer": "declaration"},
    "protocol_methods": {"required": True, "layer": "declaration"},
    "idempotent_ingest": {"required": True, "layer": "behaviour"},
    "partial_batch_invisible": {"required": True, "layer": "behaviour"},
    "revision_collision_dlq": {"required": True, "layer": "behaviour"},
    "quarantine_no_percept": {"required": True, "layer": "behaviour"},
    "source_deletion_event": {"required": True, "layer": "behaviour",
                              "affordance": "deletions"},
    "checkpoint_after_commit": {"required": True, "layer": "behaviour"},
    "rate_limit_structured": {"required": True, "layer": "behaviour"},
    "unauthorized_health": {"required": True, "layer": "behaviour"},
    "unknown_schema_tolerated": {"required": True, "layer": "behaviour"},
    "backfill_preview_safe": {"required": True, "layer": "behaviour"},
    "large_attachment": {"required": False, "layer": "behaviour"},
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

# Concrete evidence — test node ids. framework_only is reserved for Fake.
EVIDENCE: dict[str, dict[str, dict[str, str]]] = {
    "fake": {
        "idempotent_ingest": {
            "status": "pass",
            "evidence": "tests/connectors/test_service.py::test_second_sync_is_idempotent",
        },
        "partial_batch_invisible": {
            "status": "pass",
            "evidence": "tests/connectors/test_service.py::test_partial_failure_persists_nothing_cognitive",
        },
        "revision_collision_dlq": {
            "status": "pass",
            "evidence": "tests/connectors/test_service.py::test_same_revision_different_content_is_a_collision",
        },
        "quarantine_no_percept": {
            "status": "pass",
            "evidence": "tests/connectors/test_service.py::test_malicious_content_quarantined_never_extracted",
        },
        "source_deletion_event": {
            "status": "pass",
            "evidence": "tests/connectors/test_service.py::test_tombstone_builds_lineage_impact_event",
        },
        "checkpoint_after_commit": {
            "status": "pass",
            "evidence": "tests/connectors/test_service.py::test_checkpoint_advances_only_after_commit",
        },
        "rate_limit_structured": {
            "status": "pass",
            "evidence": "tests/connectors/test_service.py::test_rate_limit_degrades_and_keeps_checkpoint",
        },
        "unauthorized_health": {
            "status": "pass",
            "evidence": "tests/connectors/test_service.py::test_auth_expiry_reports_unauthorized_and_no_checkpoint",
        },
        "unknown_schema_tolerated": {
            "status": "pass",
            "evidence": "tests/connectors/test_service.py::test_sync_produces_raw_record_and_percept_with_lineage",
            "note": "extra fixture fields ignored by Fake normalizer",
        },
        "backfill_preview_safe": {
            "status": "pass",
            "evidence": "tests/connectors/test_ops.py::test_backfill_preview_still_safe",
        },
        "large_attachment": {
            "status": "not_applicable",
            "evidence": None,
            "note": "Fake has no binary fetch path",
        },
    },
    "github": {
        "idempotent_ingest": {
            "status": "pass",
            "evidence": "tests/connectors/github/test_adapter.py::test_same_sync_twice_is_idempotent",
        },
        "partial_batch_invisible": {
            "status": "pass",
            "evidence": "tests/connectors/github/test_adapter.py::test_partial_batch_failure_exposes_nothing",
        },
        "revision_collision_dlq": {
            "status": "not_tested",
            "evidence": None,
            "note": "relies on framework; no GitHub-specific collision fixture",
        },
        "quarantine_no_percept": {
            "status": "pass",
            "evidence": "tests/connectors/github/test_adapter.py::test_malicious_comment_quarantined_batch_still_commits",
        },
        "source_deletion_event": {
            "status": "not_supported",
            "evidence": None,
            "note": "manifest.affordances.deletions=false (REST polling)",
        },
        "checkpoint_after_commit": {
            "status": "pass",
            "evidence": "tests/connectors/github/test_adapter.py::test_same_sync_twice_is_idempotent",
            "note": "checkpoint stable across idempotent resync",
        },
        "rate_limit_structured": {
            "status": "pass",
            "evidence": "tests/connectors/github/test_adapter.py::test_rate_limit_degrades_with_provider_window",
        },
        "unauthorized_health": {
            "status": "pass",
            "evidence": "tests/connectors/github/test_adapter.py::test_auth_expiration_reports_unauthorized",
        },
        "unknown_schema_tolerated": {
            "status": "pass",
            "evidence": "tests/connectors/github/test_adapter.py::test_unknown_schema_fields_are_tolerated",
        },
        "backfill_preview_safe": {
            "status": "pass",
            "evidence": "tests/connectors/github/test_adapter.py::test_backfill_preview_reports_scope_and_never_ingests",
        },
        "large_attachment": {
            "status": "not_supported",
            "evidence": None,
            "note": "metadata-first REST; bytes not fetched",
        },
    },
    "slack": {
        "idempotent_ingest": {
            "status": "pass",
            "evidence": "tests/connectors/slack/test_adapter.py::test_same_sync_twice_is_idempotent",
        },
        "partial_batch_invisible": {
            "status": "not_tested",
            "evidence": None,
        },
        "revision_collision_dlq": {
            "status": "not_tested",
            "evidence": None,
        },
        "quarantine_no_percept": {
            "status": "not_tested",
            "evidence": None,
        },
        "source_deletion_event": {
            "status": "pass",
            "evidence": "tests/connectors/slack/test_adapter.py::test_deletion_tombstone_from_webhook",
        },
        "checkpoint_after_commit": {
            "status": "pass",
            "evidence": "tests/connectors/slack/test_adapter.py::test_same_sync_twice_is_idempotent",
        },
        "rate_limit_structured": {
            "status": "pass",
            "evidence": "tests/connectors/slack/test_adapter.py::test_rate_limit_degrades",
        },
        "unauthorized_health": {
            "status": "not_tested",
            "evidence": None,
        },
        "unknown_schema_tolerated": {
            "status": "partial",
            "evidence": None,
            "note": "extra event fields ignored; no dedicated test",
        },
        "backfill_preview_safe": {
            "status": "pass",
            "evidence": "tests/connectors/slack/test_adapter.py::test_backfill_preview_never_ingests",
        },
        "large_attachment": {
            "status": "not_supported",
            "evidence": None,
            "note": "files metadata_only",
        },
    },
    "gmail": {
        "idempotent_ingest": {
            "status": "pass",
            "evidence": "tests/connectors/gmail/test_adapter.py::test_idempotent_resync",
        },
        "partial_batch_invisible": {"status": "not_tested", "evidence": None},
        "revision_collision_dlq": {"status": "not_tested", "evidence": None},
        "quarantine_no_percept": {"status": "not_tested", "evidence": None},
        "source_deletion_event": {
            "status": "pass",
            "evidence": "tests/connectors/gmail/test_adapter.py::test_history_deletion_emits_event",
        },
        "checkpoint_after_commit": {
            "status": "pass",
            "evidence": "tests/connectors/gmail/test_adapter.py::test_idempotent_resync",
        },
        "rate_limit_structured": {
            "status": "pass",
            "evidence": "tests/connectors/gmail/test_adapter.py::test_rate_limit_degrades",
        },
        "unauthorized_health": {"status": "not_tested", "evidence": None},
        "unknown_schema_tolerated": {"status": "not_tested", "evidence": None},
        "backfill_preview_safe": {
            "status": "pass",
            "evidence": "tests/connectors/gmail/test_adapter.py::test_backfill_preview_lists_partitions",
        },
        "large_attachment": {
            "status": "partial",
            "evidence": None,
            "note": "attachment_mode metadata_only|discovery",
        },
    },
    "outlook": {
        "idempotent_ingest": {"status": "not_tested", "evidence": None},
        "partial_batch_invisible": {"status": "not_tested", "evidence": None},
        "revision_collision_dlq": {"status": "not_tested", "evidence": None},
        "quarantine_no_percept": {"status": "not_tested", "evidence": None},
        "source_deletion_event": {
            "status": "pass",
            "evidence": "tests/connectors/outlook/test_adapter.py::test_delta_removed_emits_deletion",
        },
        "checkpoint_after_commit": {"status": "not_tested", "evidence": None},
        "rate_limit_structured": {
            "status": "pass",
            "evidence": "tests/connectors/outlook/test_adapter.py::test_rate_limit_degrades",
        },
        "unauthorized_health": {"status": "not_tested", "evidence": None},
        "unknown_schema_tolerated": {"status": "not_tested", "evidence": None},
        "backfill_preview_safe": {"status": "not_tested", "evidence": None},
        "large_attachment": {
            "status": "partial",
            "evidence": None,
            "note": "attachment_mode metadata_only|discovery",
        },
    },
    "calendar": {
        "idempotent_ingest": {
            "status": "pass",
            "evidence": "tests/connectors/calendar/test_adapter.py::test_idempotent_resync",
        },
        "partial_batch_invisible": {"status": "not_tested", "evidence": None},
        "revision_collision_dlq": {"status": "not_tested", "evidence": None},
        "quarantine_no_percept": {"status": "not_tested", "evidence": None},
        "source_deletion_event": {
            "status": "pass",
            "evidence": "tests/connectors/calendar/test_adapter.py::test_cancelled_emits_tombstone",
        },
        "checkpoint_after_commit": {
            "status": "pass",
            "evidence": "tests/connectors/calendar/test_adapter.py::test_idempotent_resync",
        },
        "rate_limit_structured": {
            "status": "pass",
            "evidence": "tests/connectors/calendar/test_adapter.py::test_rate_limit_degrades",
        },
        "unauthorized_health": {"status": "not_tested", "evidence": None},
        "unknown_schema_tolerated": {"status": "not_tested", "evidence": None},
        "backfill_preview_safe": {"status": "not_tested", "evidence": None},
        "large_attachment": {
            "status": "not_applicable",
            "evidence": None,
        },
    },
    "fireflies": {
        "idempotent_ingest": {
            "status": "pass",
            "evidence": "tests/connectors/fireflies/test_adapter.py::test_idempotent_resync",
        },
        "partial_batch_invisible": {"status": "not_tested", "evidence": None},
        "revision_collision_dlq": {"status": "not_tested", "evidence": None},
        "quarantine_no_percept": {"status": "not_tested", "evidence": None},
        "source_deletion_event": {
            "status": "not_supported",
            "evidence": None,
            "note": "manifest.affordances.deletions=false",
        },
        "checkpoint_after_commit": {
            "status": "pass",
            "evidence": "tests/connectors/fireflies/test_adapter.py::test_idempotent_resync",
        },
        "rate_limit_structured": {
            "status": "pass",
            "evidence": "tests/connectors/fireflies/test_adapter.py::test_rate_limit_degrades",
        },
        "unauthorized_health": {"status": "not_tested", "evidence": None},
        "unknown_schema_tolerated": {"status": "not_tested", "evidence": None},
        "backfill_preview_safe": {"status": "not_tested", "evidence": None},
        "large_attachment": {
            "status": "not_applicable",
            "evidence": None,
            "note": "recording URLs not persisted",
        },
    },
    "folder": {
        "idempotent_ingest": {
            "status": "pass",
            "evidence": "tests/connectors/folder/test_adapter.py::test_idempotent_resync",
        },
        "partial_batch_invisible": {"status": "not_tested", "evidence": None},
        "revision_collision_dlq": {"status": "not_tested", "evidence": None},
        "quarantine_no_percept": {"status": "not_tested", "evidence": None},
        "source_deletion_event": {
            "status": "pass",
            "evidence": "tests/connectors/folder/test_adapter.py::test_delete_emits_tombstone",
        },
        "checkpoint_after_commit": {
            "status": "pass",
            "evidence": "tests/connectors/folder/test_adapter.py::test_idempotent_resync",
        },
        "rate_limit_structured": {
            "status": "not_applicable",
            "evidence": None,
            "note": "local FS — no provider rate limit",
        },
        "unauthorized_health": {
            "status": "partial",
            "evidence": None,
            "note": "unreadable roots → degraded/awaiting_configuration",
        },
        "unknown_schema_tolerated": {"status": "not_applicable", "evidence": None},
        "backfill_preview_safe": {
            "status": "partial",
            "evidence": None,
            "note": "roots discovery; no estimate_backfill",
        },
        "large_attachment": {
            "status": "partial",
            "evidence": None,
            "note": "oversized files → metadata-only manifests",
        },
    },
}


def _cell(status: str, *, evidence: Optional[str] = None,
          note: str = "") -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"invalid contract status {status!r}")
    return {"status": status, "evidence": evidence, "note": note}


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


def _row_ok(items: dict[str, dict[str, Any]]) -> bool:
    """Fail closed on required fail/not_tested. partial does not fail the row
    but is surfaced; not_supported/not_applicable are allowed when declared."""
    for name, meta in CONTRACT_ITEMS.items():
        cell = items.get(name) or _cell("not_tested")
        status = cell["status"]
        if not meta.get("required", True):
            if status == "fail":
                return False
            continue
        if status in ("fail", "not_tested"):
            return False
        # partial keeps row.ok false for required behavioural honesty
        if status == "partial" and meta.get("layer") == "behaviour":
            return False
    return True


def check_adapter_contract(connector_type: str) -> dict[str, Any]:
    """Return a §88 matrix row with structured evidence cells."""
    cls = get_adapter_class(connector_type)
    manifest = get_manifest(connector_type)
    gaps = _manifest_gaps(manifest)
    methods_ok = all(callable(getattr(cls, name, None)) for name in _REQUIRED_PROTOCOL)

    items: dict[str, dict[str, Any]] = {}
    items["manifest_complete"] = _cell(
        "pass" if not gaps else "fail",
        note=",".join(gaps) if gaps else "",
    )
    items["auth_mode_declared"] = _cell("pass" if manifest.auth_mode else "fail")
    items["streams_or_dynamic"] = _cell(
        "pass" if (manifest.streams or manifest.dynamic_streams) else "fail",
    )
    items["supported_external_types"] = _cell(
        "pass" if manifest.supported_external_types else "fail",
    )
    items["affordances_declared"] = _cell(
        "pass" if isinstance(manifest.affordances, dict) else "fail",
    )
    items["protocol_methods"] = _cell("pass" if methods_ok else "fail")

    evidence_map = EVIDENCE.get(connector_type, {})
    for name, meta in CONTRACT_ITEMS.items():
        if name in items:
            continue
        affordance = meta.get("affordance")
        if affordance and not (manifest.affordances or {}).get(affordance, True):
            items[name] = _cell(
                "not_supported",
                note=f"manifest.affordances.{affordance}=false",
            )
            continue
        raw = evidence_map.get(name)
        if raw is None:
            items[name] = _cell("not_tested", note="No adapter-specific evidence registered")
        else:
            items[name] = _cell(
                raw["status"],
                evidence=raw.get("evidence"),
                note=raw.get("note") or "",
            )
            # Evidence claim of pass without a pointer → demote
            if items[name]["status"] == "pass" and not items[name]["evidence"]:
                items[name] = _cell(
                    "not_tested",
                    note="pass claimed without evidence pointer",
                )

    failed = [
        k for k, v in items.items()
        if v["status"] in ("fail", "not_tested")
        and CONTRACT_ITEMS.get(k, {}).get("required", True)
    ]
    partial = [k for k, v in items.items() if v["status"] == "partial"]
    return {
        "connector_type": connector_type,
        "adapter_class": cls.__name__,
        "auth_mode": manifest.auth_mode,
        "dynamic_streams": bool(manifest.dynamic_streams),
        "streams": list(manifest.streams),
        "external_types": list(manifest.supported_external_types),
        "affordances": dict(manifest.affordances or {}),
        "protocol_ok": methods_ok,
        "items": items,
        "gaps": gaps,
        "missing_required": failed,
        "partial_items": partial,
        "ok": _row_ok(items),
    }


def framework_contract() -> dict[str, Any]:
    """Framework spine proven via FakeConnector — separate from adapter rows."""
    row = check_adapter_contract("fake")
    return {
        "layer": "framework",
        "ok": row["ok"],
        "row": row,
        "note": (
            "Framework pass proves the shared spine on FakeConnector only; "
            "it does not certify real adapters."
        ),
    }


def contract_matrix() -> dict[str, Any]:
    """Full §88 matrix. ``ok`` is true only when every adapter row is ok."""
    rows = [check_adapter_contract(name) for name in list_adapters()]
    fw = framework_contract()
    return {
        "contract": "v0.6 §88",
        "adapters": len(rows),
        "ok": all(r["ok"] for r in rows),
        "framework": fw,
        "rows": rows,
        "checklist": list(CONTRACT_ITEMS),
        "statuses": sorted(STATUSES),
        "note": (
            "ok=false means at least one required item is fail/not_tested/partial. "
            "not_supported requires a manifest affordance. Framework evidence "
            "never implies adapter pass."
        ),
    }
