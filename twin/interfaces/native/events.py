"""Normalized host events for native adapters."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class HostEvent(BaseModel):
    """Provider-agnostic host observation."""

    kind: str
    # session_start | user_message | assistant_result | tool_execution
    # | file_context | project_context | session_end | pack_request
    # | intervene_check
    host_type: str = "claude-code"
    external_session_id: str = ""
    text: str = ""
    ref: Optional[str] = None
    cwd: Optional[str] = None
    project: Optional[str] = None
    domain: Optional[str] = None
    task_profile: Optional[str] = None
    summary: str = ""
    abandoned: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
