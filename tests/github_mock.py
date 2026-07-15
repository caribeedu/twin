"""Offline GitHub REST v3 double for the connector contract suite.

Serves the same semantics the adapter depends on — ``since`` filtering,
``sort=updated``, Link-header pagination, rate-limit headers, 401/403 —
from in-memory fixtures. No test ever touches the network.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import httpx

PER_PAGE_DEFAULT = 100


def _user(login: str, *, bot: bool = False) -> dict[str, Any]:
    return {"login": login, "id": abs(hash(login)) % 10_000,
            "type": "Bot" if bot else "User"}


class FakeGitHubAPI:
    def __init__(self):
        self.authed_user = _user("edu")
        self.scopes = "read:user"
        self.valid_token: Optional[str] = "gh-test-token"
        self.repos: dict[str, dict[str, Any]] = {}
        self.rate_limited = False
        self.rate_limit_reset_in = 900
        self.server_error_paths: set[str] = set()
        self.requests: list[str] = []

    # -- fixture builders ---------------------------------------------------

    def add_repo(self, full_name: str, *, private: bool = True,
                 default_branch: str = "main") -> None:
        self.repos[full_name] = {
            "meta": {"full_name": full_name, "private": private,
                     "default_branch": default_branch, "open_issues_count": 0,
                     "pushed_at": "2026-01-01T00:00:00Z", "size": 128,
                     "owner": _user(full_name.split("/")[0]),
                     "permissions": {"pull": True, "push": False, "admin": False}},
            "issues": {},          # number → issue obj (PRs mirrored here too)
            "pulls": {},           # number → pull obj
            "issue_comments": [],
            "pull_comments": [],
            "reviews": {},         # pr number → [review]
            "commits": [],
            "releases": [],
            "statuses": {},        # sha → combined status
        }

    def add_issue(self, repo: str, number: int, *, title: str, body: str = "",
                  updated_at: str, state: str = "open",
                  user: Optional[dict] = None, **extra) -> dict[str, Any]:
        issue = {
            "number": number, "title": title, "body": body, "state": state,
            "created_at": updated_at, "updated_at": updated_at,
            "user": user or _user("alice"), "labels": [], "assignees": [],
            "html_url": f"https://github.com/{repo}/issues/{number}",
            "url": f"https://api.github.com/repos/{repo}/issues/{number}",
            **extra,
        }
        self.repos[repo]["issues"][number] = issue
        return issue

    def add_pull(self, repo: str, number: int, *, title: str, body: str = "",
                 updated_at: str, state: str = "open", merged: bool = False,
                 head_sha: str = "", user: Optional[dict] = None) -> dict[str, Any]:
        pull = {
            "number": number, "title": title, "body": body,
            "state": "closed" if merged else state,
            "merged": merged,
            "merged_at": updated_at if merged else None,
            "created_at": updated_at, "updated_at": updated_at,
            "user": user or _user("alice"),
            "assignees": [], "requested_reviewers": [],
            "base": {"ref": "main"}, "head": {"ref": "feature",
                                              "sha": head_sha or f"sha{number}"},
            "html_url": f"https://github.com/{repo}/pull/{number}",
            "url": f"https://api.github.com/repos/{repo}/pulls/{number}",
        }
        # PRs surface in the issues listing with a pull_request marker.
        # Same object in both maps so test mutations stay visible everywhere,
        # exactly like the live API.
        pull["pull_request"] = {"url": pull["url"]}
        self.repos[repo]["pulls"][number] = pull
        self.repos[repo]["issues"][number] = pull
        return pull

    def add_issue_comment(self, repo: str, comment_id: int, issue_number: int, *,
                          body: str, updated_at: str,
                          user: Optional[dict] = None) -> dict[str, Any]:
        comment = {
            "id": comment_id, "body": body,
            "created_at": updated_at, "updated_at": updated_at,
            "user": user or _user("bob"),
            "issue_url": f"https://api.github.com/repos/{repo}/issues/{issue_number}",
            "html_url": f"https://github.com/{repo}/issues/{issue_number}"
                        f"#issuecomment-{comment_id}",
        }
        self.repos[repo]["issue_comments"].append(comment)
        return comment

    def add_review(self, repo: str, pr_number: int, review_id: int, *,
                   state: str, body: str = "",
                   user: Optional[dict] = None,
                   submitted_at: str = "2026-01-02T00:00:00Z") -> dict[str, Any]:
        review = {
            "id": review_id, "state": state, "body": body,
            "submitted_at": submitted_at, "user": user or _user("carol"),
            "html_url": f"https://github.com/{repo}/pull/{pr_number}"
                        f"#pullrequestreview-{review_id}",
        }
        self.repos[repo]["reviews"].setdefault(pr_number, []).append(review)
        return review

    def add_review_comment(self, repo: str, comment_id: int, pr_number: int, *,
                           body: str, updated_at: str, path: str = "app.py",
                           user: Optional[dict] = None) -> dict[str, Any]:
        comment = {
            "id": comment_id, "body": body, "path": path,
            "created_at": updated_at, "updated_at": updated_at,
            "user": user or _user("carol"),
            "pull_request_url":
                f"https://api.github.com/repos/{repo}/pulls/{pr_number}",
            "html_url": f"https://github.com/{repo}/pull/{pr_number}"
                        f"#discussion_r{comment_id}",
        }
        self.repos[repo]["pull_comments"].append(comment)
        return comment

    def add_commit(self, repo: str, sha: str, *, message: str, date: str,
                   author_login: str = "alice") -> dict[str, Any]:
        commit = {
            "sha": sha,
            "commit": {"message": message,
                       "author": {"name": author_login, "date": date}},
            "author": _user(author_login),
            "html_url": f"https://github.com/{repo}/commit/{sha}",
        }
        self.repos[repo]["commits"].append(commit)
        return commit

    def set_status(self, repo: str, sha: str, *, state: str,
                   contexts: Optional[list[dict]] = None) -> None:
        self.repos[repo]["statuses"][sha] = {
            "state": state,
            "statuses": contexts or [{"context": "ci/test", "state": state}],
        }

    # -- transport ------------------------------------------------------------

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def _json(self, data: Any, *, headers: Optional[dict[str, str]] = None,
              status: int = 200) -> httpx.Response:
        base = {"X-RateLimit-Remaining": "5000"}
        base.update(headers or {})
        return httpx.Response(status, json=data, headers=base)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        path = url.path
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.requests.append(path)

        auth = request.headers.get("Authorization", "")
        if self.valid_token is not None and auth != f"Bearer {self.valid_token}":
            return self._json({"message": "Bad credentials"}, status=401)
        if self.rate_limited:
            return httpx.Response(403, json={"message": "API rate limit exceeded"},
                                  headers={"X-RateLimit-Remaining": "0",
                                           "Retry-After": str(self.rate_limit_reset_in)})
        if path in self.server_error_paths:
            return self._json({"message": "boom"}, status=502)

        if path == "/user":
            return self._json(self.authed_user,
                              headers={"X-OAuth-Scopes": self.scopes})
        if path == "/user/repos":
            return self._paged([r["meta"] for r in self.repos.values()],
                               request, params)

        m = re.match(r"^/repos/([^/]+/[^/]+)(/.*)?$", path)
        if not m:
            return self._json({"message": "Not Found"}, status=404)
        repo, rest = m.group(1), m.group(2) or ""
        data = self.repos.get(repo)
        if data is None:
            return self._json({"message": "Not Found"}, status=404)

        if rest == "":
            return self._json(data["meta"])
        if rest == "/issues":
            items = sorted(data["issues"].values(),
                           key=lambda i: i.get("updated_at", ""))
            items = _since_filter(items, params.get("since"), "updated_at")
            return self._paged(items, request, params)
        if rest == "/issues/comments":
            items = sorted(data["issue_comments"],
                           key=lambda c: c.get("updated_at", ""))
            items = _since_filter(items, params.get("since"), "updated_at")
            return self._paged(items, request, params)
        if rest == "/pulls/comments":
            items = sorted(data["pull_comments"],
                           key=lambda c: c.get("updated_at", ""))
            items = _since_filter(items, params.get("since"), "updated_at")
            return self._paged(items, request, params)
        pr_match = re.match(r"^/pulls/(\d+)$", rest)
        if pr_match:
            pull = data["pulls"].get(int(pr_match.group(1)))
            return self._json(pull) if pull else self._json({}, status=404)
        rv_match = re.match(r"^/pulls/(\d+)/reviews$", rest)
        if rv_match:
            pr = int(rv_match.group(1))
            items = data["reviews"].get(pr, [])
            return self._paged(items, request, params)
        if rest == "/commits":
            items = sorted(data["commits"],
                           key=lambda c: c["commit"]["author"]["date"])
            items = _since_filter(items, params.get("since"),
                                  lambda c: c["commit"]["author"]["date"])
            return self._paged(items, request, params)
        st_match = re.match(r"^/commits/([^/]+)/status$", rest)
        if st_match:
            status = data["statuses"].get(st_match.group(1))
            if status is None:
                return self._json({"state": "pending", "statuses": []})
            return self._json(status)
        if rest == "/releases":
            return self._paged(data["releases"], request, params)
        return self._json({"message": "Not Found"}, status=404)

    def _paged(self, items: list, request: httpx.Request,
               params: dict[str, str]) -> httpx.Response:
        per_page = int(params.get("per_page", PER_PAGE_DEFAULT))
        page = int(params.get("page", 1))
        start = (page - 1) * per_page
        window = items[start:start + per_page]
        headers: dict[str, str] = {}
        if start + per_page < len(items):
            nxt = str(request.url.copy_set_param("page", str(page + 1)))
            headers["Link"] = f'<{nxt}>; rel="next"'
        return self._json(window, headers=headers)


def _since_filter(items: list, since: Optional[str], key) -> list:
    if not since:
        return items
    getter = key if callable(key) else (lambda item: item.get(key, ""))
    return [item for item in items if (getter(item) or "") > since]


def json_roundtrip(obj: Any) -> Any:
    """Force plain-JSON types, mimicking the wire."""
    return json.loads(json.dumps(obj))
