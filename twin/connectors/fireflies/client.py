"""Fireflies GraphQL client (read-only transcripts).

Real protocol: ``POST https://api.fireflies.ai/graphql`` with Bearer API key.
See https://docs.fireflies.ai/ — mocks must imitate this shape, not invent REST.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from ..models import FailureClass
from ..protocol import ConnectorError

FIREFLIES_API = "https://api.fireflies.ai/graphql"

_USER_QUERY = """
query TwinUser {
  user { user_id email name }
}
"""

# fromDate is an ISO-8601 DateTime scalar per Fireflies docs.
_TRANSCRIPTS_LIST_QUERY = """
query TwinTranscripts($limit: Int, $skip: Int, $fromDate: DateTime) {
  transcripts(limit: $limit, skip: $skip, fromDate: $fromDate) {
    id
    title
    date
    duration
    host_email
    organizer_email
    is_live
    meeting_info { summary_status silent_meeting fred_joined }
  }
}
"""

_TRANSCRIPT_QUERY = """
query TwinTranscript($transcriptId: String!) {
  transcript(id: $transcriptId) {
    id
    title
    date
    duration
    host_email
    organizer_email
    participants
    calendar_id
    cal_id
    meeting_link
    audio_url
    video_url
    transcript_url
    is_live
    speakers { id name }
    meeting_attendees { displayName email name }
    meeting_info { summary_status silent_meeting fred_joined }
    sentences {
      index
      speaker_name
      speaker_id
      text
      start_time
      end_time
    }
    summary {
      overview
      short_summary
      short_overview
      action_items
      gist
    }
  }
}
"""


def _build_http(base_url: str, token: Optional[str]) -> httpx.Client:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "twin-connector-fireflies",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    # GraphQL endpoint is a single URL; do not force a trailing-slash join.
    root = base_url.rstrip("/")
    return httpx.Client(base_url=root, headers=headers, timeout=60)


class FirefliesClient:
    def __init__(self, token: Optional[str], *,
                 base_url: str = FIREFLIES_API, http: Optional[httpx.Client] = None):
        self._http = http or _build_http(base_url, token)

    def close(self) -> None:
        self._http.close()

    def graphql(
        self, query: str, variables: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """POST a GraphQL operation; raise on HTTP or GraphQL ``errors``."""
        try:
            resp = self._http.post(
                "",
                json={"query": query, "variables": variables or {}},
            )
        except httpx.HTTPError as exc:
            raise ConnectorError(
                f"fireflies network error: {type(exc).__name__}",
                failure_class=FailureClass.network, retryable=True,
            ) from exc
        return self._decode(resp)

    def _decode(self, resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code == 429:
            retry = resp.headers.get("Retry-After", "60")
            raise ConnectorError(
                "fireflies rate limit exhausted",
                failure_class=FailureClass.rate_limit, retryable=True,
                retry_after=int(retry) if str(retry).isdigit() else 60,
            )
        if resp.status_code in (401, 403):
            raise ConnectorError(
                "fireflies credential rejected",
                failure_class=(FailureClass.authentication if resp.status_code == 401
                               else FailureClass.authorization),
                human_action_required=True,
            )
        if resp.status_code >= 500:
            raise ConnectorError(
                f"fireflies server error ({resp.status_code})",
                failure_class=FailureClass.provider_error, retryable=True,
            )
        try:
            body = resp.json()
        except ValueError as exc:
            raise ConnectorError(
                "fireflies returned a non-JSON body",
                failure_class=FailureClass.schema_change,
            ) from exc
        if not isinstance(body, dict):
            raise ConnectorError(
                "fireflies returned a non-object payload",
                failure_class=FailureClass.schema_change,
            )
        errors = body.get("errors")
        if errors:
            first = errors[0] if isinstance(errors, list) and errors else errors
            msg = (
                first.get("message") if isinstance(first, dict) else str(first)
            )
            code = ""
            if isinstance(first, dict):
                ext = first.get("extensions") or {}
                code = str(ext.get("code") or ext.get("error_code") or "")
            low = (msg or "").lower()
            if "auth" in low or code in ("auth_failed", "unauthenticated"):
                raise ConnectorError(
                    f"fireflies auth error: {msg}",
                    failure_class=FailureClass.authentication,
                    human_action_required=True,
                )
            if "permission" in low or "forbidden" in low or code in (
                "forbidden", "unauthorized",
            ):
                raise ConnectorError(
                    f"fireflies authorization error: {msg}",
                    failure_class=FailureClass.authorization,
                    human_action_required=True,
                )
            if "rate" in low or "too_many" in low:
                raise ConnectorError(
                    f"fireflies rate limit: {msg}",
                    failure_class=FailureClass.rate_limit, retryable=True,
                    retry_after=60,
                )
            raise ConnectorError(
                f"fireflies graphql error: {msg}",
                failure_class=FailureClass.provider_error,
            )
        data = body.get("data")
        if data is None:
            raise ConnectorError(
                "fireflies graphql response missing data",
                failure_class=FailureClass.schema_change,
            )
        if not isinstance(data, dict):
            raise ConnectorError(
                "fireflies graphql data is not an object",
                failure_class=FailureClass.schema_change,
            )
        return data

    def me(self) -> dict[str, Any]:
        data = self.graphql(_USER_QUERY)
        user = data.get("user") or {}
        if not isinstance(user, dict):
            raise ConnectorError(
                "fireflies user payload unexpected",
                failure_class=FailureClass.schema_change,
            )
        return user

    def list_transcripts(
        self, *,
        from_date: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], Optional[int]]:
        """Return stubs and next ``skip`` (None when exhausted). Max limit 50."""
        limit = max(1, min(int(limit), 50))
        variables: dict[str, Any] = {"limit": limit, "skip": int(skip)}
        if from_date:
            variables["fromDate"] = from_date
        data = self.graphql(_TRANSCRIPTS_LIST_QUERY, variables)
        items = list(data.get("transcripts") or [])
        if len(items) >= limit:
            return items, int(skip) + len(items)
        return items, None

    def get_transcript(self, transcript_id: str) -> Optional[dict[str, Any]]:
        data = self.graphql(
            _TRANSCRIPT_QUERY, {"transcriptId": str(transcript_id)},
        )
        tr = data.get("transcript")
        if tr is None:
            return None
        if not isinstance(tr, dict):
            raise ConnectorError(
                "fireflies transcript payload unexpected",
                failure_class=FailureClass.schema_change,
            )
        return tr
