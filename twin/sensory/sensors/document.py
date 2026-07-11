"""Document Sensor — markdown / plain technical docs."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ...clock import now_iso
from ..base import Sensor
from ..percept import Percept


def _front_matter(text: str) -> tuple[dict, str]:
    """Very small YAML front matter reader (key: value lines only)."""
    meta: dict = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            block = text[3:end]
            for line in block.strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            text = text[end + 4:]
    return meta, text.lstrip("\n")


class DocumentSensor(Sensor):
    name = "document"

    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() in (".md", ".markdown")

    def sense(self, path: Path) -> Iterable[Percept]:
        raw = path.read_text(encoding="utf-8")
        meta, body = _front_matter(raw)
        percept = Percept(
            percept_type="document",
            source_sensor=self.name,
            occurred_at=meta.get("date"),
            ingested_at=now_iso(),
            actors=[meta["author"]] if meta.get("author") else [],
            content=body,
            content_refs=[{"kind": "file", "path": str(path)}],
            privacy_hints={"domain_hint": "technical"},
            metadata=meta,
            # authored technical docs: high trust, technical scope
            source_trust=0.9,
            source_scope="technical",
            source_confidentiality="internal",
        )
        yield percept.seal()
