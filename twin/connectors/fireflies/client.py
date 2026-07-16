"""Thin Fireflies API client (read-only transcripts).

Uses a simplified REST shape compatible with the offline double. Real
deployments point ``api_base_url`` at Fireflies GraphQL/REST as needed;
Phase 5 normalizes into the shared MeetingRecord model either way.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote

import httpx

from ..models import FailureClass
from ..protocol import ConnectorError

FIREFLIES_API = "https://api.fireflies.ai/v2"


def _build_http(base_url: str, token: Optional[str]) -> httpx.Client:
    headers = {
        "Accept": "application/json",
        "User-Agent": "twin-connector-fireflies",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    root = base_url if base_url.endswith("/") else base_url + "/"
    return httpx.Client(base_url=root, headers=headers, timeout=30)


class FirefliesClient:
    def __init__(self, token: Optional[str], *,
                 base_url: str = FIREFLIES_API, http: Optional[httpx.Client] = None):
        self._http = http or _build_http(base_url, token)

    def close(self) -> None:
        self._http.close()

    def call(self, path: str, *, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        try:
            resp = self._http.get(path.lstrip("/"), params=params or {})
        except httpx.HTTPError as exc:
            raise ConnectorError(
                f"fireflies network error: {type(exc).__name__}",
                failure_class=FailureClass.network, retryable=True,
            ) from exc
        return self._decode(resp)

    def _decode(self, resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code == 429:
            retry = resp.headers.get("Retry-After", "60")
            raise ConnectorError(
                "fireflies rate limit exhausted",
                failure_class=FailureClass.rate_limit, retryable=True,
                retry_after=int(retry) if str(retry).isdigit() else 60,
            )
        if resp.status_code in (401, 403):
            raise ConnectorError(
                "fireflies credential rejected",
                failure_class=(FailureClass.authentication if resp.status_code == 401
                               else FailureClass.authorization),
                human_action_required=True,
            )
        if resp.status_code >= 500:
            raise ConnectorError(
                f"fireflies server error ({resp.status_code})",
                failure_class=FailureClass.provider_error, retryable=True,
            )
        if resp.status_code == 404:
            return {}
        try:
            data = resp.json()
        except ValueError as exc:
            raise ConnectorError(
                "fireflies returned a non-JSON body",
                failure_class=FailureClass.schema_change,
            ) from exc
        if not isinstance(data, dict):
            raise ConnectorError(
                "fireflies returned a non-object payload",
                failure_class=FailureClass.schema_change,
            )
        if data.get("error"):
            err = data["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise ConnectorError(
                f"fireflies api error: {msg}",
                failure_class=FailureClass.provider_error,
            )
        return data

    def me(self) -> dict[str, Any]:
        return self.call("user")

    def list_transcripts(
        self, *,
        updated_since: Optional[str] = None,
        page_token: Optional[str] = None,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], Optional[str]]:
        params: dict[str, Any] = {"limit": limit}
        if updated_since:
            params["updated_since"] = updated_since
        if page_token:
            params["page_token"] = page_token
        data = self.call("transcripts", params=params)
        return list(data.get("transcripts") or data.get("data") or []), data.get(
            "next_page_token")

    def get_transcript(self, transcript_id: str) -> dict[str, Any]:
        return self.call(f"transcripts/{quote(transcript_id, safe='')}")
