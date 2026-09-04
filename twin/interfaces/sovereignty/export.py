"""Sovereignty export — NDJSON sections for portability."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Optional

from twin.clock import now_iso
from twin.privacy.vault import FALLBACK_VAULT, iter_vault_ids, vault_read_ids
from twin.store.store.base import TwinStore
from twin.interfaces.sovereignty.manifest import (
    BackupManifest,
    FileEntry,
    sha256_bytes,
)

SECTIONS = (
    "percepts",
    "claims",
    "evidence",
    "sessions",
    "session_events",
    "judgment_items",
    "judgment_proposals",
    "privacy_decisions",
    "claim_operations",
    "personas",
    "cognize_situations",
    "cognize_reflections",
    "cognize_interpretations",
    "cognize_relations",
    "cognize_narratives",
    "cognize_epistemic_states",
    "cognize_evidence_anchors",
    "cognize_traces",
    "cognize_narrative_revisions",
    "cognize_runs",
)


def _dump_line(obj: Any) -> bytes:
    if hasattr(obj, "model_dump"):
        payload = obj.model_dump(mode="json")
    elif isinstance(obj, dict):
        payload = obj
    else:
        payload = {"value": str(obj)}
    return (json.dumps(payload, ensure_ascii=False, default=str) + "\n").encode("utf-8")


def _write_section(path: Path, rows: Iterable[Any]) -> FileEntry:
    buf = bytearray()
    n = 0
    for row in rows:
        buf.extend(_dump_line(row))
        n += 1
    path.write_bytes(bytes(buf))
    return FileEntry(
        path=path.name,
        sha256=sha256_bytes(bytes(buf)),
        bytes=len(buf),
        records=n,
    )


def collect_export(store: TwinStore) -> dict[str, list[Any]]:
    data: dict[str, list[Any]] = {s: [] for s in SECTIONS}
    if hasattr(store, "list_percepts"):
        data["percepts"] = list(store.list_percepts())

    for status in ("candidate", "confirmed", "rejected", "deprecated", "archived"):
        data["claims"].extend(store.list_claims(status=status, limit=5_000))
    seen: set[str] = set()
    uniq = []
    for m in data["claims"]:
        if m.id in seen:
            continue
        seen.add(m.id)
        uniq.append(m)
    data["claims"] = uniq

    for mem in data["claims"]:
        data["evidence"].extend(store.get_evidence(mem.id))

    if hasattr(store, "list_sessions"):
        for st in ("active", "paused", "completed", "abandoned", "archived"):
            data["sessions"].extend(store.list_sessions(status=st, limit=2_000))
        sseen: set[str] = set()
        sessions = []
        for s in data["sessions"]:
            if s.id in sseen:
                continue
            sseen.add(s.id)
            sessions.append(s)
        data["sessions"] = sessions
        if hasattr(store, "list_session_events"):
            for s in data["sessions"]:
                data["session_events"].extend(
                    store.list_session_events(s.id, limit=10_000),
                )

    if hasattr(store, "list_judgment_items"):
        data["judgment_items"] = list(store.list_judgment_items(limit=5_000))
    if hasattr(store, "list_judgment_proposals"):
        try:
            data["judgment_proposals"] = list(
                store.list_judgment_proposals(limit=5_000),
            )
        except TypeError:
            data["judgment_proposals"] = list(
                store.list_judgment_proposals(status="pending", limit=5_000),
            )
    if hasattr(store, "list_personas"):
        data["personas"] = list(store.list_personas(active_only=False))

    # Cognize entities (include legacy ``default`` partition via vault_read_ids)
    vaults: set[str] = set()
    for seed in list(iter_vault_ids(store) or [FALLBACK_VAULT]) + ["default", FALLBACK_VAULT]:
        vaults.update(vault_read_ids(seed))
    if hasattr(store, "list_narratives"):
        for seed in list(vaults):
            for nar in store.list_narratives(seed):
                if nar.vault_id:
                    vaults.update(vault_read_ids(nar.vault_id))
            if hasattr(store, "list_situations"):
                for sit in store.list_situations(seed):
                    if sit.vault_id:
                        vaults.update(vault_read_ids(sit.vault_id))
        for vid in sorted(vaults):
            if hasattr(store, "list_situations"):
                data["cognize_situations"].extend(store.list_situations(vid))
            if hasattr(store, "list_reflections"):
                data["cognize_reflections"].extend(store.list_reflections(vid))
            elif hasattr(store, "list_open_reflections"):
                data["cognize_reflections"].extend(store.list_open_reflections(vid))
            if hasattr(store, "list_cognize_interpretations"):
                data["cognize_interpretations"].extend(
                    store.list_cognize_interpretations(vid)
                )
            if hasattr(store, "list_relations"):
                data["cognize_relations"].extend(store.list_relations(vid))
            data["cognize_narratives"].extend(store.list_narratives(vid))
            if hasattr(store, "list_evidence_anchors"):
                data["cognize_evidence_anchors"].extend(store.list_evidence_anchors(vid))
        seen_eps: set[str] = set()
        for nar in data["cognize_narratives"]:
            if not nar.epistemic_state_id or nar.epistemic_state_id in seen_eps:
                continue
            if hasattr(store, "get_epistemic_state"):
                eps = store.get_epistemic_state(nar.epistemic_state_id)
                if eps is not None:
                    data["cognize_epistemic_states"].append(eps)
                    seen_eps.add(nar.epistemic_state_id)
    return data


def write_export_bundle(
    store: TwinStore,
    dest: Path,
    *,
    kind: str = "export",
) -> BackupManifest:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    sections_dir = dest / "sections"
    sections_dir.mkdir(exist_ok=True)

    collected = collect_export(store)
    files: list[FileEntry] = []
    counts: dict[str, int] = {}
    present: list[str] = []
    for name in SECTIONS:
        rows = collected.get(name) or []
        entry = _write_section(sections_dir / f"{name}.ndjson", rows)
        entry.path = f"sections/{name}.ndjson"
        files.append(entry)
        counts[name] = entry.records
        if entry.records:
            present.append(name)

    manifest = BackupManifest(
        kind=kind,
        sections=present or list(SECTIONS),
        files=files,
        counts=counts,
        secrets_included=False,
        notes=["no connector credentials", "no encryption key material"],
        metadata={"exported_at": now_iso()},
    )
    (dest / "manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2), encoding="utf-8",
    )
    return manifest
