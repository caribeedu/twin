"""Cross-source conflict detection (v0.6 Phase 7 §72)."""

from __future__ import annotations

import re
from typing import Optional

from ... import ids
from ...clock import now_iso
from ...memory.models import (
    FindingStatus,
    FindingType,
    ReviewFinding,
    SuggestedAction,
)
from .models import WorkEpisode

_POSTPONE = re.compile(
    r"\b(postpon(?:e|ed)|delay(?:ed)?|slip(?:ped)?|push(?:ed)?\s+back|"
    r"moved\s+to|reschedul)\b",
    re.I,
)
_SHIP = re.compile(
    r"\b(ship(?:ping)?|release|launch|deploy|due|deadline|friday|monday|"
    r"tuesday|wednesday|thursday|saturday|sunday)\b",
    re.I,
)
_DATEISH = re.compile(
    r"\b(20\d{2}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2})\b",
    re.I,
)


def _texts_from_episode(store, episode: WorkEpisode) -> list[tuple[str, str, str]]:
    """Return list of (source_label, external_id, text)."""
    out: list[tuple[str, str, str]] = []
    for ref in episode.source_refs:
        et = ref.get("external_type") or "?"
        eid = ref.get("external_id") or "?"
        rid = ref.get("connector_record_id")
        text = ""
        if rid and hasattr(store, "get_connector_record"):
            rec = store.get_connector_record(rid)
            if rec is not None:
                text = rec.content or ""
        if text:
            out.append((et, eid, text))
    return out


def detect_temporal_conflicts(
    store,
    episode: WorkEpisode,
    *,
    memory_id: Optional[str] = None,
) -> list[ReviewFinding]:
    """Emit ``cross_source_temporal_conflict`` findings — never auto-resolve."""
    texts = _texts_from_episode(store, episode)
    if len(texts) < 2:
        return []

    ship_sources: list[str] = []
    postpone_sources: list[str] = []
    dated: list[tuple[str, str]] = []

    for et, eid, text in texts:
        label = f"{et}:{eid}"
        if _POSTPONE.search(text):
            postpone_sources.append(label)
        if _SHIP.search(text):
            ship_sources.append(label)
        for m in _DATEISH.finditer(text):
            dated.append((label, m.group(0).lower()))

    findings: list[ReviewFinding] = []

    if ship_sources and postpone_sources:
        findings.append(ReviewFinding(
            id=ids.finding_id(),
            memory_id=memory_id or f"episode:{episode.id}",
            type=FindingType.cross_source_temporal_conflict,
            status=FindingStatus.open,
            confidence=0.75,
            reason=(
                f"Episode {episode.id}: shipping language and postpone language "
                f"appear across sources — do not auto-pick the newest."
            ),
            suggested_action=SuggestedAction.defer,
            requires_human_review=True,
            created_at=now_iso(),
            analyzer_version="correlation-v1",
            metadata={
                "episode_id": episode.id,
                "ship_sources": ship_sources,
                "postpone_sources": postpone_sources,
                "finding_kind": "cross_source_temporal_conflict",
            },
        ))

    by_date: dict[str, set[str]] = {}
    for label, date_s in dated:
        by_date.setdefault(date_s, set()).add(label)
    if len(by_date) >= 2:
        findings.append(ReviewFinding(
            id=ids.finding_id(),
            memory_id=memory_id or f"episode:{episode.id}",
            type=FindingType.cross_source_temporal_conflict,
            status=FindingStatus.open,
            confidence=0.70,
            reason=(
                f"Episode {episode.id}: conflicting date mentions across sources "
                f"({', '.join(sorted(by_date)[:5])})."
            ),
            suggested_action=SuggestedAction.defer,
            requires_human_review=True,
            created_at=now_iso(),
            analyzer_version="correlation-v1",
            metadata={
                "episode_id": episode.id,
                "dates": {k: sorted(v) for k, v in by_date.items()},
                "finding_kind": "cross_source_temporal_conflict",
            },
        ))

    for f in findings:
        store.insert_finding(f)
    return findings
