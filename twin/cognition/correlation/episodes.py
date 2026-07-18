"""WorkEpisode correlation across connectors (v0.6 Phase 7 §19)."""

from __future__ import annotations

import re
from typing import Any, Optional

from ...clock import now_iso
from .models import EpisodeLink, EpisodeLinkKind, EpisodeStatus, WorkEpisode
from .projects import resolve_project_for_record

# Explicit / reference links may form an episode. Soft links stay candidates.
EPISODE_MERGE_CONFIDENCE = 0.75

_REPO_PR = re.compile(
    r"github\.com/([\w.-]+/[\w.-]+)/(?:pull|issues)/(\d+)",
    re.I,
)
_LABELED_NUM = re.compile(r"\b(?:PR|pr|issue|Issue)\s*#(\d+)\b")


def extract_github_refs(text: str, *, default_repo: Optional[str] = None) -> list[str]:
    """Return lineage-root style keys like ``github:org/repo#42``."""
    out: list[str] = []
    for m in _REPO_PR.finditer(text or ""):
        key = f"github:{m.group(1)}#{m.group(2)}"
        if key not in out:
            out.append(key)
    if default_repo:
        for m in _LABELED_NUM.finditer(text or ""):
            key = f"github:{default_repo}#{m.group(1)}"
            if key not in out:
                out.append(key)
    return out


