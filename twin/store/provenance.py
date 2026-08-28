"""Provenance chain: Memory → Evidence → Percept → Artifact → source system."""

from __future__ import annotations

from typing import Any, Optional

from .. import ids
from ..clock import now_iso
from twin.sense.sensory.percept import Percept
from .models import Artifact, Evidence, StoreClaim
from .store.base import TwinStore


def ensure_artifact_from_percept(store: TwinStore, percept: Percept) -> Optional[str]:
    """Create or reuse an Artifact from a percept's content_refs / metadata."""
    if not hasattr(store, "insert_artifact"):
        return None
    refs = percept.content_refs or []
    meta = percept.metadata or {}
    external_id = (
        meta.get("commit") or meta.get("sha") or meta.get("external_id")
        or (refs[0] if refs else None)
    )
    uri = meta.get("uri") or meta.get("url") or (refs[0] if refs else None)
    kind = meta.get("artifact_kind") or {
        "git": "git_commit",
        "document": "document",
        "meeting": "meeting",
        "slack": "slack_message",
    }.get(percept.source_sensor, percept.percept_type or "artifact")

    content_hash = percept.content_hash
    # Reuse only within the same source_system — identical bytes from different
    # systems remain distinct artifacts (hash is not ownership).
    if hasattr(store, "find_artifact_by_hash") and content_hash:
        existing = store.find_artifact_by_hash(content_hash)  # type: ignore[attr-defined]
        if existing and existing.source_system == (percept.source_sensor or "local"):
            if hasattr(store, "link_artifact_percept"):
                store.link_artifact_percept(existing.id, percept.id)  # type: ignore[attr-defined]
            return existing.id

    art = Artifact(
        id=ids.artifact_id(),
        kind=kind,
        external_id=str(external_id) if external_id else None,
        source_system=percept.source_sensor or "local",
        uri=str(uri) if uri else None,
        content_hash=content_hash,
        occurred_at=percept.occurred_at,
        created_at=now_iso(),
        metadata={
            "percept_id": percept.id,
            "project_id": percept.project_id,
            **{k: v for k, v in meta.items() if k not in ("content",)},
        },
    )
    store.insert_artifact(art)  # type: ignore[attr-defined]
    if hasattr(store, "link_artifact_percept"):
        store.link_artifact_percept(art.id, percept.id)  # type: ignore[attr-defined]
    return art.id


def claim_provenance(store: TwinStore, claim_id: str) -> dict[str, Any]:
    """Navigable lineage for 'why does twin believe this?'."""
    mem = store.get_claim(claim_id)
    if mem is None:
        raise ValueError(f"memory {claim_id} not found")

    evidence = store.get_evidence(claim_id)
    percepts: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    seen_art: set[str] = set()

    for ev in evidence:
        p = store.get_percept(ev.percept_id)
        p_dump: dict[str, Any] = {
            "id": ev.percept_id,
            "evidence_id": ev.id,
            "quote": ev.quote,
            "evidence_type": ev.evidence_type.value,
            "directness": ev.directness,
            "supports": ev.supports,
        }
        if p:
            p_dump.update({
                "source_sensor": p.source_sensor,
                "occurred_at": p.occurred_at,
                "source_trust": p.source_trust,
                "content_refs": p.content_refs,
                "artifact_id": ev.artifact_id,
            })
            art_id = ev.artifact_id
            if not art_id and hasattr(store, "find_artifact_by_hash") and p.content_hash:
                found = store.find_artifact_by_hash(p.content_hash)  # type: ignore[attr-defined]
                art_id = found.id if found else None
            if art_id and art_id not in seen_art and hasattr(store, "get_artifact"):
                art = store.get_artifact(art_id)  # type: ignore[attr-defined]
                if art:
                    artifacts.append(art.model_dump(mode="json"))
                    seen_art.add(art_id)
                    p_dump["artifact_id"] = art_id
        percepts.append(p_dump)

    relations = [
        r.model_dump(mode="json")
        for r in store.relations_for(claim_id)
        if r.predicate in (
            "supersedes", "contradicts", "merged_into", "split_into",
            "related_to", "supported_by",
        )
    ]

    return {
        "claim": mem.model_dump(mode="json"),
        "evidence": [e.model_dump(mode="json") for e in evidence],
        "percepts": percepts,
        "artifacts": artifacts,
        "relations": relations,
        "chain": "memory → evidence → percept → artifact → source_system",
    }


