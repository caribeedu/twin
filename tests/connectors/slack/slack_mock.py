"""Offline Slack Web API double for connector tests."""
from __future__ import annotations

from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import httpx


def _user(user_id: str, *, name: str = "alice", bot: bool = False) -> dict[str, Any]:
    return {
        "id": user_id, "name": name, "real_name": name.title(),
        "is_bot": bot, "deleted": False,
    }


class FakeSlackAPI:
    def __init__(self):
        self.valid_token: Optional[str] = "xoxb-test-token"
        self.team = {"id": "T1", "name": "acme"}
        self.authed_user = "U_EDU"
        self.channels: dict[str, dict[str, Any]] = {}
        self.messages: dict[str, list[dict[str, Any]]] = {}  # channel → msgs
        self.replies: dict[str, list[dict[str, Any]]] = {}   # "C:ts" → replies
        self.users: dict[str, dict[str, Any]] = {
            "U_EDU": _user("U_EDU", name="edu"),
            "U_ALICE": _user("U_ALICE", name="alice"),
            "U_BOT": _user("U_BOT", name="github-bot", bot=True),
        }
        self.rate_limited = False
        self.info_fails = False
        self.requests: list[str] = []

    def add_channel(self, channel_id: str, *, name: str,
                    private: bool = False, im: bool = False,
                    mpim: bool = False) -> dict[str, Any]:
        ch = {
            "id": channel_id, "name": name, "is_private": private,
            "is_im": im, "is_mpim": mpim,
            "is_channel": (not private and not im and not mpim),
            "num_members": 3, "created": 1700000000,
        }
        self.channels[channel_id] = ch
        self.messages.setdefault(channel_id, [])
        return ch

    def add_message(self, channel: str, ts: str, *, text: str,
                    user: str = "U_ALICE", reply_count: int = 0,
                    **extra) -> dict[str, Any]:
        msg = {"type": "message", "ts": ts, "text": text, "user": user,
               "reply_count": reply_count, **extra}
        self.messages.setdefault(channel, []).append(msg)
        # Slack returns newest-first
        self.messages[channel].sort(key=lambda m: float(m["ts"]), reverse=True)
        return msg

    def add_reply(self, channel: str, thread_ts: str, ts: str, *, text: str,
                  user: str = "U_EDU") -> dict[str, Any]:
        reply = {"type": "message", "ts": ts, "thread_ts": thread_ts,
                 "text": text, "user": user}
        key = f"{channel}:{thread_ts}"
        self.replies.setdefault(key, []).append(reply)
        # ensure parent has reply_count
        for msg in self.messages.get(channel, []):
            if msg["ts"] == thread_ts:
                msg["reply_count"] = msg.get("reply_count", 0) + 1
        return reply

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        # httpx joins base https://slack.com/api/ + method → /api/auth.test
        method = url.path.lstrip("/")
        if method.startswith("api/"):
            method = method[len("api/"):]
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.requests.append(method + (f"?{url.query}" if url.query else ""))

        auth = request.headers.get("Authorization", "")
        if self.valid_token is not None and auth != f"Bearer {self.valid_token}":
            return httpx.Response(200, json={"ok": False, "error": "invalid_auth"})
        if self.rate_limited:
            return httpx.Response(429, json={"ok": False, "error": "ratelimited"},
                                  headers={"Retry-After": "90"})

        if method == "auth.test":
            return self._ok({"user": "edu", "user_id": self.authed_user,
                             "team": self.team["name"], "team_id": self.team["id"]})
        if method == "conversations.list":
            return self._ok({"channels": list(self.channels.values()),
                             "response_metadata": {"next_cursor": ""}})
        if method == "conversations.info":
            if self.info_fails:
                return self._ok({"ok": False, "error": "fatal_error"},
                                force_ok=False)
            ch = self.channels.get(params.get("channel", ""))
            if not ch:
                return self._ok({"ok": False, "error": "channel_not_found"},
                                force_ok=False)
            return self._ok({"channel": ch})
        if method == "conversations.history":
            return self._history(params)
        if method == "conversations.replies":
            return self._replies(params)
        if method == "users.info":
            user = self.users.get(params.get("user", ""))
            if not user:
                return self._ok({"ok": False, "error": "user_not_found"},
                                force_ok=False)
            return self._ok({"user": user})
        return self._ok({"ok": False, "error": "unknown_method"}, force_ok=False)

    def _history(self, params: dict[str, str]) -> httpx.Response:
        channel = params.get("channel", "")
        oldest = float(params["oldest"]) if params.get("oldest") else None
        cursor = params.get("cursor")
        limit = int(params.get("limit", "200"))
        msgs = list(self.messages.get(channel, []))
        if oldest is not None:
            msgs = [m for m in msgs if float(m["ts"]) >= oldest]
        # cursor is an integer offset encoded as string for the fake
        offset = int(cursor) if cursor and cursor.isdigit() else 0
        window = msgs[offset:offset + limit]
        next_offset = offset + limit
        has_more = next_offset < len(msgs)
        next_cursor = str(next_offset) if has_more else ""
        return self._ok({
            "messages": window, "has_more": has_more,
            "response_metadata": {"next_cursor": next_cursor},
        })

    def _replies(self, params: dict[str, str]) -> httpx.Response:
        channel = params.get("channel", "")
        ts = params.get("ts", "")
        key = f"{channel}:{ts}"
        parent = next((m for m in self.messages.get(channel, [])
                       if m["ts"] == ts), {"ts": ts, "text": "", "user": "?"})
        replies = [parent] + list(self.replies.get(key, []))
        return self._ok({
            "messages": replies, "has_more": False,
            "response_metadata": {"next_cursor": ""},
        })

    def _ok(self, data: dict[str, Any], *, force_ok: bool = True) -> httpx.Response:
        body = dict(data)
        if force_ok and "ok" not in body:
            body["ok"] = True
        return httpx.Response(200, json=body)
