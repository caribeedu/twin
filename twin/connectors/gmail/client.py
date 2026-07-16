"""Thin Gmail API v1 client (read-only).

Authenticated GETs for labels/messages, page-token pagination and
rate-limit translation into structured ``ConnectorError``s.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote

import httpx

from ..models import FailureClass
from ..protocol import ConnectorError

GMAIL_API = "https://gmail.googleapis.com/gmail/v1"


def _build_http(base_url: str, token: Optional[str]) -> httpx.Client:
    headers = {
        "Accept": "application/json",
        "User-Agent": "twin-connector-gmail",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    root = base_url if base_url.endswith("/") else base_url + "/"
    return httpx.Client(base_url=root, headers=headers, timeout=30)


class GmailClient:
    def __init__(self, token: Optional[str], *,
                 base_url: str = GMAIL_API, http: Optional[httpx.Client] = None):
        self._http = http or _build_http(base_url, token)

    def close(self) -> None:
        self._http.close()

    def call(self, path: str, *, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        try:
            resp = self._http.get(path.lstrip("/"), params=params or {})
        except httpx.HTTPError as exc:
            raise ConnectorError(
                f"gmail network error: {type(exc).__name__}",
                failure_class=FailureClass.network, retryable=True,
            ) from exc

        if resp.status_code == 429:
            retry = resp.headers.get("Retry-After", "60")
            raise ConnectorError(
                "gmail rate limit exhausted",
                failure_class=FailureClass.rate_limit, retryable=True,
                retry_after=int(retry) if str(retry).isdigit() else 60,
            )
        if resp.status_code in (401, 403):
            raise ConnectorError(
                "gmail credential rejected",
                failure_class=(FailureClass.authentication if resp.status_code == 401
                               else FailureClass.authorization),
                human_action_required=True,
            )
        if resp.status_code >= 500:
            raise ConnectorError(
                f"gmail server error ({resp.status_code})",
                failure_class=FailureClass.provider_error, retryable=True,
            )
        if resp.status_code == 404:
            return {}
        try:
            data = resp.json()
        except ValueError as exc:
            raise ConnectorError(
                "gmail returned a non-JSON body",
                failure_class=FailureClass.schema_change,
            ) from exc
        if not isinstance(data, dict):
            raise ConnectorError(
                "gmail returned a non-object payload",
                failure_class=FailureClass.schema_change,
            )
        if data.get("error"):
            err = data["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise ConnectorError(
                f"gmail api error: {msg}",
                failure_class=FailureClass.provider_error,
            )
        return data

    def profile(self) -> dict[str, Any]:
        return self.call("users/me/profile")

    def list_labels(self) -> list[dict[str, Any]]:
        data = self.call("users/me/labels")
        return list(data.get("labels") or [])

    def list_messages(
        self, *, label_ids: Optional[list[str]] = None, query: Optional[str] = None,
        page_token: Optional[str] = None, max_results: int = 100,
    ) -> tuple[list[dict[str, Any]], Optional[str]]:
        params: dict[str, Any] = {"maxResults": max_results}
        if label_ids:
            params["labelIds"] = label_ids
        if query:
            params["q"] = query
        if page_token:
            params["pageToken"] = page_token
        data = self.call("users/me/messages", params=params)
        return list(data.get("messages") or []), data.get("nextPageToken")

    def get_message(self, message_id: str, *,
                    fmt: str = "full") -> dict[str, Any]:
        return self.call(
            f"users/me/messages/{quote(message_id, safe='')}",
            params={"format": fmt},
        )
