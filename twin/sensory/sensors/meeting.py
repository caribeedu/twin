"""Meeting Sensor — transcript .txt files and Fireflies/Meetily-style
JSON exports."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

from ...clock import now_iso
from ..base import Sensor
from ..percept import Percept

_SPEAKER_RE = re.compile(r"^([A-Za-zÀ-ÿ .'-]{2,40}):\s", re.MULTILINE)


class MeetingSensor(Sensor):
    name = "meeting"

    def can_handle(self, path: Path) -> bool:
        if path.suffix.lower() == ".txt":
            return True
        if path.suffix.lower() == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return False
            return isinstance(data, dict) and (
                "sentences" in data or "transcript" in data
            )
        return False

    def sense(self, path: Path) -> Iterable[Percept]:
        if path.suffix.lower() == ".txt":
            yield self._sense_transcript(path)
        else:
            yield self._sense_json(path)

    def _sense_transcript(self, path: Path) -> Percept:
        raw = path.read_text(encoding="utf-8")
        actors = sorted({m.group(1).strip() for m in _SPEAKER_RE.finditer(raw)})
        return Percept(
            percept_type="meeting_transcript",
            source_sensor=self.name,
            ingested_at=now_iso(),
            actors=actors,
            content=raw,
            content_refs=[{"kind": "file", "path": str(path)}],
            privacy_hints={"domain_hint": "work"},
        ).seal()

    def _sense_json(self, path: Path) -> Percept:
        data = json.loads(path.read_text(encoding="utf-8"))
        lines: list[str] = []
        sentences = data.get("sentences") or data.get("transcript") or []
        if isinstance(sentences, list):
            for s in sentences:
                if isinstance(s, dict):
                    speaker = s.get("speaker") or s.get("speaker_name") or "?"
                    text = s.get("text") or s.get("sentence") or ""
                    lines.append(f"{speaker}: {text}")
                else:
                    lines.append(str(s))
        elif isinstance(sentences, str):
            lines.append(sentences)
        if data.get("summary"):
            lines.insert(0, f"[summary] {data['summary']}")
        title = data.get("title", path.stem)
        return Percept(
            percept_type="meeting",
            source_sensor=self.name,
            occurred_at=data.get("date"),
            ingested_at=now_iso(),
            actors=list(data.get("participants", [])),
            content=f"# {title}\n" + "\n".join(lines),
            content_refs=[{"kind": "file", "path": str(path)}],
            privacy_hints={"domain_hint": "work"},
            metadata={"title": title},
        ).seal()