_SENSOR_LABELS = {
    "github": "GitHub",
    "slack": "Slack",
    "git": "Git",
    "document": "Document",
    "meeting": "Meeting",
    "mail": "Mail",
    "email": "Email",
    "episode": "Episode",
    "episode_reflect": "Derived",
    "pattern_reflect": "Derived",
    "pattern": "Pattern",
    "workspace": "Workspace",
    "unknown": "Unknown",
}

_KIND_LABELS = {
    "pull_request": "pull request",
    "commit": "commit",
    "message": "message",
    "thread_reply": "reply",
    "issue": "issue",
    "channel": "channel",
    "episode": "episode",
    "episode_reflection": "derived",  # legacy
    "pattern_reflection": "derived",  # legacy
    "derived_episode": "derived",
    "derived_pattern": "derived",
}

# Synthetic cognition sensors — show at most once, and only when there is no
# concrete connector artifact to display instead.
_SYNTHETIC_SENSORS = frozenset({
    "episode_reflect", "pattern_reflect", "episode", "pattern", "workspace",
})


def _friendly_sensor(sensor: str) -> str:
    return _SENSOR_LABELS.get(sensor, sensor.replace("_", " ").strip().title() or "Source")


def _friendly_kind(kind: str) -> str:
    if not kind:
        return ""
    return _KIND_LABELS.get(kind, kind.replace("_", " ").strip())


def _source_ref_label(sensor: str, ext_type: str, ext_id: str, sm: dict[str, Any]) -> str:
    """Human label for a provenance chip — never a bare implementation id."""
    sensor_label = _friendly_sensor(sensor)
    if sensor in _SYNTHETIC_SENSORS and not ext_id and not ext_type:
        return sensor_label
    bits: list[str] = [sensor_label]
    kind = _friendly_kind(ext_type)
    if kind:
        bits.append(kind)
    if ext_id:
        short = ext_id if len(ext_id) <= 40 else ext_id.split("/")[-1]
        bits.append(short)
    else:
        channel = sm.get("channel_name") or sm.get("channel")
        if channel:
            bits.append(str(channel))
    return " · ".join(bits)


def claim_source_summary(store: TwinStore, claim_id: str) -> dict[str, Any]:
    """Compact 'where did this come from?' for UI cards and list endpoints.

    Returns sensors (slack/github/…), concrete artifact refs, and a short
    human label suitable for a tag — without the full provenance dump.
    """
    evidence = store.get_evidence(claim_id) if hasattr(store, "get_evidence") else []
    sensors: list[str] = []
    refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    seen_labels: set[str] = set()
    for ev in evidence:
        p = store.get_percept(ev.percept_id) if getattr(ev, "percept_id", None) else None
        if p is None:
            continue
        sensor = p.source_sensor or "unknown"
        meta = p.metadata or {}
        sm = meta.get("source_metadata") or {}
        if not isinstance(sm, dict):
            sm = {}
        ext_type = str(meta.get("external_type") or "")
        ext_id = str(meta.get("external_id") or "")
        # Collapse many reflection percepts into one synthetic chip.
        if sensor in _SYNTHETIC_SENSORS and not ext_id:
            key = (sensor, "")
        else:
            key = (ext_type, ext_id or p.id)
        if key in seen:
            continue
        seen.add(key)
        if sensor not in sensors:
            sensors.append(sensor)
        label = _source_ref_label(sensor, ext_type, ext_id, sm)
        if label in seen_labels:
            continue
        seen_labels.add(label)
        refs.append({
            "sensor": sensor,
            "kind": ext_type or None,
            "id": ext_id or None,
            "url": sm.get("html_url") or sm.get("permalink") or sm.get("url"),
            "author": sm.get("author_name"),
            "channel": sm.get("channel_name") or sm.get("channel"),
            "label": label,
            "occurred_at": p.occurred_at,
        })
    # Prefer concrete connector chips; keep a single reflection chip only when
    # it is the sole origin (no GitHub/Slack artifact alongside).
    concrete = [r for r in refs if r.get("sensor") not in _SYNTHETIC_SENSORS]
    synthetic = [r for r in refs if r.get("sensor") in _SYNTHETIC_SENSORS]
    if concrete:
        refs = concrete
        sensors = [s for s in sensors if s not in _SYNTHETIC_SENSORS]
    elif synthetic:
        refs = synthetic[:1]
        sensors = [refs[0]["sensor"]]
    # Fallback: episode / pattern origin when evidence is still empty
    if not sensors:
        mem = store.get_claim(claim_id)
        payload = (mem.payload or {}) if mem else {}
        if payload.get("episode_id"):
            sensors = ["episode"]
            refs.append({
                "sensor": "episode", "kind": "episode",
                "id": payload["episode_id"],
                "label": "Episode",
            })
        elif payload.get("pattern_window_key"):
            sensors = ["pattern"]
            refs.append({
                "sensor": "pattern", "kind": "pattern",
                "id": payload["pattern_window_key"],
                "label": "Pattern window",
            })
        elif payload.get("source") == "episode_reflect":
            sensors = ["episode_reflect"]
            refs.append({
                "sensor": "episode_reflect", "kind": "derived_episode",
                "id": None,
                "label": "Derived percept",
            })
        elif payload.get("source") == "pattern_reflect":
            sensors = ["pattern_reflect"]
            refs.append({
                "sensor": "pattern_reflect", "kind": "derived_pattern",
                "id": None,
                "label": "Derived percept",
            })
    friendly_sensors = [_friendly_sensor(s) for s in sensors]
    return {
        "sensors": sensors,
        "refs": refs[:6],
        "label": " + ".join(friendly_sensors) if friendly_sensors else "Unknown",
    }


