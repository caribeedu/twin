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
        self.messages: dict[str, dict[str, Any]] = {}
        self.folder_messages: dict[str, list[str]] = {}
        self.attachments: dict[str, list[dict[str, Any]]] = {}
        self.delta_token = 1
        self.pending_delta: dict[str, list[dict[str, Any]]] = {}
        self.rate_limited = False
        self.next_link_rate_limited = False
        self.requests: list[str] = []

    def add_message(
        self, msg_id: str, *, conversation_id: str, subject: str, body: str,
        folder_id: str = "Inbox", from_addr: str = "alice@acme.com",
        received: str = "2023-11-14T22:13:21Z",
        quoted: bool = False,
        has_attachments: bool = False,
        attachment: Optional[dict[str, Any]] = None,
        via_delta: bool = False,
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
            "hasAttachments": has_attachments or bool(attachment),
            "isDraft": False,
            "body": {"contentType": "Text", "content": content},
            "parentFolderId": folder_id,
            "_folder_id": folder_id,
        }
        self.messages[msg_id] = msg
        self.folder_messages.setdefault(folder_id, []).append(msg_id)
        if folder_id in self.folders:
            self.folders[folder_id]["totalItemCount"] = len(
                self.folder_messages[folder_id])
        if attachment:
            self.attachments[msg_id] = [attachment]
            msg["hasAttachments"] = True
        if via_delta:
            self.pending_delta.setdefault(folder_id, []).append(dict(msg))
        return msg

    def move_message(self, msg_id: str, new_folder: str) -> None:
        msg = self.messages.get(msg_id)
        if not msg:
            return
        old = msg.get("_folder_id")
        if old and msg_id in self.folder_messages.get(old, []):
            self.folder_messages[old].remove(msg_id)
            self.pending_delta.setdefault(old, []).append({
                "id": msg_id, "@removed": {"reason": "changed"},
            })
        msg["_folder_id"] = new_folder
        msg["parentFolderId"] = new_folder
        msg["changeKey"] = f"ck-{msg_id}-moved-{new_folder}"
        self.folder_messages.setdefault(new_folder, []).append(msg_id)
        self.pending_delta.setdefault(new_folder, []).append(dict(msg))

    def remove_message(self, msg_id: str) -> None:
        msg = self.messages.pop(msg_id, None)
        if not msg:
            return
        folder = msg.get("_folder_id")
        if folder and msg_id in self.folder_messages.get(folder, []):
            self.folder_messages[folder].remove(msg_id)
        if folder:
            self.pending_delta.setdefault(folder, []).append({
                "id": msg_id, "@removed": {"reason": "deleted"},
            })

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        path = url.path.lstrip("/")
        if path.startswith("v1.0/"):
            path = path[len("v1.0/"):]
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        full = path + (f"?{url.query}" if url.query else "")
        self.requests.append(full)

        auth = request.headers.get("Authorization", "")
        if self.valid_token is not None and auth != f"Bearer {self.valid_token}":
            return httpx.Response(401, json={"error": {"message": "invalid"}})
        if self.rate_limited:
            return httpx.Response(429, json={"error": {"message": "rate"}},
                                  headers={"Retry-After": "60"})

        if path.startswith("delta-next/") or "delta-next" in path:
            if self.next_link_rate_limited:
                return httpx.Response(429, json={"error": {"message": "rate"}},
                                      headers={"Retry-After": "30"})
            return httpx.Response(200, json={
                "value": [],
                "@odata.deltaLink": (
                    f"https://graph.microsoft.com/v1.0/me/mailFolders/Inbox/"
                    f"messages/delta?$deltatoken={self.delta_token}"
                ),
            })

        if path == "me":
            return httpx.Response(200, json={
                "mail": self.email, "userPrincipalName": self.email,
            })
        if path == "me/mailFolders":
            return httpx.Response(200, json={"value": list(self.folders.values())})

        if path.startswith("me/messages/") and "/attachments" not in path:
            mid = path[len("me/messages/"):].split("/")[0]
            msg = self.messages.get(mid)
            if not msg:
                return httpx.Response(404, json={"error": {"message": "gone"}})
            return httpx.Response(200, json=msg)

        if "/attachments" in path and path.startswith("me/messages/"):
            mid = path[len("me/messages/"):].split("/")[0]
            return httpx.Response(200, json={
                "value": self.attachments.get(mid, []),
            })

        if path.endswith("/messages/delta") or "/messages/delta" in path:
            folder_id = "Inbox"
            if "mailFolders/" in path:
                folder_id = path.split("mailFolders/")[1].split("/")[0]
            delta_link = (
                f"https://graph.microsoft.com/v1.0/me/mailFolders/"
                f"{folder_id}/messages/delta?$deltatoken={self.delta_token}"
            )
            if "deltatoken" in (url.query or "") or params.get("$deltatoken"):
                values = list(self.pending_delta.pop(folder_id, []))
                self.delta_token += 1
                return httpx.Response(200, json={
                    "value": values,
                    "@odata.deltaLink": (
                        f"https://graph.microsoft.com/v1.0/me/mailFolders/"
                        f"{folder_id}/messages/delta?$deltatoken={self.delta_token}"
                    ),
                })
            # Initial delta enumeration — authoritative folder snapshot.
            ids = list(self.folder_messages.get(folder_id, []))
            values = [dict(self.messages[i]) for i in ids if i in self.messages]
            return httpx.Response(200, json={
                "value": values,
                "@odata.deltaLink": delta_link,
            })

        if path.startswith("me/mailFolders/") and path.endswith("/messages"):
            folder_id = path[len("me/mailFolders/"):-len("/messages")]
            ids = list(self.folder_messages.get(folder_id, []))
            filt = params.get("$filter", "")
            msgs = [self.messages[i] for i in ids if i in self.messages]
            if "receivedDateTime ge " in filt:
                since = filt.split("receivedDateTime ge ")[1].split()[0]
                msgs = [m for m in msgs if m["receivedDateTime"] >= since]
            if "receivedDateTime le " in filt:
                until = filt.split("receivedDateTime le ")[1].split()[0]
                msgs = [m for m in msgs if m["receivedDateTime"] <= until]
            msgs.sort(key=lambda m: m["receivedDateTime"], reverse=True)
            return httpx.Response(200, json={"value": msgs})
        return httpx.Response(404, json={"error": {"message": "unknown"}})
