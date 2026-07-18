"""Project mapping from external containers (v0.6 Phase 7 §18)."""

from __future__ import annotations

from typing import Any, Optional

from .models import ProjectLink

# Exact repo / allowlisted channel match — strong enough to attach episode
# project_id, but ProjectLink.confirmed stays False until user confirms.
STRONG_MATCH = 0.90
HINT_MATCH = 0.70


def _repo_from_record(record: Any) -> Optional[str]:
    sm = getattr(record, "source_metadata", None) or {}
    repo = sm.get("repo")
    if isinstance(repo, str) and repo.strip():
        return repo.strip()
    hint = getattr(record, "project_hint", None)
    # GitHub project_hint is often the short repo name; prefer full repo.
    return None


def _external_container(record: Any) -> tuple[str, str]:
    """Return (external_type, external_id) for a project-linkable container."""
    sm = getattr(record, "source_metadata", None) or {}
    et = getattr(record, "external_type", "") or ""
    repo = sm.get("repo")
    if repo:
        return "github_repository", str(repo)
    channel = sm.get("channel_id") or sm.get("channel")
    if channel and (et.startswith("slack") or "channel" in et):
        return "slack_channel", str(channel)
    if et.startswith("document") or et == "document_revision_chunk":
        root = sm.get("path") or getattr(record, "project_hint", None)
        if root:
            return "document_folder", str(sm.get("parent_folder") or root)
    cal = sm.get("calendar_id")
    if cal:
        return "calendar", str(cal)
    hint = getattr(record, "project_hint", None)
    if hint:
        return "project_hint", str(hint)
    return et or "unknown", str(getattr(record, "external_id", "") or "")


def find_project_for_external(
    store,
    *,
    external_type: str,
    external_id: str,
    source_account_id: str = "",
) -> Optional[ProjectLink]:
    return store.find_project_link(
        external_type=external_type,
        external_id=external_id,
        source_account_id=source_account_id or None,
    )


def resolve_project_for_record(store, record: Any) -> tuple[Optional[str], Optional[ProjectLink]]:
    """Map a ConnectorRecord onto a Project id when evidence is strong enough.

    Returns (project_id, link). Never invents a Project — only links to
    existing ones via Project.repos / aliases / confirmed ProjectLinks.
    """
    account_id = getattr(record, "source_account_id", "") or ""
    ext_type, ext_id = _external_container(record)
    if not ext_id:
        return None, None

    existing = find_project_for_external(
        store, external_type=ext_type, external_id=ext_id,
        source_account_id=account_id,
    )
    if existing is not None:
        if existing.confirmed or existing.confidence >= STRONG_MATCH:
            return existing.project_id, existing
        return None, existing

    # Match against known projects.
    projects = store.list_projects()
    sm = getattr(record, "source_metadata", None) or {}
    repo = sm.get("repo")
    hint = (getattr(record, "project_hint", None) or "").strip().lower()

    best: Optional[tuple[Any, float, str]] = None  # project, conf, reason
    for proj in projects:
        repos_l = [r.lower() for r in (proj.repos or [])]
        aliases_l = [a.lower() for a in (proj.aliases or [])]
        name_l = (proj.name or "").lower()
        if repo and str(repo).lower() in repos_l:
            best = (proj, 1.0, "exact_repo")
            break
        if repo:
            short = str(repo).split("/")[-1].lower()
            if short and short in repos_l:
                best = (proj, STRONG_MATCH, "repo_short_name")
                break
        if hint and (hint == name_l or hint in aliases_l or hint in repos_l):
            cand = (proj, HINT_MATCH, "project_hint")
            if best is None or cand[1] > best[1]:
                best = cand

    if best is None:
        return None, None

    proj, conf, reason = best
    link = ProjectLink(
        project_id=proj.id,
        source_account_id=account_id,
        external_type=ext_type,
        external_id=ext_id,
        confidence=conf,
        confirmed=False,
        metadata={"signal": reason},
    )
    store.insert_project_link(link)
    if conf >= STRONG_MATCH:
        return proj.id, link
    return None, link


def confirm_project_link(store, link_id: str) -> ProjectLink:
    link = store.get_project_link(link_id)
    if link is None:
        raise ValueError(f"project link {link_id} not found")
    link.confirmed = True
    link.confidence = max(link.confidence, 0.99)
    store.update_project_link(link)
    return link


def link_project(
    store,
    *,
    project_id: str,
    external_type: str,
    external_id: str,
    source_account_id: str = "",
    confirmed: bool = True,
    confidence: float = 1.0,
) -> ProjectLink:
    existing = find_project_for_external(
        store, external_type=external_type, external_id=external_id,
        source_account_id=source_account_id,
    )
    if existing is not None:
        existing.project_id = project_id
        existing.confirmed = confirmed
        existing.confidence = confidence
        store.update_project_link(existing)
        return existing
    link = ProjectLink(
        project_id=project_id,
        source_account_id=source_account_id,
        external_type=external_type,
        external_id=external_id,
        confidence=confidence,
        confirmed=confirmed,
    )
    store.insert_project_link(link)
    return link