def claim_source_keys(store: TwinStore, memory: Any) -> set[str]:
    """Distinct *independent sources* backing one memory.

    The unit of independence is the evidence ``independence_group`` (e.g.
    ``episode:<id>`` for everything read out of one episode, ``xsense:slack:…``
    for a cross-sense neighbor, ``lineage:github:…`` for a connector record).
    Two evidences from the same episode collapse to one source; a Slack symptom
    attached alongside a GitHub fix is a second, genuinely independent source.

    Falls back to the memory's own origin (episode / pattern window / id) only
    when no evidence groups are recorded.
    """
    mem = memory if hasattr(memory, "payload") else store.get_claim(memory)
    if mem is None:
        return set()
    keys: set[str] = set()
    evidence = store.get_evidence(mem.id) if hasattr(store, "get_evidence") else []
    for e in evidence:
        group = getattr(e, "independence_group", None)
        if group:
            keys.add(str(group))
        elif getattr(e, "percept_id", None):
            keys.add(f"pct:{e.percept_id}")
    if keys:
        return keys
    payload = mem.payload or {}
    if payload.get("episode_id"):
        return {f"episode:{payload['episode_id']}"}
    if payload.get("pattern_window_key"):
        return {f"pattern:{payload['pattern_window_key']}"}
    return {f"mem:{mem.id}"}


def count_independent_sources(store: TwinStore, memories: Any) -> int:
    """Number of distinct independent sources across a set of memories/ids.

    This is the honest "support" behind a claim: N memories that all trace back
    to a single episode count as **one** source, while agreement across senses
    (Slack + GitHub) or across episodes counts as many.
    """
    groups: set[str] = set()
    materialized = list(memories)
    for m in materialized:
        groups |= claim_source_keys(store, m)
    if groups:
        return len(groups)
    return 1 if materialized else 0


def attach_corroborating_evidence(
    store: TwinStore,
    claim_id: str,
    percept_id: str,
    quote: str,
    *,
    independence_group: Optional[str] = None,
    source_trust: float = 0.8,
    bump_confidence: bool = True,
) -> Evidence:
    """Paraphrase/corroboration: same memory, additional evidence, capped confidence."""
    from twin.cognize.services.evidence_text import sanitize_evidence_quote

    mem = store.get_claim(claim_id)
    if mem is None:
        raise ValueError(f"memory {claim_id} not found")
    ev = Evidence(
        id=ids.evidence_id(),
        claim_id=claim_id,
        percept_id=percept_id,
        quote=sanitize_evidence_quote(quote),
        evidence_type="verbatim",  # type: ignore[arg-type]
        directness=0.9,
        source_trust=source_trust,
        independence_group=independence_group,
        supports=True,
    )
    store.insert_evidence(ev)
    if bump_confidence:
        # diminishing returns; independence groups share credit
        existing = store.get_evidence(claim_id)
        groups = {e.independence_group or e.percept_id for e in existing}
        # asymptotic toward 0.95
        n = len(groups)
        new_conf = min(0.95, mem.confidence + 0.08 / max(1, n - 1) if n > 1 else mem.confidence + 0.05)
        store.update_claim(claim_id, confidence=round(new_conf, 3))
    return ev
