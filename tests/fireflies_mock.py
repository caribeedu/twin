"""Offline Fireflies GraphQL double for Phase 5 connector tests.

Imitates ``POST https://api.fireflies.ai/graphql`` — not a fictional REST API.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

_OP = re.compile(r"\b(query|mutation)\s+(\w+)", re.I)


class FakeFirefliesAPI:
    def __init__(self):
        self.valid_token: Optional[str] = "ff-test-token"
        self.user = {
            "user_id": "u_edu",
            "email": "edu@acme.com",
            "name": "Edu Caribe",
        }
        self.transcripts: dict[str, dict[str, Any]] = {}
        self.rate_limited = False
        self.graphql_errors: Optional[list[dict[str, Any]]] = None
        self.field_denied: set[str] = set()  # e.g. {"audio_url"}
        self.requests: list[dict[str, Any]] = []

    def add_transcript(
        self,
        tid: str,
        *,
        title: str = "Architecture sync",
        date: Any = "2026-07-15T15:00:00Z",
        summary: Any = ...,
        calendar_id: Optional[str] = "evt_arch_1",
        cal_id: Optional[str] = "evt_arch_1",
        meeting_link: Optional[str] = "https://meet.google.com/abc-defg",
        participants: Optional[list[Any]] = None,
        meeting_attendees: Optional[list[dict[str, Any]]] = None,
        sentences: Optional[list[dict[str, Any]]] = None,
        speakers: Optional[list[dict[str, Any]]] = None,
        host_email: str = "edu@acme.com",
        is_live: bool = False,
        summary_status: str = "processed",
        audio_url: Optional[str] = "https://cdn.example/audio?sig=expiring",
        missing: bool = False,
    ) -> dict[str, Any]:
        if summary is ...:
            summary = {"overview": "Team decided on PostgreSQL.",
                       "short_summary": "Postgres wins."}
        elif isinstance(summary, str):
            summary = {"overview": summary, "short_summary": summary}
        # summary=None means "no provider summary" (tombstone scenarios).
        payload = {
            "id": tid,
            "title": title,
            "date": date,
            "summary": summary,
            "calendar_id": calendar_id,
            "cal_id": cal_id,
            "meeting_link": meeting_link,
            "host_email": host_email,
            "organizer_email": host_email,
            "participants": participants or ["edu@acme.com", "alice@acme.com"],
            "meeting_attendees": meeting_attendees or [
                {"name": "Edu Caribe", "email": "edu@acme.com"},
                {"name": "Alice", "email": "alice@acme.com"},
            ],
            "speakers": speakers or [
                {"name": "Edu Caribe", "id": "sp_edu"},
                {"name": "Alice", "id": "sp_alice"},
            ],
            "sentences": sentences if sentences is not None else [
                {
                    "index": 0,
                    "speaker_name": "Edu Caribe",
                    "speaker_id": "sp_edu",
                    "text": "Should we use Redis for the queue?",
                    "start_time": 0.0,
                    "end_time": 3.0,
                },
                {
                    "index": 1,
                    "speaker_name": "Alice",
                    "speaker_id": "sp_alice",
                    "text": "No — prefer PostgreSQL advisory locks.",
                    "start_time": 3.1,
                    "end_time": 7.0,
                },
                {
                    "index": 2,
                    "speaker_name": "Edu Caribe",
                    "speaker_id": "sp_edu",
                    "text": "Agreed. Decision: PostgreSQL.",
                    "start_time": 7.1,
                    "end_time": 10.0,
                },
            ],
            "duration": 600,
            "audio_url": audio_url,
            "video_url": None,
            "is_live": is_live,
            "meeting_info": {
                "summary_status": summary_status,
                "silent_meeting": False,
                "fred_joined": True,
            },
            "_missing": missing,
        }
        self.transcripts[tid] = payload
        return payload

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        path = url.path.rstrip("/") or "/"
        # Accept /graphql or bare base URL POST "".
        if request.method != "POST":
            return httpx.Response(405, json={"errors": [{"message": "POST only"}]})

        auth = request.headers.get("Authorization", "")
        if self.valid_token is not None and auth != f"Bearer {self.valid_token}":
            return httpx.Response(401, json={
                "errors": [{"message": "auth_failed",
                            "extensions": {"code": "auth_failed"}}],
            })
        if self.rate_limited:
            return httpx.Response(
                429, json={"errors": [{"message": "too_many_requests"}]},
                headers={"Retry-After": "30"},
            )

        try:
            body = json.loads(request.content.decode("utf-8") or "{}")
        except ValueError:
            return httpx.Response(400, json={
                "errors": [{"message": "invalid json"}],
            })
        query = body.get("query") or ""
        variables = body.get("variables") or {}
        self.requests.append({"path": path, "query": query, "variables": variables})

        if self.graphql_errors is not None:
            return httpx.Response(200, json={"errors": self.graphql_errors})

        op_match = _OP.search(query)
        op_name = (op_match.group(2) if op_match else "").lower()

        if "user {" in query.replace("\n", " ") or op_name.endswith("user"):
            return httpx.Response(200, json={"data": {"user": self.user}})

        if "transcripts(" in query or "transcripts {" in query:
            return self._list(variables)

        if "transcript(" in query or op_name.endswith("transcript"):
            return self._one(variables)

        return httpx.Response(200, json={
            "errors": [{"message": f"unknown operation: {op_name or query[:40]}"}],
        })

    def _list(self, variables: dict[str, Any]) -> httpx.Response:
        limit = int(variables.get("limit") or 50)
        skip = int(variables.get("skip") or 0)
        from_date = variables.get("fromDate")
        items = [t for t in self.transcripts.values() if not t.get("_missing")]
        if from_date:
            items = [
                t for t in items
                if str(_norm_date(t.get("date"))) >= str(from_date)
            ]
        items.sort(key=lambda t: str(_norm_date(t.get("date"))))
        page = items[skip: skip + limit]
        stubs = []
        for t in page:
            stubs.append({
                "id": t["id"],
                "title": t.get("title"),
                "date": t.get("date"),
                "duration": t.get("duration"),
                "host_email": t.get("host_email"),
                "organizer_email": t.get("organizer_email"),
                "is_live": t.get("is_live"),
                "meeting_info": t.get("meeting_info"),
            })
        return httpx.Response(200, json={"data": {"transcripts": stubs}})

    def _one(self, variables: dict[str, Any]) -> httpx.Response:
        tid = str(variables.get("transcriptId") or "")
        t = self.transcripts.get(tid)
        if t is None or t.get("_missing"):
            return httpx.Response(200, json={"data": {"transcript": None}})
        out = {k: v for k, v in t.items() if not k.startswith("_")}
        for field in self.field_denied:
            out.pop(field, None)
        return httpx.Response(200, json={"data": {"transcript": out}})


def _norm_date(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
