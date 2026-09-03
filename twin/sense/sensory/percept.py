"""Percept — the normalized unit of perception.

Every sensor, whatever it senses, emits Percepts. This is the boundary
contract between the Sensory Layer and the Cognitive Core: downstream code
never sees sensor-specific formats.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from twin import ids


class SourceClass(str, Enum):
    code_repo = "code_repo"
    chat_discussion = "chat_discussion"
    meeting = "meeting"
    mail = "mail"
    calendar = "calendar"
    document = "document"
    session_residue = "session_residue"
    unknown = "unknown"


_SENSOR_TO_SOURCE_CLASS: dict[str, SourceClass] = {
    "github": SourceClass.code_repo,
    "slack": SourceClass.chat_discussion,
    "meeting": SourceClass.meeting,
    "fireflies": SourceClass.meeting,
    "gmail": SourceClass.mail,
    "mail": SourceClass.mail,
    "outlook": SourceClass.mail,
    "calendar": SourceClass.calendar,
    "document": SourceClass.document,
    "folder": SourceClass.document,
    "session": SourceClass.session_residue,
    "native": SourceClass.session_residue,
}


def infer_source_class(
    *,
    source_sensor: str = "",
    percept_type: str = "",
    explicit: Optional[str] = None,
) -> SourceClass:
    if explicit:
        try:
            return SourceClass(explicit)
        except ValueError:
            pass
    sensor = (source_sensor or "").lower()
    if sensor in _SENSOR_TO_SOURCE_CLASS:
        return _SENSOR_TO_SOURCE_CLASS[sensor]
    ptype = (percept_type or "").lower()
    if "slack" in ptype or "chat" in ptype or "message" in ptype:
        return SourceClass.chat_discussion
    if "pr" in ptype or "commit" in ptype or "github" in ptype:
        return SourceClass.code_repo
    if "meeting" in ptype or "transcript" in ptype:
        return SourceClass.meeting
    if "mail" in ptype or "email" in ptype:
        return SourceClass.mail
    if "calendar" in ptype or "event" in ptype:
        return SourceClass.calendar
    if "document" in ptype or "file" in ptype:
        return SourceClass.document
    if "session" in ptype:
        return SourceClass.session_residue
    return SourceClass.unknown


class Percept(BaseModel):
    id: str = Field(default_factory=lambda: ids.new_id("pct"))
    percept_type: str            # document | meeting_transcript | meeting | slack_thread | ...
    source_sensor: str           # sensor name that produced it (document, meeting, slack, ...)
    source_class: SourceClass = SourceClass.unknown
    occurred_at: Optional[str] = None   # when the sensed thing happened
    ingested_at: str = ""               # when the sensor captured it
    actors: list[str] = Field(default_factory=list)  # people involved (speakers, authors)
    content: str = ""                   # normalized plain text — what cognition reads
    content_refs: list[dict[str, Any]] = Field(default_factory=list)  # pointers to the raw signal
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    privacy_hints: dict[str, Any] = Field(default_factory=dict)  # {domain_hint, sensitivity_hint}
    integrity: dict[str, Any] = Field(default_factory=dict)      # {content_hash, size_bytes}
    metadata: dict[str, Any] = Field(default_factory=dict)
    # -- source qualification ----------------------------------------------
    # how much extracted memories from this source can be trusted (0..1);
    # scales the confidence of everything derived from the percept
    source_trust: float = 0.8
    # which life scope the source belongs to (work | technical | personal | ...)
    source_scope: str = "work"
    # confidentiality floor: memories derived from this percept can never be
    # LESS sensitive than this (public | internal | private | restricted)
    source_confidentiality: str = "internal"
    # explicit project link (resolved by sensors/sessions when known)
    project_id: Optional[str] = None
    # set when Cognize successfully processes this percept in a batch
    cognized_at: Optional[str] = None

    def model_post_init(self, __context: Any) -> None:
        if self.source_class is SourceClass.unknown:
            inferred = infer_source_class(
                source_sensor=self.source_sensor,
                percept_type=self.percept_type,
            )
            if inferred is not SourceClass.unknown:
                object.__setattr__(self, "source_class", inferred)

    def seal(self) -> "Percept":
        """Fill integrity fields from content (idempotent)."""
        self.integrity.setdefault(
            "content_hash", hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        )
        self.integrity.setdefault("size_bytes", len(self.content.encode("utf-8")))
        return self

    @property
    def content_hash(self) -> str:
        return self.integrity.get("content_hash", "")
