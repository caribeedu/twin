"""Thin Microsoft Graph mail client (read-only)."""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote

import httpx

from ..models import FailureClass
from ..protocol import ConnectorError

GRAPH_API = "https://graph.microsoft.com/v1.0"


def _build_http(base_url: str, token: Optional[str]) -> httpx.Client:
    headers = {
        "Accept": "application/json",
        "User-Agent": "twin-connector-outlook",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    root = base_url if base_url.endswith("/") else base_url + "/"
    return httpx.Client(base_url=root, headers=headers, timeout=30)


class OutlookClient:
    def __init__(self, token: Optional[str], *,
                 base_url: str = GRAPH_API, http: Optional[httpx.Client] = None):
        self._http = http or _build_http(base_url, token)

    def close(self) -> None:
        self._http.close()

    def call(self, path: str, *, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        try:
            resp = self._http.get(path.lstrip("/"), params=params or {})
        except httpx.HTTPError as exc:
            raise ConnectorError(
                f"graph network error: {type(exc).__name__}",
                failure_class=FailureClass.network, retryable=True,
            ) from exc
        return self._decode(resp)

    def call_url(self, url: str) -> dict[str, Any]:
        """Absolute nextLink / deltaLink — same status handling as ``call``."""
        try:
            resp = self._http.get(url)
        except httpx.HTTPError as exc:
            raise ConnectorError(
                f"graph network error: {type(exc).__name__}",
                failure_class=FailureClass.network, retryable=True,
            ) from exc
        return self._decode(resp)

    def _decode(self, resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code == 429:
            retry = resp.headers.get("Retry-After", "60")
            raise ConnectorError(
                "graph rate limit exhausted",
                failure_class=FailureClass.rate_limit, retryable=True,
                retry_after=int(retry) if str(retry).isdigit() else 60,
            )
        if resp.status_code in (401, 403):
            raise ConnectorError(
                "graph credential rejected",
                failure_class=(FailureClass.authentication if resp.status_code == 401
                               else FailureClass.authorization),
                human_action_required=True,
            )
        if resp.status_code >= 500:
            raise ConnectorError(
                f"graph server error ({resp.status_code})",
                failure_class=FailureClass.provider_error, retryable=True,
            )
        if resp.status_code == 404:
            return {}
        try:
            data = resp.json()
        except ValueError as exc:
            raise ConnectorError(
                "graph returned a non-JSON body",
                failure_class=FailureClass.schema_change,
            ) from exc
        if not isinstance(data, dict):
            raise ConnectorError(
                "graph returned a non-object payload",
                failure_class=FailureClass.schema_change,
            )
        if data.get("error"):
            err = data["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise ConnectorError(
                f"graph api error: {msg}",
                failure_class=FailureClass.provider_error,
            )
        return data

    def me(self) -> dict[str, Any]:
        return self.call("me")

    def list_folders(self) -> list[dict[str, Any]]:
        data = self.call("me/mailFolders", params={"$top": 100})
        return list(data.get("value") or [])

    def list_messages(
        self, folder_id: str, *,
        filter_query: Optional[str] = None,
        skip_token: Optional[str] = None,
        top: int = 50,
    ) -> tuple[list[dict[str, Any]], Optional[str]]:
        params: dict[str, Any] = {
            "$top": top,
            "$orderby": "receivedDateTime desc",
            "$select": ("id,subject,bodyPreview,from,toRecipients,ccRecipients,"
                        "receivedDateTime,conversationId,internetMessageId,"
                        "changeKey,hasAttachments,body,isDraft"),
        }
        if filter_query:
            params["$filter"] = filter_query
        path = f"me/mailFolders/{quote(folder_id, safe='')}/messages"
        if skip_token and str(skip_token).startswith("http"):
            data = self.call_url(skip_token)
        else:
            data = self.call(path, params=params)
        return list(data.get("value") or []), data.get("@odata.nextLink")

    def delta_messages(
        self, folder_id: str, *,
        link: Optional[str] = None,
        top: int = 50,
    ) -> dict[str, Any]:
        if link and str(link).startswith("http"):
            return self.call_url(link)
        path = f"me/mailFolders/{quote(folder_id, safe='')}/messages/delta"
        return self.call(path, params={"$top": top})

    def get_message(self, message_id: str) -> dict[str, Any]:
        return self.call(
            f"me/messages/{quote(message_id, safe='')}",
            params={"$select": ("id,subject,bodyPreview,from,toRecipients,"
                                "ccRecipients,receivedDateTime,conversationId,"
                                "internetMessageId,changeKey,hasAttachments,"
                                "body,isDraft,parentFolderId")},
        )

    def list_attachments(self, message_id: str) -> list[dict[str, Any]]:
        data = self.call(
            f"me/messages/{quote(message_id, safe='')}/attachments",
            params={"$select": ("id,name,contentType,size,isInline,"
                                "contentId,@odata.type")},
        )
        return list(data.get("value") or [])
