"""Thin Google Calendar API v3 client (read-only).

Outlook/Graph calendar can share the same cognitive normalize path later;
Phase 5 ships one technical adapter against this shape (mocked in CI).
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote

import httpx

from ..models import FailureClass
from ..protocol import ConnectorError

CALENDAR_API = "https://www.googleapis.com/calendar/v3"


def _build_http(base_url: str, token: Optional[str]) -> httpx.Client:
    headers = {
        "Accept": "application/json",
        "User-Agent": "twin-connector-calendar",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    root = base_url if base_url.endswith("/") else base_url + "/"
    return httpx.Client(base_url=root, headers=headers, timeout=30)


class CalendarClient:
    def __init__(self, token: Optional[str], *,
                 base_url: str = CALENDAR_API, http: Optional[httpx.Client] = None):
        self._http = http or _build_http(base_url, token)

    def close(self) -> None:
        self._http.close()

    def call(self, path: str, *, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        try:
            resp = self._http.get(path.lstrip("/"), params=params or {})
        except httpx.HTTPError as exc:
            raise ConnectorError(
                f"calendar network error: {type(exc).__name__}",
                failure_class=FailureClass.network, retryable=True,
            ) from exc
        return self._decode(resp)

    def _decode(self, resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code == 429:
            retry = resp.headers.get("Retry-After", "60")
            raise ConnectorError(
                "calendar rate limit exhausted",
                failure_class=FailureClass.rate_limit, retryable=True,
                retry_after=int(retry) if str(retry).isdigit() else 60,
            )
        if resp.status_code in (401, 403):
            raise ConnectorError(
                "calendar credential rejected",
                failure_class=(FailureClass.authentication if resp.status_code == 401
                               else FailureClass.authorization),
                human_action_required=True,
            )
        if resp.status_code >= 500:
            raise ConnectorError(
                f"calendar server error ({resp.status_code})",
                failure_class=FailureClass.provider_error, retryable=True,
            )
        if resp.status_code == 404:
            return {}
        try:
            data = resp.json()
        except ValueError as exc:
            raise ConnectorError(
                "calendar returned a non-JSON body",
                failure_class=FailureClass.schema_change,
            ) from exc
        if not isinstance(data, dict):
            raise ConnectorError(
                "calendar returned a non-object payload",
                failure_class=FailureClass.schema_change,
            )
        if data.get("error"):
            err = data["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise ConnectorError(
                f"calendar api error: {msg}",
                failure_class=FailureClass.provider_error,
            )
        return data

    def list_calendars(self) -> list[dict[str, Any]]:
        data = self.call("users/me/calendarList")
        return list(data.get("items") or [])

    def list_events(
        self, calendar_id: str, *,
        updated_min: Optional[str] = None,
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
        page_token: Optional[str] = None,
        max_results: int = 50,
        show_deleted: bool = True,
    ) -> tuple[list[dict[str, Any]], Optional[str]]:
        params: dict[str, Any] = {
            "maxResults": max_results,
            "singleEvents": "true",
            "orderBy": "updated",
            "showDeleted": "true" if show_deleted else "false",
        }
        if updated_min:
            params["updatedMin"] = updated_min
        if time_min:
            params["timeMin"] = time_min
        if time_max:
            params["timeMax"] = time_max
        if page_token:
            params["pageToken"] = page_token
        path = f"calendars/{quote(calendar_id, safe='')}/events"
        data = self.call(path, params=params)
        return list(data.get("items") or []), data.get("nextPageToken")
