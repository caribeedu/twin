"""Slack Sensor — standard Slack channel export (list of message dicts)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from ...clock import now_iso
from ..base import Sensor
from ..percept import Percept


class SlackSensor(Sensor):
    name = "slack"

    def can_handle(self, path: Path) -> bool:
        if path.suffix.lower() != ".json":
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False
        return isinstance(data, list)

    def sense(self, path: Path) -> Iterable[Percept]:
        data = json.loads(path.read_text(encoding="utf-8"))
        lines: list[str] = []
        actors: set[str] = set()
        for msg in data:
            if not isinstance(msg, dict) or not msg.get("text"):
                continue
            user = (
                (msg.get("user_profile") or {}).get("real_name")
                or msg.get("user")
                or "?"
            )
            actors.add(user)
            lines.append(f"{user}: {msg['text']}")
        yield Percept(
            percept_type="slack_thread",
            source_sensor=self.name,
            ingested_at=now_iso(),
            actors=sorted(actors),
            content="\n".join(lines),
            content_refs=[{"kind": "file", "path": str(path)}],
            privacy_hints={"domain_hint": "work"},
            # informal chat: lower trust, may contain third-party content
            source_trust=0.6,
            source_scope="work",
            source_confidentiality="private",
        ).seal()
