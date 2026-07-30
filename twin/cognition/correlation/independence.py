"""Source independence groups.

A GitHub notification email and the PR it restates share one informational
root — they must not count as independent corroboration.
"""

from __future__ import annotations

from typing import Any, Optional

from ...sensory.percept import Percept


def _meta_source(percept_or_meta: Percept | dict[str, Any]) -> dict[str, Any]:
    if isinstance(percept_or_meta, Percept):
        return dict(percept_or_meta.metadata or {})
    return dict(percept_or_meta or {})


def independence_group_for(
    percept_or_meta: Percept | dict[str, Any],
    *,
    fallback: Optional[str] = None,
) -> str:
    """Return a stable independence group key for evidence attachment.

    Priority:
      1. explicit independence_group
      2. notification_of / quoted_from / derived_from
      3. lineage_root (incl. bot/notification derived)
      4. correlation_fingerprint / calendar_event_id
      5. thread_key
      6. fallback (artifact/percept id)
    """
    meta = _meta_source(percept_or_meta)
    sm = dict(meta.get("source_metadata") or {})

    for key in ("independence_group",):
        val = sm.get(key) or meta.get(key)
        if val:
            return str(val)

    for key in ("notification_of", "quoted_from"):
        val = sm.get(key) or meta.get(key)
        if val:
            return f"lineage:{val}"

    # artifact_refs may carry derived_from
    for ref in meta.get("artifact_refs") or sm.get("artifact_refs") or []:
        if isinstance(ref, dict) and ref.get("kind") == "derived_from" and ref.get("external_id"):
            return f"lineage:{ref['external_id']}"

    lineage = sm.get("lineage_root") or meta.get("lineage_root")
    derived = sm.get("derived") or meta.get("derived")
    if lineage and derived in (
        "likely_notification", "provider_summary", "forwarded", "quoted",
    ):
        return f"lineage:{lineage}"
    if lineage:
        return f"lineage:{lineage}"

    for key in ("correlation_fingerprint", "calendar_event_id", "iCalUID"):
        val = sm.get(key)
        if val:
            return f"corr:{val}"

    thread = meta.get("thread_key") or sm.get("thread_key")
    if thread:
        return f"thread:{thread}"

    return fallback or meta.get("external_id") or "unknown"


def is_derived_evidence(percept_or_meta: Percept | dict[str, Any]) -> bool:
    meta = _meta_source(percept_or_meta)
    sm = dict(meta.get("source_metadata") or {})
    derived = sm.get("derived") or meta.get("derived")
    role = sm.get("evidence_role")
    return bool(
        derived in ("likely_notification", "provider_summary", "forwarded", "quoted")
        or role in ("derived", "operational", "artifact_metadata", "index")
    )


def evidence_directness_for(percept_or_meta: Percept | dict[str, Any]) -> float:
    """Derived / notification evidence is not first-hand."""
    if is_derived_evidence(percept_or_meta):
        sm = _meta_source(percept_or_meta).get("source_metadata") or {}
        if sm.get("derived") == "likely_notification":
            return 0.35
        if sm.get("derived") == "provider_summary":
            return 0.40
        return 0.45
    return 1.0
