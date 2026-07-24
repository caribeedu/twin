"""Orchestrate a cross-source correlation pass."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .conflicts import detect_temporal_conflicts
from .episodes import correlate_records
from .identity import ingest_actors_from_record, propose_identity_links
from .models import ExternalIdentity
from .partition import partition_records, vault_for_record
from .projects import resolve_project_for_record


@dataclass
class CorrelationReport:
    records_scanned: int = 0
    identities_created: int = 0
    identities_updated: int = 0
    identity_links_created: int = 0
    project_links_created: int = 0
    project_links_reused: int = 0
    episodes_created: int = 0
    episodes_updated: int = 0
    episodes_closed: int = 0
    conflicts_created: int = 0
    conflicts_reused: int = 0
    conflicts_resolved: int = 0
    episode_ids: list[str] = field(default_factory=list)
    # Backward-compatible aggregates
    identities: int = 0
    identity_links: int = 0
    project_links: int = 0
    episodes: int = 0
    conflicts: int = 0


def run_correlation_pass(
    store,
    *,
    connector_ids: Optional[list[str]] = None,
    limit: int = 2000,
    detect_conflicts: bool = True,
) -> CorrelationReport:
    """Scan connector records → identities, project maps, episodes, conflicts.

    Partitioned by vault. Idempotent and reconciles membership. Does not write
    Memory or Judgment.
    """
    report = CorrelationReport()
    records: list[Any] = []
    if connector_ids:
        for cid in connector_ids:
            records.extend(store.list_connector_records(cid)[:limit])
    else:
        if hasattr(store, "list_connector_instances"):
            for inst in store.list_connector_instances():
                records.extend(store.list_connector_records(inst.id)[:limit])
        else:
            return report

    deleted_ids = {
        r.id for r in records
        if getattr(r, "deleted", False) and getattr(r, "id", None)
    }
    live = [r for r in records if not getattr(r, "deleted", False)]
    report.records_scanned = len(live)

    identities: list[ExternalIdentity] = []
    seen_ident: set[str] = set()
    known_before = {
        i.id for i in store.list_external_identities()
    } if hasattr(store, "list_external_identities") else set()
    known_proj = {
        (pl.external_type, pl.external_id, pl.source_account_id)
        for pl in store.list_project_links()
    } if hasattr(store, "list_project_links") else set()

    for rec in live:
        for ident in ingest_actors_from_record(store, rec):
            if ident.id not in seen_ident:
                seen_ident.add(ident.id)
                identities.append(ident)
                if ident.id in known_before:
                    report.identities_updated += 1
                else:
                    report.identities_created += 1
                    known_before.add(ident.id)
        _pid, link = resolve_project_for_record(store, rec)
        if link is not None:
            key = (link.external_type, link.external_id, link.source_account_id)
            if key in known_proj:
                report.project_links_reused += 1
            else:
                report.project_links_created += 1
                known_proj.add(key)

    links = propose_identity_links(store, identities)
    report.identity_links_created = len(links)

    by_vault = partition_records(store, live)
    # Also pass tombstones into deleted set per vault reconciliation
    all_episodes: list = []
    known_eps = {
        e.id for e in store.list_work_episodes(limit=5000)
    } if hasattr(store, "list_work_episodes") else set()

    for vault_id, vault_recs in by_vault.items():
        eps = correlate_records(
            store, vault_recs,
            vault_id=vault_id,
            deleted_record_ids=deleted_ids,
        )
        for ep in eps:
            if ep.id in known_eps:
                if ep.status.value == "closed":
                    report.episodes_closed += 1
                else:
                    report.episodes_updated += 1
            else:
                report.episodes_created += 1
                known_eps.add(ep.id)
            all_episodes.append(ep)

    # Reconcile tombstones for vaults that had only deletions
    if deleted_ids:
        for vault_id in {vault_for_record(store, r) for r in records if r.deleted}:
            if vault_id in by_vault:
                continue
            eps = correlate_records(
                store, [], vault_id=vault_id, deleted_record_ids=deleted_ids,
            )
            all_episodes.extend(eps)

    report.episode_ids = [e.id for e in all_episodes]

    if detect_conflicts:
        for ep in all_episodes:
            if ep.status.value == "closed":
                # Close open conflict findings for empty episodes
                from .conflicts import _close_stale_findings
                report.conflicts_resolved += _close_stale_findings(
                    store, ep, active_keys=set(),
                )
                continue
            before = {
                (f.metadata or {}).get("finding_key")
                for f in store.get_findings(f"episode:{ep.id}", unresolved_only=True)
            } if hasattr(store, "get_findings") else set()
            findings = detect_temporal_conflicts(store, ep)
            after_open = {
                (f.metadata or {}).get("finding_key")
                for f in store.get_findings(f"episode:{ep.id}", unresolved_only=True)
            } if hasattr(store, "get_findings") else set()
            for f in findings:
                key = (f.metadata or {}).get("finding_key")
                if key in before:
                    report.conflicts_reused += 1
                else:
                    report.conflicts_created += 1
            resolved = before - after_open
            report.conflicts_resolved += len(resolved)

    report.identities = report.identities_created + report.identities_updated
    report.identity_links = report.identity_links_created
    report.project_links = report.project_links_created + report.project_links_reused
    report.episodes = len(all_episodes)
    report.conflicts = report.conflicts_created + report.conflicts_reused
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
