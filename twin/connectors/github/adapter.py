"""GithubConnector — ProfessionalConnector adapter for GitHub (REST v3).

Streams are dynamic, one per (repository, object family):

    repo:{owner}/{name}:issues     issues + issue comments
    repo:{owner}/{name}:pulls      PRs + reviews + review comments + CI summary
    repo:{owner}/{name}:commits    default-branch commits
    repo:{owner}/{name}:releases

Incremental strategy (§23): per-substream pagination with continuation
cursors. A committed ``watermark`` advances only after every endpoint in
the family finishes the current lookback window — page budget exhausted
never means the stream is fully consumed.

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
from . import sync_state as ss

FAMILIES = ("issues", "pulls", "commits", "releases")
DEFAULT_LOOKBACK_SECONDS = 86400
DEFAULT_MAX_PAGES = 10
RECENT_RELEASES = 20
RECENT_COMMITS = 20
# Classic PAT scopes that grant write — fine-grained tokens may expose none.
CLASSIC_WRITE_SCOPES = {"write:org", "admin:org", "workflow", "delete_repo"}


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


def _max_ts(current: Optional[str], candidate: Optional[str]) -> Optional[str]:
    if not candidate:
        return current
    if not current or candidate > current:
        return candidate
    return current


def _commit_observed_at(commit: dict[str, Any]) -> Optional[str]:
    inner = commit.get("commit") or {}
    author = (inner.get("author") or {}).get("date")
    committer = (inner.get("committer") or {}).get("date")
    return _max_ts(author, committer)


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
        self._repo_meta: dict[str, dict[str, Any]] = {}

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
            dynamic_streams=True,
            default_scopes=["repo:read"],
        )

    # -- lifecycle ----------------------------------------------------------

    def discover_accounts(self) -> list[SourceAccount]:
        return [self.account]

    def _repo_default_branch(self, repo: str) -> str:
        if repo not in self._repo_meta:
            meta, _ = self.client.get(f"/repos/{repo}")
            self._repo_meta[repo] = meta or {}
        return str(self._repo_meta[repo].get("default_branch") or "main")

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
        login = user.get("login", "?")
        classic_write = sorted(set(scopes) & CLASSIC_WRITE_SCOPES)
        if classic_write:
            return ConnectorHealth(
                status=HealthStatus.degraded,
                detail=(f"authenticated as {login}; classic PAT grants write scopes "
                        f"{classic_write} — connector runs read-only GETs only; "
                        "use a least-privilege token"),
                scopes=scopes,
            )
        fine_grained = (self.secret or "").startswith("github_pat_") or not scopes
        if fine_grained:
            detail = (f"authenticated as {login} (fine-grained PAT; "
                      "X-OAuth-Scopes may be empty). Connector runs read-only "
                      "GETs only; credential privilege is unverified unless "
                      "GitHub exposes repository permissions.")
            if self.repositories:
                try:
                    meta, _ = self.client.get(f"/repos/{self.repositories[0]}")
                    perms = (meta or {}).get("permissions") or {}
                    if perms.get("push") or perms.get("admin"):
                        return ConnectorHealth(
                            status=HealthStatus.degraded,
                            detail=(f"authenticated as {login}; fine-grained token "
                                    "grants push/admin on "
                                    f"{self.repositories[0]} — use read-only "
                                    "repository permissions"),
                            scopes=scopes,
                        )
                except ConnectorError:
                    pass
            return ConnectorHealth(status=HealthStatus.healthy, detail=detail,
                                   scopes=scopes)
        if "repo" in scopes:
            return ConnectorHealth(
                status=HealthStatus.degraded,
                detail=(f"authenticated as {login}; classic PAT has broad `repo` "
                        "scope (often required for private repositories). "
                        "Connector runs read-only GETs only; privilege is not "
                        "read-only verified"),
                scopes=scopes,
            )
        return ConnectorHealth(status=HealthStatus.healthy,
                               detail=f"authenticated as {login}",
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
        if not self.repositories:
            raise ConnectorError(
                "no repositories configured",
                failure_class=FailureClass.configuration,
                human_action_required=True,
            )
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
        base = cursor or plan.cursor_before or {}
        window_since = self._since(
            {"watermark": base.get("watermark")} if ss.in_progress(base) else base
        )
        cur = ss.normalize_cursor(base, family=family, window_since=window_since)
        items: list[RawFetchItem] = []
        pages_budget = self.max_pages

        # One page budget = one FetchPage. done=False means the runtime must
        # commit a durable continuation cursor; done=True promotes watermark.
        while pages_budget > 0:
            sub = cur["substream"]
            batch_items, pages_used, sub_done = self._fetch_substream(
                repo, family, sub, cur, pages_budget,
            )
            items.extend(batch_items)
            pages_budget -= pages_used
            if pages_used == 0 and not sub_done:
                # defensive: avoid spinning if a substream made no progress
                return FetchPage(raw_items=items, cursor_after=cur, done=False)
            if not sub_done:
                return FetchPage(raw_items=items, cursor_after=cur, done=False)
            nxt = ss.next_substream(family, sub)
            if nxt:
                cur["substream"] = nxt
            else:
                return FetchPage(
                    raw_items=items,
                    cursor_after=ss.finalize_cursor(cur),
                    done=True,
                )
        return FetchPage(raw_items=items, cursor_after=cur, done=False)

    def _fetch_substream(
        self,
        repo: str,
        family: str,
        substream: str,
        cursor: dict[str, Any],
        pages_budget: int,
    ) -> tuple[list[RawFetchItem], int, bool]:
        handlers = {
            "issues": self._substream_issues,
            "issue_comments": self._substream_issue_comments,
            "pr_scan": self._substream_pr_scan,
            "pr_enrich": self._substream_pr_enrich,
            "pull_comments": self._substream_pull_comments,
            "commits_incremental": self._substream_commits_incremental,
            "commits_reconcile": self._substream_commits_reconcile,
            "releases": self._substream_releases,
        }
        handler = handlers.get(substream)
        if handler is None:
            raise ConnectorError(
                f"unknown substream {substream!r} for family {family!r}",
                failure_class=FailureClass.schema_change,
            )
        return handler(repo, cursor, pages_budget)

    def _since_params(self, cursor: dict[str, Any]) -> dict[str, Any]:
        since = cursor.get("window_since")
        return {"since": since} if since else {}

    def _substream_issues(
        self, repo: str, cursor: dict[str, Any], pages_budget: int,
    ) -> tuple[list[RawFetchItem], int, bool]:
        state = ss.substream_state(cursor, "issues")
        params = {"state": "all", "sort": "updated", "direction": "asc",
                  **self._since_params(cursor)}
        page_items, next_url, pages = self.client.fetch_page_batch(
            f"/repos/{repo}/issues",
            params=params,
            start_url=state.get("next_url"),
            max_pages=pages_budget,
        )
        state["next_url"] = next_url
        items: list[RawFetchItem] = []
        for issue in page_items:
            if issue.get("pull_request"):
                continue
            number = issue.get("number")
            ext_id = (f"{repo}#{number}" if number is not None
                      else f"{repo}#malformed-{_stable_hash8(issue)}")
            items.append(self._raw(repo, "issue", ext_id,
                                   issue.get("updated_at") or "0", issue))
            ss.bump_window_max(cursor, issue.get("updated_at"))
        return items, pages, next_url is None

    def _substream_issue_comments(
        self, repo: str, cursor: dict[str, Any], pages_budget: int,
    ) -> tuple[list[RawFetchItem], int, bool]:
        state = ss.substream_state(cursor, "issue_comments")
        params = {"sort": "updated", "direction": "asc",
                  **self._since_params(cursor)}
        page_items, next_url, pages = self.client.fetch_page_batch(
            f"/repos/{repo}/issues/comments",
            params=params,
            start_url=state.get("next_url"),
            max_pages=pages_budget,
        )
        state["next_url"] = next_url
        items: list[RawFetchItem] = []
        for comment in page_items:
            if "/pull/" in (comment.get("html_url") or ""):
                continue
            items.append(self._raw(repo, "issue_comment", str(comment["id"]),
                                   comment.get("updated_at") or "0", comment))
            ss.bump_window_max(cursor, comment.get("updated_at"))
        return items, pages, next_url is None

    def _substream_pr_scan(
        self, repo: str, cursor: dict[str, Any], pages_budget: int,
    ) -> tuple[list[RawFetchItem], int, bool]:
        state = ss.substream_state(cursor, "pr_scan")
        enrich = ss.substream_state(cursor, "pr_enrich")
        queue: list[int] = enrich.setdefault("queue", [])
        seen: set[int] = set(enrich.setdefault("seen", []))
        params = {"state": "all", "sort": "updated", "direction": "asc",
                  **self._since_params(cursor)}
        page_items, next_url, pages = self.client.fetch_page_batch(
            f"/repos/{repo}/issues",
            params=params,
            start_url=state.get("next_url"),
            max_pages=pages_budget,
        )
        state["next_url"] = next_url
        for issue in page_items:
            if not issue.get("pull_request"):
                continue
            number = int(issue["number"])
            if number not in seen:
                seen.add(number)
                queue.append(number)
            ss.bump_window_max(cursor, issue.get("updated_at"))
        enrich["seen"] = sorted(seen)
        return [], pages, next_url is None

    def _substream_pr_enrich(
        self, repo: str, cursor: dict[str, Any], pages_budget: int,
    ) -> tuple[list[RawFetchItem], int, bool]:
        state = ss.substream_state(cursor, "pr_enrich")
        queue: list[int] = state.get("queue") or []
        idx = int(state.get("idx", 0))
        items: list[RawFetchItem] = []
        pages_used = 0

        if state.get("reviews_next_url"):
            pr_num = int(state["current_pr"])
            reviews, next_url, pages = self.client.fetch_page_batch(
                f"/repos/{repo}/pulls/{pr_num}/reviews",
                start_url=state["reviews_next_url"],
                max_pages=pages_budget,
            )
            pages_used += pages
            for review in reviews:
                items.append(self._raw(
                    repo, "review", str(review["id"]),
                    norm.revision_for_review(review),
                    review, pr_number=pr_num))
                ss.bump_window_max(cursor, review.get("submitted_at"))
            state["reviews_next_url"] = next_url
            if next_url:
                return items, pages_used, False
            state.pop("reviews_next_url", None)
            state.pop("current_pr", None)
            state.pop("awaiting_reviews", None)
            state["idx"] = idx + 1
            idx += 1

        while idx < len(queue) and pages_used < pages_budget:
            pr_num = queue[idx]
            if not state.get("awaiting_reviews"):
                pr, _ = self.client.get(f"/repos/{repo}/pulls/{pr_num}")
                pages_used += 1
                items.append(self._raw(repo, "pull_request", f"{repo}#{pr_num}",
                                       pr.get("updated_at") or "0", pr,
                                       pr_number=pr_num))
                ss.bump_window_max(cursor, pr.get("updated_at"))
                head_sha = (pr.get("head") or {}).get("sha")
                if head_sha and pages_used < pages_budget:
                    status, _ = self.client.get(
                        f"/repos/{repo}/commits/{head_sha}/status", allow_404=True)
                    pages_used += 1
                    if status and (status.get("statuses") or []):
                        items.append(self._raw(
                            repo, "check_summary", f"{repo}@{head_sha}",
                            norm.revision_for_check_summary(status), status,
                            pr_number=pr_num, head_sha=head_sha))
                if pages_used >= pages_budget:
                    state["current_pr"] = pr_num
                    state["idx"] = idx
                    state["awaiting_reviews"] = True
                    return items, pages_used, False
            state.pop("awaiting_reviews", None)
            reviews, next_url, pages = self.client.fetch_page_batch(
                f"/repos/{repo}/pulls/{pr_num}/reviews",
                max_pages=pages_budget - pages_used,
            )
            pages_used += pages
            for review in reviews:
                items.append(self._raw(
                    repo, "review", str(review["id"]),
                    norm.revision_for_review(review),
                    review, pr_number=pr_num))
                ss.bump_window_max(cursor, review.get("submitted_at"))
            if next_url:
                state["reviews_next_url"] = next_url
                state["current_pr"] = pr_num
                state["idx"] = idx
                return items, pages_used, False
            idx += 1
            state["idx"] = idx

        done = idx >= len(queue) and not state.get("reviews_next_url")
        return items, pages_used, done

    def _substream_pull_comments(
        self, repo: str, cursor: dict[str, Any], pages_budget: int,
    ) -> tuple[list[RawFetchItem], int, bool]:
        state = ss.substream_state(cursor, "pull_comments")
        params = {"sort": "updated", "direction": "asc",
                  **self._since_params(cursor)}
        page_items, next_url, pages = self.client.fetch_page_batch(
            f"/repos/{repo}/pulls/comments",
            params=params,
            start_url=state.get("next_url"),
            max_pages=pages_budget,
        )
        state["next_url"] = next_url
        items: list[RawFetchItem] = []
        for comment in page_items:
            items.append(self._raw(repo, "review_comment", str(comment["id"]),
                                   comment.get("updated_at") or "0", comment))
            ss.bump_window_max(cursor, comment.get("updated_at"))
        return items, pages, next_url is None

    def _substream_commits_incremental(
        self, repo: str, cursor: dict[str, Any], pages_budget: int,
    ) -> tuple[list[RawFetchItem], int, bool]:
        state = ss.substream_state(cursor, "commits_incremental")
        branch = self._repo_default_branch(repo)
        params = dict(self._since_params(cursor))
        page_items, next_url, pages = self.client.fetch_page_batch(
            f"/repos/{repo}/commits",
            params=params,
            start_url=state.get("next_url"),
            max_pages=pages_budget,
        )
        state["next_url"] = next_url
        items: list[RawFetchItem] = []
        for commit in page_items:
            obj = dict(commit)
            obj["_branch_scope"] = branch
            items.append(self._raw(repo, "commit", commit["sha"],
                                   commit["sha"], obj))
            ss.bump_window_max(cursor, _commit_observed_at(commit))
        return items, pages, next_url is None

    def _substream_commits_reconcile(
        self, repo: str, cursor: dict[str, Any], pages_budget: int,
    ) -> tuple[list[RawFetchItem], int, bool]:
        branch = self._repo_default_branch(repo)
        page_items, _, pages = self.client.fetch_page_batch(
            f"/repos/{repo}/commits",
            max_pages=min(1, pages_budget),
        )
        items: list[RawFetchItem] = []
        for commit in page_items[:RECENT_COMMITS]:
            obj = dict(commit)
            obj["_branch_scope"] = branch
            items.append(self._raw(repo, "commit", commit["sha"],
                                   commit["sha"], obj))
            ss.bump_window_max(cursor, _commit_observed_at(commit))
        return items, pages, True

    def _substream_releases(
        self, repo: str, cursor: dict[str, Any], pages_budget: int,
    ) -> tuple[list[RawFetchItem], int, bool]:
        state = ss.substream_state(cursor, "releases")
        since = cursor.get("window_since")
        offset = int(state.get("offset", 0))
        page_items, next_url, pages = self.client.fetch_page_batch(
            f"/repos/{repo}/releases",
            start_url=state.get("next_url"),
            max_pages=pages_budget,
        )
        state["next_url"] = next_url
        items: list[RawFetchItem] = []
        for i, release in enumerate(page_items):
            global_idx = offset + i
            published = release.get("published_at") or release.get("created_at")
            include = (
                global_idx < RECENT_RELEASES
                or not since
                or (published and published > since)
            )
            if not include:
                continue
            revision = norm.revision_for_release(release)
            items.append(self._raw(repo, "release", str(release["id"]),
                                   revision, release))
            ss.bump_window_max(cursor, published)
        state["offset"] = offset + len(page_items)
        return items, pages, next_url is None

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
                         or obj.get("published_at")
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
        rec.external_type = raw_item.external_type
        rec.external_id = raw_item.external_id
        rec.external_revision = raw_item.external_revision
        return [rec]

    def acknowledge(self, plan: SyncPlan, page: FetchPage) -> dict[str, Any]:
        return page.cursor_after or dict(plan.cursor_before or {})
