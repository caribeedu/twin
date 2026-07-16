"""Offline Fireflies REST double for Phase 5 connector tests."""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlparse

import httpx


class FakeFirefliesAPI:
    def __init__(self):
        self.valid_token: Optional[str] = "ff-test-token"
        self.user = {"email": "edu@acme.com", "name": "Edu Caribe"}
        self.transcripts: dict[str, dict[str, Any]] = {}
        self.rate_limited = False
        self.requests: list[str] = []

    def add_transcript(
        self,
        tid: str,
        *,
        title: str = "Architecture sync",
        date: str = "2026-07-15T15:00:00Z",
        updated_at: Optional[str] = None,
        summary: Optional[str] = "Team decided on PostgreSQL.",
        calendar_event_id: Optional[str] = "evt_arch_1",
        ical_uid: Optional[str] = "evt_arch_1@google.com",
        conference_url: Optional[str] = "https://meet.google.com/abc-defg",
        participants: Optional[list[Any]] = None,
        sentences: Optional[list[dict[str, Any]]] = None,
        speakers: Optional[list[dict[str, Any]]] = None,
        host_email: str = "edu@acme.com",
    ) -> dict[str, Any]:
        payload = {
            "id": tid,
            "title": title,
            "date": date,
            "updated_at": updated_at or date,
            "summary": summary,
            "calendar_event_id": calendar_event_id,
            "ical_uid": ical_uid,
            "meeting_link": conference_url,
            "host_email": host_email,
            "organizer_email": host_email,
            "participants": participants or [
                {"name": "Edu Caribe", "email": "edu@acme.com"},
                {"name": "Alice", "email": "alice@acme.com"},
            ],
            "speakers": speakers or [
                {"name": "Edu Caribe", "email": "edu@acme.com", "id": "sp_edu"},
                {"name": "Alice", "email": "alice@acme.com", "id": "sp_alice"},
            ],
            "sentences": sentences or [
                {
                    "speaker_name": "Edu Caribe",
                    "text": "Should we use Redis for the queue?",
                    "start_time": 0,
                    "end_time": 3000,
                },
                {
                    "speaker_name": "Alice",
                    "text": "No — prefer PostgreSQL advisory locks.",
                    "start_time": 3100,
                    "end_time": 7000,
                },
                {
                    "speaker_name": "Edu Caribe",
                    "text": "Agreed. Decision: PostgreSQL.",
                    "start_time": 7100,
                    "end_time": 10000,
                },
            ],
            "duration": 600,
            "transcript_version": "v1",
        }
        self.transcripts[tid] = payload
        return payload

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        path = url.path.lstrip("/")
        if path.startswith("v2/"):
            path = path[len("v2/"):]
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.requests.append(path + (f"?{url.query}" if url.query else ""))

        auth = request.headers.get("Authorization", "")
        if self.valid_token is not None and auth != f"Bearer {self.valid_token}":
            return httpx.Response(401, json={"error": {"message": "Unauthorized"}})
        if self.rate_limited:
            return httpx.Response(
                429, json={"error": {"message": "Rate limited"}},
                headers={"Retry-After": "30"},
            )

        if path == "user":
            return httpx.Response(200, json=self.user)

        if path == "transcripts":
            items = list(self.transcripts.values())
            since = params.get("updated_since")
            if since:
                items = [
                    t for t in items
                    if str(t.get("updated_at") or t.get("date") or "") >= since
                ]
            items.sort(key=lambda t: str(t.get("updated_at") or t.get("date") or ""))
            page_size = int(params.get("limit") or 50)
            page_token = params.get("page_token")
            offset = int(page_token.split(":", 1)[1]) if (
                page_token and page_token.startswith("p:")
            ) else 0
            page = items[offset: offset + page_size]
            stubs = [
                {
                    "id": t["id"],
                    "title": t.get("title"),
                    "date": t.get("date"),
                    "updated_at": t.get("updated_at"),
                    "duration": t.get("duration"),
                }
                for t in page
            ]
            body: dict[str, Any] = {"transcripts": stubs}
            if offset + page_size < len(items):
                body["next_page_token"] = f"p:{offset + page_size}"
            return httpx.Response(200, json=body)

        if path.startswith("transcripts/"):
            tid = unquote(path[len("transcripts/"):])
            t = self.transcripts.get(tid)
            if not t:
                return httpx.Response(404, json={"error": {"message": "Not Found"}})
            return httpx.Response(200, json=t)

        return httpx.Response(404, json={"error": {"message": "Not Found"}})
