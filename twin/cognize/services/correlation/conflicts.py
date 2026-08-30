"""Cross-source conflict detection.

Findings are idempotent (``finding_key``) and require distinct sources
supporting incompatible claims. A single record mentioning both ship and
postpone does not create a cross-source finding.
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional

from twin import ids
from twin.clock import now_iso
from twin.store.models import (
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
    r"\b(20\d{2}-\d{2}-\d{2})\b",
    re.I,
)


def _finding_key(
    *, finding_kind: str, episode_id: str, claim_set: str, sources: list[str],
) -> str:
    canon = "|".join(sorted(sources))
    digest = hashlib.sha256(
        f"{finding_kind}|{episode_id}|{claim_set}|{canon}".encode("utf-8"),
    ).hexdigest()[:16]
    return f"corr:{finding_kind}:{episode_id}:{digest}"


def _texts_from_episode(store, episode: WorkEpisode) -> list[tuple[str, str]]:
    """Return list of (source_label, text) for active membership only."""
    out: list[tuple[str, str]] = []
    for ref in episode.source_refs:
        et = ref.get("external_type") or "?"
        eid = ref.get("external_id") or "?"
        label = f"{et}:{eid}"
        rid = ref.get("connector_record_id")
        text = ""
        if rid and hasattr(store, "get_connector_record"):
            rec = store.get_connector_record(rid)
            if rec is not None and not getattr(rec, "deleted", False):
                text = rec.content or ""
        if text:
            out.append((label, text))
    return out


def _upsert_finding(store, finding: ReviewFinding) -> tuple[ReviewFinding, bool]:
    """Insert or refresh by finding_key. Returns (finding, created)."""
    key = (finding.metadata or {}).get("finding_key")
    claim_id = finding.claim_id
    if key and hasattr(store, "get_findings"):
        for existing in store.get_findings(claim_id, unresolved_only=False):
            if (existing.metadata or {}).get("finding_key") == key:
                existing.reason = finding.reason
                existing.confidence = finding.confidence
                existing.metadata = {
                    **(existing.metadata or {}),
                    **(finding.metadata or {}),
                }
                existing.status = FindingStatus.open
                existing.resolved = False
                existing.resolved_at = None
                if hasattr(store, "update_finding"):
                    store.update_finding(existing)
                return existing, False
    store.insert_finding(finding)
    return finding, True


def _close_stale_findings(
    store, episode: WorkEpisode, *, active_keys: set[str],
) -> int:
    closed = 0
    claim_id = f"episode:{episode.id}"
    if not hasattr(store, "get_findings"):
        return 0
    for existing in store.get_findings(claim_id, unresolved_only=True):
        key = (existing.metadata or {}).get("finding_key")
        if not key or not str(key).startswith("corr:"):
            continue
        if key not in active_keys:
            existing.status = FindingStatus.resolved
            existing.resolved = True
            existing.resolved_at = now_iso()
            existing.metadata = {
                **(existing.metadata or {}),
                "resolved_reason": "conflict_no_longer_present",
            }
            if hasattr(store, "update_finding"):
                store.update_finding(existing)
            closed += 1
    return closed


def detect_temporal_conflicts(
    store,
    episode: WorkEpisode,
    *,
    claim_id: Optional[str] = None,
) -> list[ReviewFinding]:
    """Emit/update ``cross_source_temporal_conflict`` findings."""
    texts = _texts_from_episode(store, episode)
    mid = claim_id or f"episode:{episode.id}"
    if len(texts) < 2:
        _close_stale_findings(store, episode, active_keys=set())
        return []

    ship_sources: set[str] = set()
    postpone_sources: set[str] = set()
    dates_by_source: dict[str, set[str]] = {}

    for label, text in texts:
        if _POSTPONE.search(text):
            postpone_sources.add(label)
        if _SHIP.search(text):
            ship_sources.add(label)
        for m in _DATEISH.finditer(text):
            dates_by_source.setdefault(label, set()).add(m.group(0).lower())

    desired: list[ReviewFinding] = []
    active_keys: set[str] = set()

    # Require distinct sources: some source asserts ship, a *different* one postpone.
    if any(s1 != s2 for s1 in ship_sources for s2 in postpone_sources):
        sources = sorted(ship_sources | postpone_sources)
        key = _finding_key(
            finding_kind="ship_vs_postpone",
            episode_id=episode.id,
            claim_set="ship|postpone",
            sources=sources,
        )
        active_keys.add(key)
        desired.append(ReviewFinding(
            id=ids.finding_id(),
            claim_id=mid,
            type=FindingType.cross_source_temporal_conflict,
            status=FindingStatus.open,
            confidence=0.75,
            reason=(
                f"Episode {episode.id}: shipping language and postpone language "
                f"appear across distinct sources — do not auto-pick the newest."
            ),
            suggested_action=SuggestedAction.defer,
            requires_human_review=True,
            created_at=now_iso(),
            analyzer_version="correlation-v2",
            metadata={
                "episode_id": episode.id,
                "vault_id": episode.vault_id,
                "ship_sources": sorted(ship_sources),
                "postpone_sources": sorted(postpone_sources),
                "finding_kind": "cross_source_temporal_conflict",
                "finding_key": key,
            },
        ))

    # Dates: incompatible values across different sources only.
    # Build date → sources; require >=2 dates each with a source that does not
    # also assert the other (simple: at least two sources with disjoint dates).
    if len(dates_by_source) >= 2:
        source_dates = {
            src: frozenset(dates) for src, dates in dates_by_source.items()
        }
        sources = sorted(source_dates)
        conflict = False
        for i, sa in enumerate(sources):
            for sb in sources[i + 1:]:
                if source_dates[sa].isdisjoint(source_dates[sb]):
                    # Both mention dates but share none → possible conflict
                    if source_dates[sa] and source_dates[sb]:
                        conflict = True
                        break
            if conflict:
                break
        if conflict:
            all_dates = sorted({d for ds in source_dates.values() for d in ds})
            key = _finding_key(
                finding_kind="date_mismatch",
                episode_id=episode.id,
                claim_set=",".join(all_dates),
                sources=sources,
            )
            active_keys.add(key)
            desired.append(ReviewFinding(
                id=ids.finding_id(),
                claim_id=mid,
                type=FindingType.cross_source_temporal_conflict,
                status=FindingStatus.open,
                confidence=0.70,
                reason=(
                    f"Episode {episode.id}: conflicting date mentions across sources "
                    f"({', '.join(all_dates[:5])})."
                ),
                suggested_action=SuggestedAction.defer,
                requires_human_review=True,
                created_at=now_iso(),
                analyzer_version="correlation-v2",
                metadata={
                    "episode_id": episode.id,
                    "vault_id": episode.vault_id,
                    "dates": {k: sorted(v) for k, v in dates_by_source.items()},
                    "finding_kind": "cross_source_temporal_conflict",
                    "finding_key": key,
                },
            ))

    out: list[ReviewFinding] = []
    for f in desired:
        saved, _created = _upsert_finding(store, f)
        out.append(saved)
    _close_stale_findings(store, episode, active_keys=active_keys)
    return out
