"""Normalized host events for native adapters."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

ALLOWED_HOST_EVENT_KINDS = frozenset({
    "session_start",
    "pack_request",
    "user_message",
    "assistant_result",
    "tool_requested",
    "tool_completed",
    "tool_failed",
    "file_context",
    "project_context",
    "intervene_check",
    "session_end",
    "unsupported_host_event",
})

# Kinds that may attach artifacts to an active CognitiveSession
OBSERVATION_KINDS = frozenset({
    "session_start",
    "user_message",
    "assistant_result",
    "tool_requested",
    "tool_completed",
    "tool_failed",
    "file_context",
    "project_context",
})

# Events whose stdout may include a Context Pack for the host
PACK_EMIT_KINDS = frozenset({"session_start", "pack_request"})


class HostCapabilities(BaseModel):
    """What the host can accept from Twin (Phase 8: Claude Code proof)."""

    observe_session: bool = True
    request_context_pack: bool = True
    display_intervention: bool = True
    block_action: bool = False
    modify_action: bool = False
    stream_observations: bool = True
    structured_stdout: bool = True


CLAUDE_CODE_CAPABILITIES = HostCapabilities()


class HostEvent(BaseModel):
    """Provider-agnostic host observation."""

    kind: str
    host_type: str = "claude-code"
    external_session_id: str = ""
    event_id: Optional[str] = None
    delivery_id: Optional[str] = None
    occurred_at: Optional[str] = None
    sequence: Optional[int] = None
    tool_call_id: Optional[str] = None
    tool_phase: Optional[str] = None  # before | after | failed
    text: str = ""
    ref: Optional[str] = None
    cwd: Optional[str] = None
    project: Optional[str] = None
    domain: Optional[str] = None
    task_profile: Optional[str] = None
    persona: Optional[str] = None
    purpose: Optional[str] = None
    audience: Optional[str] = None
    summary: str = ""
    abandoned: bool = False
    redacted: bool = False
    redaction_categories: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
