"""GitHub API objects → ConnectorRecords.

One record per granular object (issue, comment, PR, review, commit…) — the
granularity the cognitive layer needs already exists in GitHub's model, so
the adapter never splits or merges content. Conventions that later phases
rely on:

- ``actor_ids``: ``github:{login}`` — stable keys for identity resolution;
- ``thread_key``: ``github:{repo}#{number}`` shared by an issue/PR and
 everything nested under it — cross-source correlation anchors here;
- ``source_metadata.lineage_root``: the informational root, so a bot
 notification of PR #42 can later join PR #42's independence group
 instead of counting as new evidence;
- ``external_revision``: the provider's own change marker (``updated_at``;
 commits use the immutable sha; reviews append a body hash because GitHub
 exposes no updated_at for them — an edit becomes a NEW revision instead
 of a false collision).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from ..models import ConnectorRecord
from .trust import trust_for

MAX_CONTENT_CHARS = 4000


def _hash8(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:8]


def revision_for_review(review: dict[str, Any]) -> str:
    """GitHub exposes no updated_at for reviews; hashing the body into the
    revision turns an edit into a NEW observed revision, never a collision."""
    state = (review.get("state") or "").upper()
    return f"{review.get('submitted_at') or '0'}.{_hash8(review.get('body') or state)}"


def revision_for_check_summary(status: dict[str, Any]) -> str:
    contexts = status.get("statuses") or []
    state = status.get("state", "unknown")
    summary = ", ".join(
        f"{c.get('context', '?')}={c.get('state', '?')}" for c in contexts[:10]
    )
    return f"{state}.{_hash8(summary)}"


def _login(user: Optional[dict[str, Any]]) -> Optional[str]:
    if not user or not user.get("login"):
        return None
    return f"github:{user['login']}"


def _actors(*users: Optional[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for user in users:
        actor = _login(user)
        if actor and actor not in seen:
            seen.append(actor)
    return seen


def _clip(text: Optional[str]) -> str:
    text = (text or "").strip()
    if len(text) > MAX_CONTENT_CHARS:
        return text[: MAX_CONTENT_CHARS - 1] + "…"
    return text


def _record(
    *, connector_id: str, account_id: str, external_type: str, external_id: str,
    external_revision: str, occurred_at: Optional[str], content: str,
    payload: dict[str, Any], repo: str, thread_key: Optional[str] = None,
    actors: Optional[list[str]] = None, participants: Optional[list[str]] = None,
    lineage_root: Optional[str] = None, state: Optional[str] = None,
) -> ConnectorRecord:
    trust, kind = trust_for(external_type, payload)
    source_metadata: dict[str, Any] = {
        "repo": repo,
        "author_kind": kind,
        "html_url": payload.get("html_url"),
    }
    if state:
        source_metadata["state"] = state
    if lineage_root:
        source_metadata["lineage_root"] = lineage_root
    if kind == "bot":
        # a bot post is usually a notification/derivation, never fresh
        # first-hand evidence — independence groups key off lineage_root
        source_metadata["derived"] = "likely_notification"
        if lineage_root:
            source_metadata["notification_of"] = lineage_root
    return ConnectorRecord(
        connector_id=connector_id,
        source_account_id=account_id,
        external_type=external_type,
        external_id=external_id,
        external_revision=external_revision,
        occurred_at=occurred_at,
        actor_ids=actors or [],
        participant_ids=participants or [],
        project_hint=repo.split("/")[-1],
        thread_key=thread_key,
        artifact_refs=[{"kind": external_type, "html_url": payload.get("html_url"),
                        "api_url": payload.get("url")}],
        content=content,
        source_metadata=source_metadata,
        confidentiality={"source_trust": trust},
    )


def record_from_issue(connector_id: str, account_id: str, repo: str,
                      issue: dict[str, Any]) -> ConnectorRecord:
    number = issue["number"]
    labels = ", ".join(l["name"] for l in issue.get("labels", []) if l.get("name"))
    assignees = [a for a in (issue.get("assignees") or [])]
    lines = [
        f"GitHub issue {repo}#{number}: {issue.get('title', '')}",
        f"state: {issue.get('state')}" + (f" · labels: {labels}" if labels else ""),
    ]
    if issue.get("body"):
        lines.append(_clip(issue["body"]))
    return _record(
        connector_id=connector_id, account_id=account_id,
        external_type="issue", external_id=f"{repo}#{number}",
        external_revision=issue.get("updated_at") or "0",
        occurred_at=issue.get("created_at"),
        content="\n".join(lines), payload=issue, repo=repo,
        thread_key=f"github:{repo}#{number}",
        actors=_actors(issue.get("user")),
        participants=_actors(issue.get("user"), *assignees),
        lineage_root=f"github:{repo}#{number}",
        state=issue.get("state"),
    )


def record_from_issue_comment(connector_id: str, account_id: str, repo: str,
                              comment: dict[str, Any]) -> ConnectorRecord:
    number = _issue_number_from_url(comment.get("issue_url") or comment.get("html_url", ""))
    thread = f"github:{repo}#{number}" if number else None
    header = f"Comment on {repo}#{number}" if number else f"Comment in {repo}"
    return _record(
        connector_id=connector_id, account_id=account_id,
        external_type="issue_comment", external_id=str(comment["id"]),
        external_revision=comment.get("updated_at") or "0",
        occurred_at=comment.get("created_at"),
        content=f"{header} by {(comment.get('user') or {}).get('login', '?')}:\n"
                f"{_clip(comment.get('body'))}",
        payload=comment, repo=repo, thread_key=thread,
        actors=_actors(comment.get("user")),
        lineage_root=thread,
    )


def record_from_pull_request(connector_id: str, account_id: str, repo: str,
                             pr: dict[str, Any]) -> ConnectorRecord:
    number = pr["number"]
    merged = bool(pr.get("merged") or pr.get("merged_at"))
    state = "merged" if merged else pr.get("state", "open")
    requested = pr.get("requested_reviewers") or []
    assignees = pr.get("assignees") or []
    lines = [
        f"GitHub pull request {repo}#{number}: {pr.get('title', '')}",
        f"state: {state.upper()}"
        + (f" · merged at {pr.get('merged_at')}" if merged else "")
        + f" · {pr.get('base', {}).get('ref', '?')} ← {pr.get('head', {}).get('ref', '?')}",
    ]
    if merged:
        lines.append("This is the FINAL, merged state of the change.")
    elif pr.get("state") == "closed":
        lines.append("Closed WITHOUT merging — the change was not adopted.")
    if pr.get("body"):
        lines.append(_clip(pr["body"]))
    rec = _record(
        connector_id=connector_id, account_id=account_id,
        external_type="pull_request", external_id=f"{repo}#{number}",
        external_revision=pr.get("updated_at") or "0",
        occurred_at=pr.get("created_at"),
        content="\n".join(lines), payload=pr, repo=repo,
        thread_key=f"github:{repo}#{number}",
        actors=_actors(pr.get("user")),
        participants=_actors(pr.get("user"), *assignees, *requested),
        lineage_root=f"github:{repo}#{number}",
        state=state,
    )
    # Authoritative structural link to the landing commit. For a *merged* PR,
    # ``merge_commit_sha`` is the sha that actually landed on the base branch
    # (the merge commit, or the squashed/rebased commit). Correlation keys an
    # anchor off it so the PR and its commit fuse without parsing messages.
    # (Open PRs also carry a merge_commit_sha, but it is a throwaway test-merge
    # not present in history, so we only trust it once merged.)
    if merged and pr.get("merge_commit_sha"):
        rec.source_metadata["merge_commit_sha"] = pr["merge_commit_sha"]
    return rec


def record_from_review(connector_id: str, account_id: str, repo: str,
                       pr_number: int, review: dict[str, Any]) -> ConnectorRecord:
    state = (review.get("state") or "").upper()
    revision = revision_for_review(review)
    content = (f"Review on {repo}#{pr_number} by "
               f"{(review.get('user') or {}).get('login', '?')}: {state}")
    if review.get("body"):
        content += f"\n{_clip(review['body'])}"
    return _record(
        connector_id=connector_id, account_id=account_id,
        external_type="review", external_id=str(review["id"]),
        external_revision=revision,
        occurred_at=review.get("submitted_at"),
        content=content, payload=review, repo=repo,
        thread_key=f"github:{repo}#{pr_number}",
        actors=_actors(review.get("user")),
        lineage_root=f"github:{repo}#{pr_number}",
        state=state.lower() or None,
    )


def record_from_review_comment(connector_id: str, account_id: str, repo: str,
                               comment: dict[str, Any]) -> ConnectorRecord:
    number = _issue_number_from_url(comment.get("pull_request_url")
                                    or comment.get("html_url", ""))
    thread = f"github:{repo}#{number}" if number else None
    location = comment.get("path", "?")
    return _record(
        connector_id=connector_id, account_id=account_id,
        external_type="review_comment", external_id=str(comment["id"]),
        external_revision=comment.get("updated_at") or "0",
        occurred_at=comment.get("created_at"),
        content=f"Review comment on {repo}#{number} ({location}) by "
                f"{(comment.get('user') or {}).get('login', '?')}:\n"
                f"{_clip(comment.get('body'))}",
        payload=comment, repo=repo, thread_key=thread,
        actors=_actors(comment.get("user")),
        lineage_root=thread,
    )


def record_from_commit(connector_id: str, account_id: str, repo: str,
                       commit: dict[str, Any]) -> ConnectorRecord:
    sha = commit["sha"]
    inner = commit.get("commit") or {}
    author = inner.get("author") or {}
    committer = inner.get("committer") or {}
    message = _clip(inner.get("message"))
    rec = _record(
        connector_id=connector_id, account_id=account_id,
        external_type="commit", external_id=sha,
        external_revision=sha,  # immutable by construction
        occurred_at=author.get("date"),
        content=f"Commit {sha[:12]} in {repo} by "
                f"{author.get('name') or (commit.get('author') or {}).get('login', '?')}:\n"
                f"{message}",
        payload=commit, repo=repo,
        actors=_actors(commit.get("author")),
    )
    branch = commit.get("_branch_scope") or commit.get("branch_scope")
    if branch:
        rec.source_metadata["branch_scope"] = branch
        rec.source_metadata["default_branch_at_observation"] = branch
    if committer.get("date"):
        rec.source_metadata["committer_date"] = committer.get("date")
    if author.get("date"):
        rec.source_metadata["author_date"] = author.get("date")
    return rec


def revision_for_release(release: dict[str, Any]) -> str:
    """Releases can be edited after publish; hash relevant fields so edits
    become a new revision instead of a collision or a silent miss."""
    published = release.get("published_at") or release.get("created_at") or "0"
    content_fields = {
        "name": release.get("name"),
        "body": release.get("body"),
        "draft": release.get("draft"),
        "prerelease": release.get("prerelease"),
        "target_commitish": release.get("target_commitish"),
        "tag_name": release.get("tag_name"),
    }
    canonical = json.dumps(content_fields, sort_keys=True, default=str)
    return f"{published}.{_hash8(canonical)}"


def record_from_release(connector_id: str, account_id: str, repo: str,
                        release: dict[str, Any]) -> ConnectorRecord:
    return _record(
        connector_id=connector_id, account_id=account_id,
        external_type="release", external_id=str(release["id"]),
        external_revision=revision_for_release(release),
        occurred_at=release.get("published_at") or release.get("created_at"),
        content=f"Release {release.get('tag_name', '?')} in {repo}: "
                f"{release.get('name') or ''}\n{_clip(release.get('body'))}",
        payload=release, repo=repo,
        actors=_actors(release.get("author")),
    )


def record_from_check_summary(connector_id: str, account_id: str, repo: str,
                              pr_number: int, head_sha: str,
                              status: dict[str, Any]) -> ConnectorRecord:
    contexts = status.get("statuses") or []
    state = status.get("state", "unknown")
    summary = ", ".join(
        f"{c.get('context', '?')}={c.get('state', '?')}" for c in contexts[:10]
    )
    revision = revision_for_check_summary(status)
    return _record(
        connector_id=connector_id, account_id=account_id,
        external_type="check_summary", external_id=f"{repo}@{head_sha}",
        external_revision=revision,
        occurred_at=None,
        content=f"CI summary for {repo}#{pr_number} @ {head_sha[:12]}: "
                f"{state.upper()}" + (f" ({summary})" if summary else ""),
        payload=status, repo=repo,
        thread_key=f"github:{repo}#{pr_number}",
        lineage_root=f"github:{repo}#{pr_number}",
        state=state,
    )


def record_from_repository(connector_id: str, account_id: str,
                           repo_obj: dict[str, Any]) -> ConnectorRecord:
    full = repo_obj.get("full_name", "?")
    return _record(
        connector_id=connector_id, account_id=account_id,
        external_type="repository", external_id=full,
        external_revision=repo_obj.get("pushed_at")
        or repo_obj.get("updated_at") or "0",
        occurred_at=repo_obj.get("created_at"),
        content=f"Repository {full}: {_clip(repo_obj.get('description'))}\n"
                f"default branch: {repo_obj.get('default_branch')}"
                f" · private: {repo_obj.get('private')}",
        payload=repo_obj, repo=full,
        actors=_actors(repo_obj.get("owner")),
    )


def _issue_number_from_url(url: str) -> Optional[int]:
    if not url:
        return None
    tail = url.rstrip("/").split("/")[-1]
    # html_url for comments looks like .../pull/42#issuecomment-1
    tail = tail.split("#")[0]
    return int(tail) if tail.isdigit() else None