class _UF:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, x: str) -> None:
        self.parent.setdefault(x, x)

    def find(self, x: str) -> str:
        self.add(x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _record_keys(record: Any) -> list[tuple[str, EpisodeLinkKind, float]]:
    """Anchors that may join records into one episode."""
    keys: list[tuple[str, EpisodeLinkKind, float]] = []
    sm = getattr(record, "source_metadata", None) or {}
    eid = getattr(record, "external_id", "") or ""
    et = getattr(record, "external_type", "") or ""

    lineage = sm.get("lineage_root")
    if lineage:
        keys.append((f"lineage:{lineage}", EpisodeLinkKind.explicit, 0.95))
    for field, kind, conf in (
        ("notification_of", EpisodeLinkKind.derived, 0.95),
        ("correlation_fingerprint", EpisodeLinkKind.fingerprint, 0.85),
        ("calendar_event_id", EpisodeLinkKind.explicit, 0.95),
        ("iCalUID", EpisodeLinkKind.explicit, 0.90),
    ):
        val = sm.get(field)
        if val:
            keys.append((f"{field}:{val}", kind, conf))

    thread = getattr(record, "thread_key", None)
    if thread:
        keys.append((f"thread:{thread}", EpisodeLinkKind.thread, 0.80))

    content = getattr(record, "content", "") or ""
    repo = sm.get("repo")
    for ref in extract_github_refs(content, default_repo=repo):
        keys.append((f"lineage:{ref}", EpisodeLinkKind.reference, 0.88))

    # Self key so isolated records still form singleton episodes when asked.
    keys.append((f"self:{et}:{eid}", EpisodeLinkKind.soft, 0.40))
    return keys


def _source_ref(record: Any) -> dict[str, Any]:
    sm = getattr(record, "source_metadata", None) or {}
    return {
        "connector_record_id": getattr(record, "id", None),
        "connector_id": getattr(record, "connector_id", None),
        "source_account_id": getattr(record, "source_account_id", None),
        "external_type": getattr(record, "external_type", None),
        "external_id": getattr(record, "external_id", None),
        "thread_key": getattr(record, "thread_key", None),
        "lineage_root": sm.get("lineage_root"),
        "occurred_at": getattr(record, "occurred_at", None),
        "project_hint": getattr(record, "project_hint", None),
    }


def correlate_records(
    store,
    records: list[Any],
    *,
    min_confidence: float = EPISODE_MERGE_CONFIDENCE,
    create_singletons: bool = False,
) -> list[WorkEpisode]:
    """Cluster connector records into WorkEpisodes.

    Soft-only clusters (confidence < min_confidence) are not materialised
    unless ``create_singletons`` is set — low-confidence automatic links must
    not consolidate evidence as independent.
    """
    if not records:
        return []

    uf = _UF()
    edge_meta: dict[tuple[str, str], tuple[EpisodeLinkKind, float]] = {}
    record_by_id: dict[str, Any] = {}
    keys_by_record: dict[str, list[tuple[str, EpisodeLinkKind, float]]] = {}

    for rec in records:
        rid = getattr(rec, "id", None) or getattr(rec, "external_id", None)
        if not rid:
            continue
        record_by_id[rid] = rec
        keys = _record_keys(rec)
        keys_by_record[rid] = keys
        for key, kind, conf in keys:
            uf.add(key)
            # Track best edge kind for this key←record (via key identity)
            edge_meta[(rid, key)] = (kind, conf)

    # Union keys that co-occur on the same record (and across records via shared keys)
    key_owners: dict[str, list[str]] = {}
    for rid, keys in keys_by_record.items():
        strong_keys = [k for k, kind, conf in keys if conf >= min_confidence]
        for i, ka in enumerate(strong_keys):
            for kb in strong_keys[i + 1:]:
                uf.union(ka, kb)
            key_owners.setdefault(ka, []).append(rid)
        for key, kind, conf in keys:
            if conf >= min_confidence:
                key_owners.setdefault(key, []).append(rid)

    # Union all records that share a strong key's component
    components: dict[str, set[str]] = {}
    for key, owners in key_owners.items():
        root = uf.find(key)
        components.setdefault(root, set()).update(owners)

    episodes: list[WorkEpisode] = []
    for _root, member_ids in components.items():
        members = [record_by_id[r] for r in member_ids if r in record_by_id]
        if len(members) < 2 and not create_singletons:
            continue

        # Confidence = max edge among members' strong keys
        conf = 0.0
        kinds: list[str] = []
        for rid in member_ids:
            for key, kind, c in keys_by_record.get(rid, []):
                if c >= min_confidence:
                    conf = max(conf, c)
                    kinds.append(kind.value)

        if conf < min_confidence and not create_singletons:
            continue

        # Prefer existing episode with overlapping lineage
        lineage_keys = []
        for rec in members:
            sm = getattr(rec, "source_metadata", None) or {}
            if sm.get("lineage_root"):
                lineage_keys.append(str(sm["lineage_root"]))
        existing = None
        for lk in lineage_keys:
            existing = store.find_work_episode_by_lineage(lk)
            if existing:
                break

        project_id = None
        for rec in members:
            pid, _ = resolve_project_for_record(store, rec)
            if pid:
                project_id = pid
                break

        actors: list[str] = []
        for rec in members:
            for a in list(getattr(rec, "actor_ids", None) or []) + list(
                getattr(rec, "participant_ids", None) or []
            ):
                if a and a not in actors:
                    actors.append(a)

        times = sorted(
            t for t in (getattr(r, "occurred_at", None) for r in members) if t
        )
        title = _episode_title(members)
        indep = None
        if lineage_keys:
            indep = f"lineage:{lineage_keys[0]}"

        refs = [_source_ref(r) for r in members]
        if existing is None:
            ep = WorkEpisode(
                project_id=project_id,
                title=title,
                started_at=times[0] if times else None,
                ended_at=times[-1] if times else None,
                status=(
                    EpisodeStatus.active if conf >= 0.90
                    else EpisodeStatus.candidate
                ),
                participant_actor_ids=actors,
                source_refs=refs,
                independence_group=indep,
                confidence=conf,
                metadata={"link_kinds": sorted(set(kinds))},
            )
            store.insert_work_episode(ep)
        else:
            ep = existing
            ep.title = ep.title or title
            ep.project_id = ep.project_id or project_id
            ep.confidence = max(ep.confidence, conf)
            ep.updated_at = now_iso()
            if times:
                if not ep.started_at or times[0] < ep.started_at:
                    ep.started_at = times[0]
                if not ep.ended_at or times[-1] > ep.ended_at:
                    ep.ended_at = times[-1]
            for a in actors:
                if a not in ep.participant_actor_ids:
                    ep.participant_actor_ids.append(a)
            seen = {
                (r.get("external_type"), r.get("external_id"))
                for r in ep.source_refs
            }
            for ref in refs:
                key = (ref.get("external_type"), ref.get("external_id"))
                if key not in seen:
                    ep.source_refs.append(ref)
                    seen.add(key)
            if conf >= 0.90 and ep.status == EpisodeStatus.candidate:
                ep.status = EpisodeStatus.active
            store.update_work_episode(ep)

        for rec in members:
            sm = getattr(rec, "source_metadata", None) or {}
            best_kind = EpisodeLinkKind.soft
            best_conf = 0.4
            for _key, kind, c in keys_by_record.get(getattr(rec, "id", ""), []):
                if c > best_conf:
                    best_conf, best_kind = c, kind
            if store.find_episode_link(
                ep.id, getattr(rec, "external_type", ""),
                getattr(rec, "external_id", ""),
            ):
                continue
            link = EpisodeLink(
                episode_id=ep.id,
                connector_record_id=getattr(rec, "id", None),
                external_type=getattr(rec, "external_type", "") or "",
                external_id=getattr(rec, "external_id", "") or "",
                thread_key=getattr(rec, "thread_key", None),
                lineage_root=sm.get("lineage_root"),
                kind=best_kind,
                confidence=best_conf,
            )
            store.insert_episode_link(link)
        episodes.append(ep)
    return episodes


def _episode_title(members: list[Any]) -> str:
    for rec in members:
        content = (getattr(rec, "content", None) or "").strip()
        if content:
            line = content.splitlines()[0].lstrip("# ").strip()
            if line:
                return line[:120]
        hint = getattr(rec, "project_hint", None)
        if hint:
            return f"Work on {hint}"
    return "Work episode"
