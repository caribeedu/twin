"""Offline Google Calendar API v3 double for connector tests."""
from __future__ import annotations

from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlparse

import httpx


class FakeCalendarAPI:
    def __init__(self):
        self.valid_token: Optional[str] = "ya29.cal-test-token"
        self.email = "edu@acme.com"
        self.calendars: dict[str, dict[str, Any]] = {
            "primary": {
                "id": "primary",
                "summary": "Edu Caribe",
                "primary": True,
                "accessRole": "owner",
            },
            "work@acme.com": {
                "id": "work@acme.com",
                "summary": "Work",
                "primary": False,
                "accessRole": "owner",
            },
        }
        # calendar_id → event_id → event
        self.events: dict[str, dict[str, dict[str, Any]]] = {
            "primary": {},
            "work@acme.com": {},
        }
        self.rate_limited = False
        self.requests: list[str] = []

    def add_event(
        self,
        event_id: str,
        *,
        calendar_id: str = "primary",
        summary: str = "Sync",
        start: str = "2026-07-15T15:00:00Z",
        end: str = "2026-07-15T16:00:00Z",
        updated: str = "2026-07-15T14:00:00Z",
        status: str = "confirmed",
        organizer: str = "edu@acme.com",
        attendees: Optional[list[str]] = None,
        description: str = "",
        hangout_link: Optional[str] = None,
        ical_uid: Optional[str] = None,
        etag: Optional[str] = None,
        transparency: str = "opaque",
    ) -> dict[str, Any]:
        ev: dict[str, Any] = {
            "id": event_id,
            "summary": summary,
            "status": status,
            "updated": updated,
            "etag": etag or f'"{event_id}-{updated}"',
            "iCalUID": ical_uid or f"{event_id}@google.com",
            "transparency": transparency,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
            "organizer": {"email": organizer},
            "attendees": [
                {"email": a} for a in (attendees or ["alice@acme.com", organizer])
            ],
            "description": description,
        }
        if hangout_link:
            ev["hangoutLink"] = hangout_link
        self.events.setdefault(calendar_id, {})[event_id] = ev
        return ev

    def cancel_event(self, event_id: str, *, calendar_id: str = "primary") -> None:
        ev = self.events[calendar_id][event_id]
        ev["status"] = "cancelled"
        ev["updated"] = "2026-07-16T12:00:00Z"
        ev["etag"] = f'"{event_id}-cancelled"'

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        path = url.path.lstrip("/")
        if path.startswith("calendar/v3/"):
            path = path[len("calendar/v3/"):]
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.requests.append(path + (f"?{url.query}" if url.query else ""))

        auth = request.headers.get("Authorization", "")
        if self.valid_token is not None and auth != f"Bearer {self.valid_token}":
            return httpx.Response(401, json={
                "error": {"message": "Invalid Credentials"},
            })
        if self.rate_limited:
            return httpx.Response(
                429, json={"error": {"message": "Rate Limit Exceeded"}},
                headers={"Retry-After": "60"},
            )

        if path == "users/me/calendarList":
            items = list(self.calendars.values())
            page_size = int(params.get("maxResults") or 100)
            page_token = params.get("pageToken")
            offset = int(page_token.split(":", 1)[1]) if (
                page_token and page_token.startswith("p:")
            ) else 0
            page = items[offset: offset + page_size]
            body: dict[str, Any] = {"items": page}
            if offset + page_size < len(items):
                body["nextPageToken"] = f"p:{offset + page_size}"
            return httpx.Response(200, json=body)

        # calendars/{id}/events
        if path.startswith("calendars/") and path.endswith("/events"):
            raw_id = path[len("calendars/"):-len("/events")]
            cal_id = unquote(raw_id)
            items = list(self.events.get(cal_id, {}).values())
            updated_min = params.get("updatedMin")
            if updated_min:
                items = [
                    e for e in items
                    if str(e.get("updated") or "") >= updated_min
                ]
            items.sort(key=lambda e: str(e.get("updated") or ""))
            page_token = params.get("pageToken")
            page_size = int(params.get("maxResults") or 50)
            if page_token and page_token.startswith("p:"):
                offset = int(page_token.split(":", 1)[1])
            else:
                offset = 0
            page = items[offset: offset + page_size]
            next_token = None
            if offset + page_size < len(items):
                next_token = f"p:{offset + page_size}"
            body: dict[str, Any] = {"items": page}
            if next_token:
                body["nextPageToken"] = next_token
            return httpx.Response(200, json=body)

        return httpx.Response(404, json={"error": {"message": "Not Found"}})
