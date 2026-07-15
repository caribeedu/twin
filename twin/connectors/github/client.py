"""Thin GitHub REST v3 client.

Deliberately small: authenticated GETs, Link-header pagination and rate-limit
translation into structured ``ConnectorError``s. REST (not GraphQL) because
every resource Phase 2 needs supports ``since``/``sort=updated`` natively and
the surface is trivial to mock offline.

Never logs URLs with parameters, bodies or the token — failures surface as
``ConnectorError`` and the framework sanitizes whatever it persists.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

import httpx

from ..models import FailureClass
from ..protocol import ConnectorError

GITHUB_API = "https://api.github.com"
PER_PAGE = 100
_LINK_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')


def _build_http(base_url: str, token: Optional[str]) -> httpx.Client:
    """Module-level factory so tests can swap in a MockTransport."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "twin-connector-github",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=base_url, headers=headers, timeout=30)


def _retry_after_seconds(resp: httpx.Response) -> int:
    retry = resp.headers.get("Retry-After")
    if retry and retry.isdigit():
        return int(retry)
    reset = resp.headers.get("X-RateLimit-Reset")
    if reset and reset.isdigit():
        return max(1, int(reset) - int(datetime.now(timezone.utc).timestamp()))
    return 60


class GitHubClient:
    def __init__(self, token: Optional[str], *,
                 base_url: str = GITHUB_API, http: Optional[httpx.Client] = None):
        self._http = http or _build_http(base_url, token)
        self.rate_limit_remaining: Optional[int] = None

    def close(self) -> None:
        self._http.close()

    def get(self, path: str, *, params: Optional[dict[str, Any]] = None,
            allow_404: bool = False) -> tuple[Any, httpx.Headers]:
        try:
            resp = self._http.get(path, params=params or {})
        except httpx.HTTPError as exc:
            raise ConnectorError(
                f"github network error: {type(exc).__name__}",
                failure_class=FailureClass.network, retryable=True,
            ) from exc

        remaining = resp.headers.get("X-RateLimit-Remaining")
        if remaining is not None and remaining.isdigit():
            self.rate_limit_remaining = int(remaining)

        if resp.status_code in (401,):
            raise ConnectorError(
                "github credential rejected",
                failure_class=FailureClass.authentication,
                human_action_required=True,
            )
        if resp.status_code in (403, 429) and (
            resp.headers.get("X-RateLimit-Remaining") == "0"
            or "rate limit" in resp.text.lower()
        ):
            raise ConnectorError(
                "github rate limit exhausted",
                failure_class=FailureClass.rate_limit,
                retryable=True,
                retry_after=_retry_after_seconds(resp),
            )
        if resp.status_code == 403:
            raise ConnectorError(
                "github access forbidden for this resource",
                failure_class=FailureClass.authorization,
                human_action_required=True,
            )
        if resp.status_code == 404:
            if allow_404:
                return None, resp.headers
            raise ConnectorError(
                "github resource not found",
                failure_class=FailureClass.provider_error,
            )
        if resp.status_code >= 500:
            raise ConnectorError(
                f"github server error ({resp.status_code})",
                failure_class=FailureClass.provider_error, retryable=True,
            )
        if resp.status_code >= 400:
            raise ConnectorError(
                f"github request rejected ({resp.status_code})",
                failure_class=FailureClass.provider_error,
            )
        try:
            return resp.json(), resp.headers
        except ValueError as exc:
            raise ConnectorError(
                "github returned a non-JSON body",
                failure_class=FailureClass.schema_change,
            ) from exc

    def paginate(self, path: str, *, params: Optional[dict[str, Any]] = None,
                 max_pages: int = 10) -> Iterator[list[Any]]:
        """Yield one JSON list per page, following the Link rel=next header
        up to ``max_pages`` — a single stream batch never tries to swallow a
        huge repository in one go (backpressure §53)."""
        query = {"per_page": PER_PAGE, **(params or {})}
        url: Optional[str] = path
        pages = 0
        while url is not None and pages < max_pages:
            data, headers = self.get(url, params=query if pages == 0 else None)
            if not isinstance(data, list):
                raise ConnectorError(
                    "github list endpoint returned a non-list payload",
                    failure_class=FailureClass.schema_change,
                )
            yield data
            pages += 1
            match = _LINK_NEXT.search(headers.get("Link", "") or "")
            url = match.group(1) if match else None

    def user(self) -> tuple[dict[str, Any], list[str]]:
        """Authenticated identity + granted scopes (classic PATs)."""
        data, headers = self.get("/user")
        scopes = [s.strip() for s in
                  (headers.get("X-OAuth-Scopes") or "").split(",") if s.strip()]
        return data, scopes
