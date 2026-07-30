"""Normalized host events for native adapters."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

ALLOWED_HOST_EVENT_KINDS = frozenset({
    "session_start",
    "pack_request",
    "user_message",
    "assistant_result",
    "turn_completed",
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
    "turn_completed",
    "tool_requested",
    "tool_completed",
    "tool_failed",
    "file_context",
    "project_context",
})

# Events whose stdout may include a Context Pack for the host
PACK_EMIT_KINDS = frozenset({"session_start", "pack_request"})

# Structural lifecycle markers — observed for replay, never cognitive content.
STRUCTURAL_EVENT_KINDS = frozenset({
    "turn_completed",
    "session_start",
    "session_end",
})


class HostCapabilities(BaseModel):
    """What the host can accept from Twin (provider-agnostic).

    Adapters declare these on ``session_start``. Field defaults and
    ``conservative_default()`` are fail-closed for unknown hosts.
    """

    observe_session: bool = True
    request_context_pack: bool = False
    display_intervention: bool = False
    block_action: bool = False
    modify_action: bool = False
    stream_observations: bool = False
    structured_stdout: bool = True
    supports_session_start: bool = True
    supports_session_end: bool = False
    supports_turn_end: bool = False
    supports_user_message: bool = False
    supports_tool_events: bool = False
    supports_context_injection: bool = False
    context_injection_events: list[str] = Field(default_factory=list)
    supports_parallel_observation: bool = False
    supports_file_context: bool = False

    @classmethod
    def conservative_default(cls) -> "HostCapabilities":
        """Fail-closed profile when a host did not declare capabilities."""
        return cls()

    @classmethod
    def claude_code(cls) -> "HostCapabilities":
        """Claude Code hook surface — session/turn/user/tool + pack injection."""
        return cls(
            observe_session=True,
            request_context_pack=True,
            display_intervention=True,
            stream_observations=True,
            structured_stdout=True,
            supports_session_start=True,
            supports_session_end=True,
            supports_turn_end=True,
            supports_user_message=True,
            supports_tool_events=True,
            supports_context_injection=True,
            context_injection_events=["session_start", "user_message"],
            supports_parallel_observation=False,
            supports_file_context=False,
        )

    @classmethod
    def fake_host(cls) -> "HostCapabilities":
        """Portable eval host — same injection surface as Claude Code."""
        return cls.claude_code()


# Back-compat alias for adapter imports.
CLAUDE_CODE_CAPABILITIES = HostCapabilities.claude_code()


class HostEvent(BaseModel):
    """Provider-agnostic host observation."""

    kind: str
    host_type: str = "native"
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
