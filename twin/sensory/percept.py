"""Percept — the normalized unit of perception.

Every sensor, whatever it senses, emits Percepts. This is the boundary
contract between the Sensory Layer and the Cognitive Core: downstream code
never sees sensor-specific formats.
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from pydantic import BaseModel, Field

from .. import ids


class Percept(BaseModel):
    id: str = Field(default_factory=lambda: ids.new_id("pct"))
    percept_type: str            # document | meeting_transcript | meeting | slack_thread | ...
    source_sensor: str           # sensor name that produced it (document, meeting, slack, ...)
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
