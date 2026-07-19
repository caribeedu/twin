"""Offline Gmail API double for connector tests."""
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
        self.history_id = 1000
        self.labels: dict[str, dict[str, Any]] = {
            "INBOX": {"id": "INBOX", "name": "INBOX", "type": "system",
                      "messagesTotal": 0},
            "Label_Work": {"id": "Label_Work", "name": "Work", "type": "user",
                           "messagesTotal": 0},
        }
        self.messages: dict[str, dict[str, Any]] = {}
        self.history_events: list[dict[str, Any]] = []
        self.history_too_old = False
        self.rate_limited = False
        self.requests: list[str] = []

    def add_message(
        self, msg_id: str, *, thread_id: str, subject: str, body: str,
        from_addr: str = "alice@acme.com", to: str = "edu@acme.com",
        label_ids: Optional[list[str]] = None,
        internal_date_ms: int = 1700000001000,
        in_reply_to: Optional[str] = None,
        record_history: bool = True,
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
            "historyId": str(self.history_id),
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
        if record_history:
            self.history_id += 1
            self.history_events.append({
                "id": str(self.history_id),
                "messagesAdded": [{"message": {
                    "id": msg_id, "labelIds": list(msg["labelIds"]),
                }}],
            })
        return msg

    def add_label(self, msg_id: str, label_id: str) -> None:
        msg = self.messages[msg_id]
        if label_id not in msg["labelIds"]:
            msg["labelIds"].append(label_id)
        self.history_id += 1
        self.history_events.append({
            "id": str(self.history_id),
            "labelsAdded": [{"message": {"id": msg_id},
                             "labelIds": [label_id]}],
        })

    def delete_message(self, msg_id: str) -> None:
        self.messages.pop(msg_id, None)
        self.history_id += 1
        self.history_events.append({
            "id": str(self.history_id),
            "messagesDeleted": [{"message": {"id": msg_id}}],
        })

    def remove_label(self, msg_id: str, label_id: str) -> None:
        msg = self.messages.get(msg_id)
        if msg and label_id in msg["labelIds"]:
            msg["labelIds"] = [l for l in msg["labelIds"] if l != label_id]
        self.history_id += 1
        self.history_events.append({
            "id": str(self.history_id),
            "labelsRemoved": [{"message": {"id": msg_id},
                               "labelIds": [label_id]}],
        })

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        path = url.path.lstrip("/")
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
                "emailAddress": self.email,
                "messagesTotal": len(self.messages),
                "historyId": str(self.history_id),
            })
        if path == "users/me/labels":
            return httpx.Response(200, json={"labels": list(self.labels.values())})
        if path == "users/me/history":
            if self.history_too_old:
                return httpx.Response(404, json={
                    "error": {"code": 404, "message": "historyId too old"},
                })
            start = int(flat.get("startHistoryId") or 0)
            label_filter = flat.get("labelId")
            events = []
            for ev in self.history_events:
                if int(ev["id"]) <= start:
                    continue
                if label_filter:
                    # keep events that mention the label or deletions
                    keep = False
                    for key in ("messagesAdded", "labelsAdded", "labelsRemoved"):
                        for row in ev.get(key) or []:
                            labs = row.get("labelIds") or (
                                (row.get("message") or {}).get("labelIds") or [])
                            if label_filter in labs:
                                keep = True
                    if ev.get("messagesDeleted"):
                        keep = True
                    if not keep:
                        continue
                events.append(ev)
            return httpx.Response(200, json={
                "history": events,
                "historyId": str(self.history_id),
            })
        if path == "users/me/messages":
            label_ids = params.get("labelIds") or []
            q = flat.get("q", "")
            after_ts = None
            before_ts = None
            if "after:" in q:
                try:
                    after_ts = int(q.split("after:")[1].split()[0]) * 1000
                except ValueError:
                    after_ts = None
            if "before:" in q:
                try:
                    before_ts = int(q.split("before:")[1].split()[0]) * 1000
                except ValueError:
                    before_ts = None
            matches = []
            for msg in self.messages.values():
                if label_ids and not any(l in msg["labelIds"] for l in label_ids):
                    continue
                if after_ts is not None and int(msg["internalDate"]) <= after_ts:
                    continue
                if before_ts is not None and int(msg["internalDate"]) >= before_ts:
                    continue
                matches.append({"id": msg["id"], "threadId": msg["threadId"]})
            matches.sort(key=lambda m: m["id"])
            page_size = int(flat.get("maxResults") or 50)
            page_token = flat.get("pageToken")
            start = int(page_token) if page_token and page_token.isdigit() else 0
            page = matches[start:start + page_size]
            next_token = None
            if start + page_size < len(matches):
                next_token = str(start + page_size)
            body: dict[str, Any] = {"messages": page}
            if next_token:
                body["nextPageToken"] = next_token
            return httpx.Response(200, json=body)
        if path.startswith("users/me/messages/"):
            mid = path.rsplit("/", 1)[-1]
            msg = self.messages.get(mid)
            if not msg:
                return httpx.Response(404, json={"error": {"message": "not found"}})
            return httpx.Response(200, json=msg)
        return httpx.Response(404, json={"error": {"message": "unknown"}})
