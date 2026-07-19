"""Read-only explainability for correlation hypotheses (v0.6).

Surfaces *why* an episode / identity link / project link exists from data
Phase 7 already stores — never invents Memory or Judgment.
"""

from __future__ import annotations

from typing import Any, Optional

from .models import EpisodeLinkStatus, ProjectLinkStatus


def explain_episode(store, episode_id: str) -> dict[str, Any]:
    ep = store.get_work_episode(episode_id)
    if ep is None:
        return {"episode_id": episode_id, "error": "not found"}

    links = store.list_episode_links(episode_id)
    active = [
        lk for lk in links
        if getattr(lk.status, "value", lk.status) == EpisodeLinkStatus.active.value
    ]
    anchors: list[dict[str, Any]] = []
    if hasattr(store, "list_episode_anchors"):
        for a in store.list_episode_anchors(episode_id):
            anchors.append({
                "type": a.get("anchor_type") if isinstance(a, dict)
                else getattr(a, "anchor_type", None),
                "value": a.get("anchor_value") if isinstance(a, dict)
                else getattr(a, "anchor_value", None),
                "vault_id": a.get("vault_id") if isinstance(a, dict)
                else getattr(a, "vault_id", None),
            })
    elif ep.metadata.get("anchors"):
        anchors = list(ep.metadata.get("anchors") or [])

    merge_kinds = {"explicit", "reference"}
    link_rows = []
    indep: dict[str, int] = {}
    for lk in links:
        kind = getattr(lk.kind, "value", lk.kind)
        st = getattr(lk.status, "value", lk.status)
        role = "merge" if kind in merge_kinds else (
            "contextual" if kind in ("fingerprint", "thread") else kind
        )
        link_rows.append({
            "id": lk.id,
            "kind": kind,
            "role": role,
            "status": st,
            "confidence": lk.confidence,
            "external_type": lk.external_type,
            "external_id": lk.external_id,
            "independence_group": lk.independence_group,
            "directness": lk.directness,
            "lineage_root": lk.lineage_root,
            "connector_record_id": lk.connector_record_id,
        })
        if st == "active" and lk.independence_group:
            indep[lk.independence_group] = indep.get(lk.independence_group, 0) + 1

    findings: list[dict[str, Any]] = []
    mem_id = f"episode:{episode_id}"
    if hasattr(store, "get_findings"):
        for f in store.get_findings(mem_id, unresolved_only=False):
            st = getattr(f.status, "value", getattr(f, "status", None))
            findings.append({
                "id": f.id,
                "type": getattr(f.type, "value", f.type),
                "status": st,
                "finding_key": (f.metadata or {}).get("finding_key"),
                "reason": getattr(f, "reason", "") or "",
                "resolved": bool(getattr(f, "resolved", False) or st not in (
                    None, "open",
                )),
            })

    return {
        "episode_id": ep.id,
        "vault_id": ep.vault_id,
        "correlation_key": ep.correlation_key,
        "title": ep.title,
        "status": getattr(ep.status, "value", ep.status),
        "project_id": ep.project_id,
        "confidence": ep.confidence,
        "confidence_basis": (
            "max(active EpisodeLink.confidence); recomputed on membership rebuild"
        ),
        "independence_group": ep.independence_group,
        "independence_group_count": ep.independence_group_count,
        "independence_groups": indep,
        "anchors": anchors,
        "links": link_rows,
        "active_links": len(active),
        "source_refs": list(ep.source_refs or []),
        "participant_actor_ids": list(ep.participant_actor_ids or []),
        "open_findings": [f for f in findings if not f.get("resolved")],
        "findings": findings,
        "started_at": ep.started_at,
        "ended_at": ep.ended_at,
    }


def explain_identity_link(store, link_id: str) -> dict[str, Any]:
    link = store.get_identity_link(link_id)
    if link is None:
        return {"link_id": link_id, "error": "not found"}
    left = store.get_external_identity(link.left_identity_id)
    right = (
        store.get_external_identity(link.right_identity_id)
        if link.right_identity_id else None
    )
    return {
        "link_id": link.id,
        "status": getattr(link.status, "value", link.status),
        "confidence": link.confidence,
        "vault_id": link.vault_id,
        "cross_domain": link.cross_domain,
        "signals": list(link.signals or []),
        "entity_id": link.entity_id,
        "left": _ident_brief(left),
        "right": _ident_brief(right),
        "why": (
            "Proposed from shared email / same-provider id within one vault; "
            "never display-name-only. Confirmation is manual."
        ),
        "metadata": dict(link.metadata or {}),
    }


def explain_project_link(store, link_id: str) -> dict[str, Any]:
    link = store.get_project_link(link_id)
    if link is None:
        return {"link_id": link_id, "error": "not found"}
    status = getattr(link.status, "value", None)
    if status is None:
        status = (ProjectLinkStatus.confirmed.value if link.confirmed
                  else ProjectLinkStatus.candidate.value)
    attachable = status in (
        ProjectLinkStatus.candidate.value,
        ProjectLinkStatus.confirmed.value,
    )
    proj = store.get_project(link.project_id) if hasattr(store, "get_project") else None
    return {
        "link_id": link.id,
        "project_id": link.project_id,
        "project_name": getattr(proj, "name", None) if proj else None,
        "external_type": link.external_type,
        "external_id": link.external_id,
        "vault_id": link.vault_id,
        "status": status,
        "confirmed": bool(link.confirmed),
        "confidence": link.confidence,
        "attachable_to_episode": attachable,
        "signal": (link.metadata or {}).get("signal"),
        "why": (
            "Mapped via Project.repos/aliases or explicit twin project link. "
            "historical/rejected never attach episode.project_id."
            if not attachable else
            "Candidate/confirmed link may attach episode.project_id when "
            "confirmed or confidence ≥ strong-match threshold."
        ),
        "metadata": dict(link.metadata or {}),
    }


def _ident_brief(ident: Optional[Any]) -> Optional[dict[str, Any]]:
    if ident is None:
        return None
    return {
        "id": ident.id,
        "actor_id": ident.actor_id,
        "provider": ident.provider,
        "external_id": ident.external_id,
        "email": ident.email,
        "vault_id": ident.vault_id,
        "confirmed": ident.confirmed,
    }
