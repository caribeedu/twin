"""Orchestrate a cross-source correlation pass (v0.6 Phase 7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .conflicts import detect_temporal_conflicts
from .episodes import correlate_records
from .identity import ingest_actors_from_record, propose_identity_links
from .models import ExternalIdentity, WorkEpisode
from .projects import resolve_project_for_record


@dataclass
class CorrelationReport:
    identities: int = 0
    identity_links: int = 0
    project_links: int = 0
    episodes: int = 0
    conflicts: int = 0
    records_scanned: int = 0
    episode_ids: list[str] = field(default_factory=list)


def run_correlation_pass(
    store,
    *,
    connector_ids: Optional[list[str]] = None,
    limit: int = 2000,
    detect_conflicts: bool = True,
) -> CorrelationReport:
    """Scan connector records → identities, project maps, episodes, conflicts.

    Safe to re-run: upserts / finds existing links. Does not write Memory or
    Judgment.
    """
    report = CorrelationReport()
    records: list[Any] = []
    if connector_ids:
        for cid in connector_ids:
            records.extend(store.list_connector_records(cid)[:limit])
    else:
        # All instances known to the store.
        if hasattr(store, "list_connector_instances"):
            for inst in store.list_connector_instances():
                records.extend(store.list_connector_records(inst.id)[:limit])
        else:
            return report

    # Drop tombstones from correlation clustering (keep for lineage elsewhere).
    live = [r for r in records if not getattr(r, "deleted", False)]
    report.records_scanned = len(live)

    identities: list[ExternalIdentity] = []
    seen_ident: set[str] = set()
    project_link_count = 0
    for rec in live:
        for ident in ingest_actors_from_record(store, rec):
            if ident.id not in seen_ident:
                seen_ident.add(ident.id)
                identities.append(ident)
        _pid, link = resolve_project_for_record(store, rec)
        if link is not None:
            project_link_count += 1

    report.identities = len(identities)
    links = propose_identity_links(store, identities)
    report.identity_links = len(links)
    report.project_links = project_link_count

    episodes = correlate_records(store, live)
    report.episodes = len(episodes)
    report.episode_ids = [e.id for e in episodes]

    if detect_conflicts:
        for ep in episodes:
            findings = detect_temporal_conflicts(store, ep)
            report.conflicts += len(findings)

    return report


def independence_group_for_record(record: Any) -> str:
    """Convenience for tests / CLI — group key from a ConnectorRecord."""
    from .independence import independence_group_for

    meta = {
        "external_id": getattr(record, "external_id", None),
        "thread_key": getattr(record, "thread_key", None),
        "source_metadata": getattr(record, "source_metadata", None) or {},
        "artifact_refs": getattr(record, "artifact_refs", None) or [],
    }
    return independence_group_for(meta)
