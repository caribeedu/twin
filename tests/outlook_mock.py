"""Offline Microsoft Graph mail double for Phase 4 connector tests."""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import httpx


class FakeOutlookAPI:
    def __init__(self):
        self.valid_token: Optional[str] = "ewog.test-token"
        self.email = "edu@acme.com"
        self.folders: dict[str, dict[str, Any]] = {
            "Inbox": {"id": "Inbox", "displayName": "Inbox", "totalItemCount": 0},
            "Folder_Work": {"id": "Folder_Work", "displayName": "Work",
                            "totalItemCount": 0},
        }
        self.messages: dict[str, dict[str, Any]] = {}  # id → msg
        self.folder_messages: dict[str, list[str]] = {}
        self.rate_limited = False
        self.requests: list[str] = []

    def add_message(
        self, msg_id: str, *, conversation_id: str, subject: str, body: str,
        folder_id: str = "Inbox", from_addr: str = "alice@acme.com",
        received: str = "2023-11-14T22:13:21Z",
        quoted: bool = False,
    ) -> dict[str, Any]:
        content = body
        if quoted:
            content = body + "\n\nOn Mon, Alice wrote:\n> prior"
        msg = {
            "id": msg_id,
            "subject": subject,
            "bodyPreview": body[:80],
            "from": {"emailAddress": {"address": from_addr}},
            "toRecipients": [{"emailAddress": {"address": self.email}}],
            "ccRecipients": [],
            "receivedDateTime": received,
            "conversationId": conversation_id,
            "internetMessageId": f"<{msg_id}@mail.acme.com>",
            "changeKey": f"ck-{msg_id}",
            "hasAttachments": False,
            "isDraft": False,
            "body": {"contentType": "Text", "content": content},
            "_folder_id": folder_id,
        }
        self.messages[msg_id] = msg
        self.folder_messages.setdefault(folder_id, []).append(msg_id)
        if folder_id in self.folders:
            self.folders[folder_id]["totalItemCount"] = len(
                self.folder_messages[folder_id])
        return msg

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        path = url.path.lstrip("/")
        if path.startswith("v1.0/"):
            path = path[len("v1.0/"):]
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.requests.append(path + (f"?{url.query}" if url.query else ""))

        auth = request.headers.get("Authorization", "")
        if self.valid_token is not None and auth != f"Bearer {self.valid_token}":
            return httpx.Response(401, json={"error": {"message": "invalid"}})
        if self.rate_limited:
            return httpx.Response(429, json={"error": {"message": "rate"}},
                                  headers={"Retry-After": "60"})

        if path == "me":
            return httpx.Response(200, json={
                "mail": self.email, "userPrincipalName": self.email,
            })
        if path == "me/mailFolders":
            return httpx.Response(200, json={"value": list(self.folders.values())})
        if path.startswith("me/mailFolders/") and path.endswith("/messages"):
            folder_id = path[len("me/mailFolders/"):-len("/messages")]
            ids = list(self.folder_messages.get(folder_id, []))
            filt = params.get("$filter", "")
            msgs = [self.messages[i] for i in ids if i in self.messages]
            if "receivedDateTime ge " in filt:
                since = filt.split("receivedDateTime ge ")[1].split()[0]
                msgs = [m for m in msgs if m["receivedDateTime"] >= since]
            msgs.sort(key=lambda m: m["receivedDateTime"], reverse=True)
            return httpx.Response(200, json={"value": msgs})
        return httpx.Response(404, json={"error": {"message": "unknown"}})
