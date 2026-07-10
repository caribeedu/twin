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
