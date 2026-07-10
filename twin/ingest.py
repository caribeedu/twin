"""Ingestion: load markdown docs, meeting transcripts (txt), meeting exports
(json, Fireflies/Meetily-style) and Slack exports (json) into normalized
``Source`` rows. Raw text is kept verbatim as evidence; extraction happens in
a later stage.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

from . import ids
from .db import Database, now_iso
from .models import Source

SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".json"}


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


def load_markdown(path: Path) -> Source:
    raw = path.read_text(encoding="utf-8")
    meta, body = _front_matter(raw)
    return Source(
        id=ids.source_id(),
        source_type="markdown",
        path=str(path),
        author=meta.get("author"),
        created_at=meta.get("date"),
        raw_text=body,
        metadata=meta,
        content_hash=_hash(raw),
        ingested_at=now_iso(),
    )


_SPEAKER_RE = re.compile(r"^([A-Za-zÀ-ÿ .'-]{2,40}):\s", re.MULTILINE)


def load_transcript(path: Path) -> Source:
    raw = path.read_text(encoding="utf-8")
    participants = sorted({m.group(1).strip() for m in _SPEAKER_RE.finditer(raw)})
    return Source(
        id=ids.source_id(),
        source_type="meeting_transcript",
        path=str(path),
        participants=participants,
        raw_text=raw,
        content_hash=_hash(raw),
        ingested_at=now_iso(),
    )


def load_meeting_json(path: Path, data: dict) -> Source:
    """Fireflies/Meetily-style export: {title, date, participants, sentences|transcript}."""
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
    raw_text = f"# {title}\n" + "\n".join(lines)
    return Source(
        id=ids.source_id(),
        source_type="meeting_json",
        path=str(path),
        participants=list(data.get("participants", [])),
        created_at=data.get("date"),
        raw_text=raw_text,
        metadata={"title": title},
        content_hash=_hash(json.dumps(data, sort_keys=True)),
        ingested_at=now_iso(),
    )


def load_slack_json(path: Path, data: list) -> Source:
    """Slack export: a list of {user|user_profile, ts, text} messages."""
    lines: list[str] = []
    participants: set[str] = set()
    for msg in data:
        if not isinstance(msg, dict) or not msg.get("text"):
            continue
        user = (
            (msg.get("user_profile") or {}).get("real_name")
            or msg.get("user")
            or "?"
        )
        participants.add(user)
        lines.append(f"{user}: {msg['text']}")
    return Source(
        id=ids.source_id(),
        source_type="slack",
        path=str(path),
        participants=sorted(participants),
        raw_text="\n".join(lines),
        content_hash=_hash(json.dumps(data, sort_keys=True)),
        ingested_at=now_iso(),
    )


def load_file(path: Path) -> Source:
    suffix = path.suffix.lower()
    if suffix in (".md", ".markdown"):
        return load_markdown(path)
    if suffix == ".txt":
        return load_transcript(path)
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return load_slack_json(path, data)
        return load_meeting_json(path, data)
    raise ValueError(f"Unsupported file type: {path}")


def ingest_paths(db: Database, paths: list[str | Path]) -> tuple[list[str], list[str]]:
    """Ingest files and/or directories. Returns (new_source_ids, skipped_paths)."""
    new_ids: list[str] = []
    skipped: list[str] = []
    files: list[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            files.extend(sorted(f for f in p.rglob("*") if f.suffix.lower() in SUPPORTED_SUFFIXES))
        elif p.is_file():
            files.append(p)
        else:
            skipped.append(str(p))
    for f in files:
        try:
            src = load_file(f)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            skipped.append(str(f))
            continue
        if db.insert_source(src) is None:
            skipped.append(f"{f} (duplicate)")
        else:
            new_ids.append(src.id)
    return new_ids, skipped
