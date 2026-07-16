"""Offline Gmail API double for Phase 4 connector tests."""

from __future__ import annotations

import base64
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import httpx


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


class FakeGmailAPI:
    def __init__(self):
        self.valid_token: Optional[str] = "ya29.test-token"
        self.email = "edu@acme.com"
        self.labels: dict[str, dict[str, Any]] = {
            "INBOX": {"id": "INBOX", "name": "INBOX", "type": "system",
                      "messagesTotal": 0},
            "Label_Work": {"id": "Label_Work", "name": "Work", "type": "user",
                           "messagesTotal": 0},
        }
        self.messages: dict[str, dict[str, Any]] = {}
        self.rate_limited = False
        self.requests: list[str] = []

    def add_message(
        self, msg_id: str, *, thread_id: str, subject: str, body: str,
        from_addr: str = "alice@acme.com", to: str = "edu@acme.com",
        label_ids: Optional[list[str]] = None,
        internal_date_ms: int = 1700000001000,
        in_reply_to: Optional[str] = None,
    ) -> dict[str, Any]:
        headers = [
            {"name": "From", "value": from_addr},
            {"name": "To", "value": to},
            {"name": "Subject", "value": subject},
            {"name": "Message-ID", "value": f"<{msg_id}@mail.acme.com>"},
        ]
        if in_reply_to:
            headers.append({"name": "In-Reply-To", "value": in_reply_to})
        msg = {
            "id": msg_id,
            "threadId": thread_id,
            "labelIds": label_ids or ["INBOX"],
            "snippet": body[:80],
            "internalDate": str(internal_date_ms),
            "historyId": str(internal_date_ms),
            "payload": {
                "mimeType": "text/plain",
                "headers": headers,
                "body": {"data": _b64(body), "size": len(body)},
            },
        }
        self.messages[msg_id] = msg
        for lid in msg["labelIds"]:
            if lid in self.labels:
                self.labels[lid]["messagesTotal"] = (
                    int(self.labels[lid].get("messagesTotal") or 0) + 1
                )
        return msg

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        path = url.path.lstrip("/")
        # base https://gmail.googleapis.com/gmail/v1/ + users/me/...
        if path.startswith("gmail/v1/"):
            path = path[len("gmail/v1/"):]
        params = {k: v for k, v in parse_qs(url.query).items()}
        flat = {k: v[0] for k, v in params.items()}
        self.requests.append(path + (f"?{url.query}" if url.query else ""))

        auth = request.headers.get("Authorization", "")
        if self.valid_token is not None and auth != f"Bearer {self.valid_token}":
            return httpx.Response(401, json={"error": {"message": "invalid"}})
        if self.rate_limited:
            return httpx.Response(429, json={"error": {"message": "rate"}},
                                  headers={"Retry-After": "90"})

        if path == "users/me/profile":
            return httpx.Response(200, json={
                "emailAddress": self.email, "messagesTotal": len(self.messages),
            })
        if path == "users/me/labels":
            return httpx.Response(200, json={"labels": list(self.labels.values())})
        if path == "users/me/messages":
            label_ids = params.get("labelIds") or []
            q = flat.get("q", "")
            after_ts = None
            if "after:" in q:
                try:
                    after_ts = int(q.split("after:")[1].split()[0]) * 1000
                except ValueError:
                    after_ts = None
            matches = []
            for msg in self.messages.values():
                if label_ids and not any(l in msg["labelIds"] for l in label_ids):
                    continue
                if after_ts is not None and int(msg["internalDate"]) < after_ts:
                    continue
                matches.append({"id": msg["id"], "threadId": msg["threadId"]})
            matches.sort(key=lambda m: m["id"])
            return httpx.Response(200, json={"messages": matches})
        if path.startswith("users/me/messages/"):
            mid = path.rsplit("/", 1)[-1]
            msg = self.messages.get(mid)
            if not msg:
                return httpx.Response(404, json={"error": {"message": "not found"}})
            return httpx.Response(200, json=msg)
        return httpx.Response(404, json={"error": {"message": "unknown"}})
