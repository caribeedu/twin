"""Project mapping from external containers."""

from __future__ import annotations

from typing import Any, Optional

from ...clock import now_iso
from .models import ProjectLink, ProjectLinkStatus
from .partition import account_meta

# Exact repo / allowlisted channel match — strong enough to attach episode
# project_id, but ProjectLink stays candidate until user confirms.
STRONG_MATCH = 0.90
HINT_MATCH = 0.70

# Statuses that may attach an episode to a project (current ownership).
_ATTACHABLE = frozenset({
    ProjectLinkStatus.candidate,
    ProjectLinkStatus.confirmed,
    ProjectLinkStatus.candidate.value,
    ProjectLinkStatus.confirmed.value,
})


def _status_val(link: ProjectLink) -> str:
    st = getattr(link, "status", None)
    if st is None:
        return (ProjectLinkStatus.confirmed.value if link.confirmed
                else ProjectLinkStatus.candidate.value)
    return getattr(st, "value", st)


def _is_attachable(link: ProjectLink) -> bool:
    return _status_val(link) in _ATTACHABLE


def _repo_from_record(record: Any) -> Optional[str]:
    sm = getattr(record, "source_metadata", None) or {}
    repo = sm.get("repo")
    if isinstance(repo, str) and repo.strip():
        return repo.strip()
    return None


def _external_container(record: Any) -> tuple[str, str]:
    """Return (external_type, external_id) for a project-linkable container."""
    sm = getattr(record, "source_metadata", None) or {}
    et = getattr(record, "external_type", "") or ""
    repo = sm.get("repo")
    if repo:
        return "github_repository", str(repo)
    channel = sm.get("channel_id") or sm.get("channel")
    # Slack message/thread records carry ``external_type`` like "message" (not
    # "slack…"), so key off the slack-specific metadata instead of the type name.
    slackish = (
        et.startswith("slack")
        or "channel" in et
        or bool(sm.get("team_id") or sm.get("workspace_id")
                or sm.get("channel_kind"))
        or ("ts" in sm and "author_kind" in sm)
    )
    if channel and slackish:
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
    """Prefer account-scoped link; fall back only to legacy unscoped (``""``).

    Never returns another account's link for the same external container —
    account/vault partition is structural. Lifecycle decisions on a legacy
    unscoped link still stick when the caller has an account id.
    """
    if source_account_id:
        hit = store.find_project_link(
            external_type=external_type,
            external_id=external_id,
            source_account_id=source_account_id,
        )
        if hit is not None:
            return hit
    return store.find_project_link(
        external_type=external_type,
        external_id=external_id,
        source_account_id="",
    )


def resolve_project_for_record(store, record: Any) -> tuple[Optional[str], Optional[ProjectLink]]:
    """Map a ConnectorRecord onto a Project id when evidence is strong enough.

    Returns (project_id, link). Never invents a Project — only links to
    existing ones via Project.repos / aliases / ProjectLinks.
    ``historical`` / ``rejected`` links are never attached to episodes and
    block auto-creating a fresh candidate for the same container.
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
        if not _is_attachable(existing):
            return None, existing
        if (_status_val(existing) == ProjectLinkStatus.confirmed.value
                or existing.confirmed
                or existing.confidence >= STRONG_MATCH):
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
    meta = account_meta(store, record)
    link = ProjectLink(
        project_id=proj.id,
        source_account_id=account_id,
        vault_id=meta["vault_id"],
        external_type=ext_type,
        external_id=ext_id,
        confidence=conf,
        status=ProjectLinkStatus.candidate,
        confirmed=False,
        metadata={"signal": reason},
    )
    store.insert_project_link(link)
    if conf >= STRONG_MATCH:
        return proj.id, link
    return None, link


def set_project_link_status(
    store, link_id: str, status: ProjectLinkStatus | str,
) -> ProjectLink:
    """Set lifecycle status. Only ``candidate|confirmed`` attach episodes."""
    link = store.get_project_link(link_id)
    if link is None:
        raise ValueError(f"project link {link_id} not found")
    try:
        new_status = status if isinstance(status, ProjectLinkStatus) \
            else ProjectLinkStatus(status)
    except ValueError as exc:
        raise ValueError(
            f"invalid project link status {status!r}; "
            f"allowed={[s.value for s in ProjectLinkStatus]}"
        ) from exc
    prev = _status_val(link)
    link.status = new_status
    link.confirmed = new_status == ProjectLinkStatus.confirmed
    if new_status == ProjectLinkStatus.confirmed:
        link.confidence = max(link.confidence, 0.99)
    meta = dict(link.metadata or {})
    # Operational history (not a full audit log): from/to + wall clock.
    meta["status_history"] = list(meta.get("status_history") or []) + [{
        "from": prev,
        "to": new_status.value,
        "changed_at": now_iso(),
        "actor": "user",
        "reason": None,
    }]
    link.metadata = meta
    store.update_project_link(link)
    return link


def confirm_project_link(store, link_id: str) -> ProjectLink:
    return set_project_link_status(store, link_id, ProjectLinkStatus.confirmed)


def reject_project_link(store, link_id: str) -> ProjectLink:
    return set_project_link_status(store, link_id, ProjectLinkStatus.rejected)


def archive_project_link(store, link_id: str) -> ProjectLink:
    """Mark link historical — provenance kept, not current ownership."""
    return set_project_link_status(store, link_id, ProjectLinkStatus.historical)


def link_project(
    store,
    *,
    project_id: str,
    external_type: str,
    external_id: str,
    source_account_id: str = "",
    confirmed: bool = True,
    confidence: float = 1.0,
    status: Optional[ProjectLinkStatus | str] = None,
) -> ProjectLink:
    if status is None:
        status = (ProjectLinkStatus.confirmed if confirmed
                  else ProjectLinkStatus.candidate)
    elif not isinstance(status, ProjectLinkStatus):
        status = ProjectLinkStatus(status)
    existing = find_project_for_external(
        store, external_type=external_type, external_id=external_id,
        source_account_id=source_account_id,
    )
    if existing is not None:
        existing.project_id = project_id
        existing.status = status
        existing.confirmed = status == ProjectLinkStatus.confirmed
        existing.confidence = confidence
        store.update_project_link(existing)
        return existing
    link = ProjectLink(
        project_id=project_id,
        source_account_id=source_account_id,
        external_type=external_type,
        external_id=external_id,
        confidence=confidence,
        status=status,
        confirmed=status == ProjectLinkStatus.confirmed,
    )
    store.insert_project_link(link)
    return link
