"""Thin Slack Web API client.

Authenticated GETs/POSTs for the Conversations API, cursor pagination and
rate-limit translation into structured ``ConnectorError``s. Never logs
tokens or message bodies.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from ..models import FailureClass
from ..protocol import ConnectorError

SLACK_API = "https://slack.com/api"
DEFAULT_LIMIT = 200


def _build_http(base_url: str, token: Optional[str]) -> httpx.Client:
    headers = {
        "Accept": "application/json",
        "User-Agent": "twin-connector-slack",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    # trailing slash so method names join under /api/ instead of replacing it
    root = base_url if base_url.endswith("/") else base_url + "/"
    return httpx.Client(base_url=root, headers=headers, timeout=30)


class SlackClient:
    def __init__(self, token: Optional[str], *,
                 base_url: str = SLACK_API, http: Optional[httpx.Client] = None):
        self._http = http or _build_http(base_url, token)

    def close(self) -> None:
        self._http.close()

    def call(self, method: str, *, params: Optional[dict[str, Any]] = None,
             allow_not_found: bool = False) -> dict[str, Any]:
        try:
            resp = self._http.get(method, params=params or {})
        except httpx.HTTPError as exc:
            raise ConnectorError(
                f"slack network error: {type(exc).__name__}",
                failure_class=FailureClass.network, retryable=True,
            ) from exc

        if resp.status_code == 429:
            retry = resp.headers.get("Retry-After", "60")
            raise ConnectorError(
                "slack rate limit exhausted",
                failure_class=FailureClass.rate_limit,
                retryable=True,
                retry_after=int(retry) if str(retry).isdigit() else 60,
            )
        if resp.status_code == 401:
            raise ConnectorError(
                "slack credential rejected",
                failure_class=FailureClass.authentication,
                human_action_required=True,
            )
        if resp.status_code >= 500:
            raise ConnectorError(
                f"slack server error ({resp.status_code})",
                failure_class=FailureClass.provider_error, retryable=True,
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise ConnectorError(
                "slack returned a non-JSON body",
                failure_class=FailureClass.schema_change,
            ) from exc
        if not isinstance(data, dict):
            raise ConnectorError(
                "slack returned a non-object payload",
                failure_class=FailureClass.schema_change,
            )
        if not data.get("ok"):
            err = str(data.get("error") or "unknown_error")
            if err in ("invalid_auth", "account_inactive", "token_revoked",
                       "not_authed"):
                raise ConnectorError(
                    f"slack auth failed: {err}",
                    failure_class=FailureClass.authentication,
                    human_action_required=True,
                )
            if err in ("missing_scope", "not_allowed_token_type"):
                raise ConnectorError(
                    f"slack authorization failed: {err}",
                    failure_class=FailureClass.authorization,
                    human_action_required=True,
                )
            if err in ("channel_not_found", "thread_not_found") and allow_not_found:
                return data
            if err == "ratelimited":
                raise ConnectorError(
                    "slack rate limit exhausted",
                    failure_class=FailureClass.rate_limit,
                    retryable=True, retry_after=60,
                )
            raise ConnectorError(
                f"slack api error: {err}",
                failure_class=FailureClass.provider_error,
                retryable=err in ("fatal_error", "internal_error"),
            )
        return data

    def auth_test(self) -> dict[str, Any]:
        return self.call("auth.test")

    def conversations_list(self, *, types: str = "public_channel,private_channel",
                           cursor: Optional[str] = None,
                           limit: int = DEFAULT_LIMIT) -> tuple[list[dict], Optional[str]]:
        params: dict[str, Any] = {"types": types, "limit": limit,
                                  "exclude_archived": True}
        if cursor:
            params["cursor"] = cursor
        data = self.call("conversations.list", params=params)
        next_cur = (data.get("response_metadata") or {}).get("next_cursor") or None
        return list(data.get("channels") or []), next_cur or None

    def conversations_history(
        self, channel: str, *, oldest: Optional[str] = None,
        cursor: Optional[str] = None, limit: int = DEFAULT_LIMIT,
        inclusive: bool = True,
    ) -> tuple[list[dict], Optional[str], bool]:
        params: dict[str, Any] = {
            "channel": channel, "limit": limit, "inclusive": inclusive,
        }
        if oldest:
            params["oldest"] = oldest
        if cursor:
            params["cursor"] = cursor
        data = self.call("conversations.history", params=params)
        next_cur = (data.get("response_metadata") or {}).get("next_cursor") or None
        return (list(data.get("messages") or []), next_cur or None,
                bool(data.get("has_more")))

    def conversations_replies(
        self, channel: str, ts: str, *, cursor: Optional[str] = None,
        limit: int = DEFAULT_LIMIT,
    ) -> tuple[list[dict], Optional[str]]:
        params: dict[str, Any] = {"channel": channel, "ts": ts, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        data = self.call("conversations.replies", params=params,
                         allow_not_found=True)
        if not data.get("ok"):
            return [], None
        next_cur = (data.get("response_metadata") or {}).get("next_cursor") or None
        return list(data.get("messages") or []), next_cur or None

    def conversations_info(self, channel: str) -> Optional[dict[str, Any]]:
        data = self.call("conversations.info", params={"channel": channel},
                         allow_not_found=True)
        if not data.get("ok"):
            return None
        return data.get("channel")

    def users_info(self, user: str) -> Optional[dict[str, Any]]:
        data = self.call("users.info", params={"user": user}, allow_not_found=True)
        if not data.get("ok"):
            return None
        return data.get("user")
