"""GithubConnector — ProfessionalConnector adapter for GitHub (REST v3).

Streams are dynamic, one per (repository, object family):

    repo:{owner}/{name}:issues     issues + issue comments
    repo:{owner}/{name}:pulls      PRs + reviews + review comments + CI summary
    repo:{owner}/{name}:commits    default-branch commits
    repo:{owner}/{name}:releases

Incremental strategy (§23): ``updated_at`` watermark per stream + fixed
lookback window re-fetched every cycle. The framework dedupes the overlap by
revision, so the lookback costs requests, never duplicate Percepts.
Repositories are an EXPLICIT allowlist in the instance configuration —
"everything the token can reach" is never a default.

The adapter never decides what becomes memory: it fetches, wraps context
(repo, PR number) around the provider payload and normalizes. Deletions are
not observable through REST polling, and the manifest says so
(``deletions: false``) instead of pretending.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..models import (
    ConnectorCheckpoint,
    ConnectorInstance,
    ConnectorRecord,
    FailureClass,
    HealthStatus,
    RawConnectorItem,
    SourceAccount,
)
from ..protocol import (
    AdapterManifest,
    ConnectorError,
    ConnectorHealth,
    FetchPage,
    RawFetchItem,
    SyncPlan,
)
from ..registry import register_adapter
from .client import GITHUB_API, GitHubClient
from . import normalize as norm

FAMILIES = ("issues", "pulls", "commits", "releases")
DEFAULT_LOOKBACK_SECONDS = 86400
DEFAULT_MAX_PAGES = 10
# read-only scopes only — v0.6 perceives, it never acts (§10)
WRITE_SCOPES = {"repo", "write:org", "admin:org", "workflow", "delete_repo"}


def _parse_stream(stream: str) -> tuple[str, str]:
    """'repo:{owner}/{name}:{family}' → (repo, family)."""
    parts = stream.split(":")
    if len(parts) != 3 or parts[0] != "repo" or parts[2] not in FAMILIES:
        raise ConnectorError(
            f"unknown github stream layout: {stream!r}",
            failure_class=FailureClass.schema_change,
        )
    return parts[1], parts[2]


def _minus_seconds(iso_ts: str, seconds: int) -> str:
    ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    out = ts - timedelta(seconds=seconds)
    return out.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stable_hash8(obj: Any) -> str:
    """Deterministic key for objects lacking a natural id — a retried fetch
    must map the same malformed payload to the same dead letter."""
    canonical = json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]


@register_adapter
class GithubConnector:
    connector_type = "github"

    def __init__(
        self,
        instance: ConnectorInstance,
        account: SourceAccount,
        secret: Optional[str],
    ) -> None:
        self.instance = instance
        self.account = account
        self.secret = secret
        cfg = instance.configuration or {}
        self.repositories: list[str] = list(cfg.get("repositories") or [])
        self.lookback_seconds = int(cfg.get("lookback_seconds",
                                            DEFAULT_LOOKBACK_SECONDS))
        self.backfill_since: Optional[str] = cfg.get("backfill_since")
        self.max_pages = int(cfg.get("max_pages_per_stream", DEFAULT_MAX_PAGES))
        self.api_base_url: str = cfg.get("api_base_url", GITHUB_API)
        self._client: Optional[GitHubClient] = None

    # -- plumbing -----------------------------------------------------------

    @property
    def client(self) -> GitHubClient:
        if self._client is None:
            self._client = GitHubClient(self.secret, base_url=self.api_base_url)
        return self._client

    @staticmethod
    def adapter_manifest() -> AdapterManifest:
        return AdapterManifest(
            connector_type="github",
            adapter_version="1.0",
            schema_version=1,
            auth_mode="personal_access_token",
            affordances={
                "incremental_sync": True,
                "webhooks": True,       # accepted as a targeted-sync hint only
                "deletions": False,     # not observable via REST polling — honest
                "attachments": False,
                "threads": True,
            },
            supported_external_types=[
                "repository", "issue", "issue_comment", "pull_request",
                "review", "review_comment", "commit", "release", "check_summary",
            ],
            streams=[],                 # dynamic: plan_streams()
            default_scopes=["repo:read"],
        )

    # -- lifecycle ----------------------------------------------------------

    def discover_accounts(self) -> list[SourceAccount]:
        return [self.account]

    def list_repositories(self) -> list[dict[str, Any]]:
        """Provider-specific helper for the setup surfaces: repositories the
        token can reach, with rough volume signals for the backfill preview."""
        out: list[dict[str, Any]] = []
        for page in self.client.paginate(
            "/user/repos", params={"sort": "pushed", "direction": "desc"},
            max_pages=self.max_pages,
        ):
            for repo in page:
                out.append({
                    "full_name": repo.get("full_name"),
                    "private": repo.get("private"),
                    "default_branch": repo.get("default_branch"),
                    "open_issues": repo.get("open_issues_count"),
                    "pushed_at": repo.get("pushed_at"),
                    "size_kb": repo.get("size"),
                })
        return out

    def estimate_backfill(self) -> dict[str, dict[str, Any]]:
        """Rough per-stream volume signals for the backfill preview — reads
        only repository metadata, never object listings, never ingests."""
        out: dict[str, dict[str, Any]] = {}
        for repo in self.repositories:
            try:
                meta, _ = self.client.get(f"/repos/{repo}")
            except ConnectorError as exc:
                meta = {"error": exc.failure_class.value}
            meta = meta or {}
            signal = {
                "open_issues": meta.get("open_issues_count"),
                "pushed_at": meta.get("pushed_at"),
                "size_kb": meta.get("size"),
                "private": meta.get("private"),
            }
            if "error" in meta:
                signal = {"error": meta["error"]}
            for family in FAMILIES:
                out[f"repo:{repo}:{family}"] = signal
        return out

    def validate_credentials(self) -> ConnectorHealth:
        if not self.secret:
            return ConnectorHealth(status=HealthStatus.unauthorized,
                                   detail="no credential configured")
        try:
            user, scopes = self.client.user()
        except ConnectorError as exc:
            if exc.failure_class == FailureClass.authentication:
                return ConnectorHealth(status=HealthStatus.unauthorized,
                                       detail="token rejected by github")
            return ConnectorHealth(status=HealthStatus.degraded,
                                   detail=f"github unreachable: {exc.failure_class.value}")
        excessive = sorted(set(scopes) & WRITE_SCOPES)
        if excessive:
            return ConnectorHealth(
                status=HealthStatus.degraded,
                detail=(f"authenticated as {user.get('login')} but token grants "
                        f"write scopes {excessive} — v0.6 is read-only, use a "
                        "least-privilege token"),
                scopes=scopes,
            )
        return ConnectorHealth(status=HealthStatus.healthy,
                               detail=f"authenticated as {user.get('login')}",
                               scopes=scopes)

    def plan_streams(self, account: SourceAccount) -> list[str]:
        return [f"repo:{repo}:{family}"
                for repo in self.repositories for family in FAMILIES]

    def plan_sync(
        self,
        account: SourceAccount,
        checkpoint: Optional[ConnectorCheckpoint],
        *,
        stream: str,
    ) -> SyncPlan:
        repo, family = _parse_stream(stream)
        return SyncPlan(
            stream=stream,
            cursor_before=dict(checkpoint.cursor) if checkpoint else {},
            lookback_seconds=self.lookback_seconds,
            metadata={"repo": repo, "family": family},
        )

    # -- fetch ----------------------------------------------------------------

    def _since(self, cursor: Optional[dict[str, Any]]) -> Optional[str]:
        watermark = (cursor or {}).get("watermark")
        if watermark:
            return _minus_seconds(watermark, self.lookback_seconds)
        return self.backfill_since  # None = full history (explicit choice)

    def fetch_batch(
        self, plan: SyncPlan, cursor: Optional[dict[str, Any]],
    ) -> FetchPage:
        repo = plan.metadata["repo"]
        family = plan.metadata["family"]
        since = self._since(cursor or plan.cursor_before)
        fetch = getattr(self, f"_fetch_{family}")
        items, max_seen = fetch(repo, since)
        previous = (cursor or plan.cursor_before or {}).get("watermark")
        watermark = max(filter(None, [previous, max_seen]), default=None)
        cursor_after = {"watermark": watermark} if watermark else {}
        return FetchPage(raw_items=items, cursor_after=cursor_after, done=True)

    def _fetch_issues(self, repo: str,
                      since: Optional[str]) -> tuple[list[RawFetchItem], Optional[str]]:
        items: list[RawFetchItem] = []
        max_seen: Optional[str] = None
        params = {"state": "all", "sort": "updated", "direction": "asc"}
        if since:
            params["since"] = since
        for page in self.client.paginate(f"/repos/{repo}/issues", params=params,
                                         max_pages=self.max_pages):
            for issue in page:
                if issue.get("pull_request"):
                    continue  # PRs belong to the pulls stream (authoritative fetch)
                # malformed objects still enter the pipeline so normalization
                # dead-letters them individually — the fetch never crashes a
                # whole stream over one broken item (deterministic key so a
                # retry meets the same dead letter, not a new one)
                number = issue.get("number")
                ext_id = (f"{repo}#{number}" if number is not None
                          else f"{repo}#malformed-{_stable_hash8(issue)}")
                items.append(self._raw(repo, "issue", ext_id,
                                       issue.get("updated_at") or "0", issue))
                max_seen = _max_ts(max_seen, issue.get("updated_at"))
        cparams = {"sort": "updated", "direction": "asc"}
        if since:
            cparams["since"] = since
        for page in self.client.paginate(f"/repos/{repo}/issues/comments",
                                         params=cparams, max_pages=self.max_pages):
            for comment in page:
                if "/pull/" in (comment.get("html_url") or ""):
                    continue  # PR conversation comments ride with the pulls stream
                items.append(self._raw(repo, "issue_comment", str(comment["id"]),
                                       comment.get("updated_at") or "0", comment))
                max_seen = _max_ts(max_seen, comment.get("updated_at"))
        return items, max_seen

    def _fetch_pulls(self, repo: str,
                     since: Optional[str]) -> tuple[list[RawFetchItem], Optional[str]]:
        items: list[RawFetchItem] = []
        max_seen: Optional[str] = None
        params = {"state": "all", "sort": "updated", "direction": "asc"}
        if since:
            params["since"] = since
        # the issues listing (which supports `since`) DETECTS updated PRs;
        # each one is then re-fetched from /pulls as the authoritative object
        for page in self.client.paginate(f"/repos/{repo}/issues", params=params,
                                         max_pages=self.max_pages):
            for issue in page:
                if not issue.get("pull_request"):
                    continue
                number = issue["number"]
                pr, _ = self.client.get(f"/repos/{repo}/pulls/{number}")
                items.append(self._raw(repo, "pull_request", f"{repo}#{number}",
                                       pr.get("updated_at") or "0", pr,
                                       pr_number=number))
                max_seen = _max_ts(max_seen, pr.get("updated_at"))
                reviews, _ = self.client.get(f"/repos/{repo}/pulls/{number}/reviews")
                for review in reviews or []:
                    items.append(self._raw(
                        repo, "review", str(review["id"]),
                        norm.revision_for_review(review),
                        review, pr_number=number))
                head_sha = (pr.get("head") or {}).get("sha")
                if head_sha:
                    status, _ = self.client.get(
                        f"/repos/{repo}/commits/{head_sha}/status", allow_404=True)
                    if status and (status.get("statuses") or []):
                        items.append(self._raw(
                            repo, "check_summary", f"{repo}@{head_sha}",
                            norm.revision_for_check_summary(status), status,
                            pr_number=number, head_sha=head_sha))
        cparams = {"sort": "updated", "direction": "asc"}
        if since:
            cparams["since"] = since
        for page in self.client.paginate(f"/repos/{repo}/pulls/comments",
                                         params=cparams, max_pages=self.max_pages):
            for comment in page:
                items.append(self._raw(repo, "review_comment", str(comment["id"]),
                                       comment.get("updated_at") or "0", comment))
                max_seen = _max_ts(max_seen, comment.get("updated_at"))
        return items, max_seen

    def _fetch_commits(self, repo: str,
                       since: Optional[str]) -> tuple[list[RawFetchItem], Optional[str]]:
        items: list[RawFetchItem] = []
        max_seen: Optional[str] = None
        params: dict[str, Any] = {}
        if since:
            params["since"] = since
        for page in self.client.paginate(f"/repos/{repo}/commits", params=params,
                                         max_pages=self.max_pages):
            for commit in page:
                date = ((commit.get("commit") or {}).get("author") or {}).get("date")
                items.append(self._raw(repo, "commit", commit["sha"],
                                       commit["sha"], commit))
                max_seen = _max_ts(max_seen, date)
        return items, max_seen

    def _fetch_releases(self, repo: str,
                        since: Optional[str]) -> tuple[list[RawFetchItem], Optional[str]]:
        items: list[RawFetchItem] = []
        max_seen: Optional[str] = None
        for page in self.client.paginate(f"/repos/{repo}/releases",
                                         max_pages=self.max_pages):
            for release in page:
                published = release.get("published_at") or release.get("created_at")
                if since and published and published <= since:
                    continue  # no `since` support server-side — filter here
                items.append(self._raw(repo, "release", str(release["id"]),
                                       published or "0", release))
                max_seen = _max_ts(max_seen, published)
        return items, max_seen

    def _raw(self, repo: str, external_type: str, external_id: str,
             revision: str, obj: dict[str, Any], *,
             pr_number: Optional[int] = None,
             head_sha: Optional[str] = None) -> RawFetchItem:
        payload: dict[str, Any] = {"repo": repo, "object": obj}
        if pr_number is not None:
            payload["pr_number"] = pr_number
        if head_sha is not None:
            payload["head_sha"] = head_sha
        return RawFetchItem(
            external_type=external_type,
            external_id=external_id,
            external_revision=str(revision),
            payload=payload,
            occurred_at=(obj.get("created_at") or obj.get("submitted_at")
                         or ((obj.get("commit") or {}).get("author") or {}).get("date")),
        )

    # -- normalize -------------------------------------------------------------

    def normalize(self, raw_item: RawConnectorItem) -> list[ConnectorRecord]:
        payload = raw_item.payload or {}
        repo = payload.get("repo")
        obj = payload.get("object")
        if not repo or not isinstance(obj, dict):
            raise ConnectorError(
                "github raw item missing repo/object envelope",
                failure_class=FailureClass.schema_change,
                external_id=raw_item.external_id,
                external_type=raw_item.external_type,
            )
        kind = raw_item.external_type
        cid, aid = raw_item.connector_id, raw_item.source_account_id
        if kind == "issue":
            rec = norm.record_from_issue(cid, aid, repo, obj)
        elif kind == "issue_comment":
            rec = norm.record_from_issue_comment(cid, aid, repo, obj)
        elif kind == "pull_request":
            rec = norm.record_from_pull_request(cid, aid, repo, obj)
        elif kind == "review":
            rec = norm.record_from_review(cid, aid, repo,
                                          int(payload.get("pr_number") or 0), obj)
        elif kind == "review_comment":
            rec = norm.record_from_review_comment(cid, aid, repo, obj)
        elif kind == "commit":
            rec = norm.record_from_commit(cid, aid, repo, obj)
        elif kind == "release":
            rec = norm.record_from_release(cid, aid, repo, obj)
        elif kind == "check_summary":
            rec = norm.record_from_check_summary(
                cid, aid, repo, int(payload.get("pr_number") or 0),
                str(payload.get("head_sha") or ""), obj)
        elif kind == "repository":
            rec = norm.record_from_repository(cid, aid, obj)
        else:
            raise ConnectorError(
                f"unsupported github object type {kind!r}",
                failure_class=FailureClass.schema_change,
                external_id=raw_item.external_id, external_type=kind,
            )
        # the raw item is the single source of truth for identity/revision
        rec.external_type = raw_item.external_type
        rec.external_id = raw_item.external_id
        rec.external_revision = raw_item.external_revision
        return [rec]

    def acknowledge(self, plan: SyncPlan, page: FetchPage) -> dict[str, Any]:
        return page.cursor_after or dict(plan.cursor_before or {})


def _max_ts(current: Optional[str], candidate: Optional[str]) -> Optional[str]:
    if not candidate:
        return current
    if not current or candidate > current:
        return candidate
    return current
