"""Workspace tick (v0.8) — Global-Workspace-shaped observation spine.

Synchronous, invocable evaluation — not a continuous background worker.
Separates stages clearly:

```text
reading → observe → salience → recall → [parallel_interpretation] → done
```

A tick never writes confirmed Memory or Judgment. Optional interpretation
reuses the v0.7 pipeline and only produces reviewable candidates, and only
for ``input_mode="delta"`` with an idempotent identity.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

from .. import ids
from ..clock import now_iso
from ..config import UNCLASSIFIED_DOMAIN, Config
from ..judgment.firewall import Firewall
from ..memory.embeddings import Embedder
from ..memory.store.base import MemoryStore
from ..memory.store.workspace_ops_mixin import WorkspaceTickRecord
from ..sensory.percept import Percept
from .observer import observe, read_context
from .pipeline import extract_percept
from .recall import RecallPolicy, RecallResult, apply_recall_policy
from .salience import score_memories

InputMode = Literal["snapshot", "delta"]


def text_content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


@dataclass
class WorkspaceTickResult:
    """Typed stages of one workspace evaluation tick."""

    tick_id: str = ""
    session_id: str = ""
    sequence: Optional[int] = None
    content_hash: str = ""
    input_mode: str = "snapshot"
    idempotency_key: str = ""
    duplicated: bool = False
    inferred_domain: str = ""
    reading: dict[str, Any] = field(default_factory=dict)
    suggestions: list[dict[str, Any]] = field(default_factory=list)
    blocked: list[dict[str, Any]] = field(default_factory=list)
    silent: bool = False
    silence_reason: str = ""
    contradiction_memory_ids: list[str] = field(default_factory=list)
    parallel_interpretation: dict[str, Any] = field(default_factory=dict)
    candidate_memory_ids: list[str] = field(default_factory=list)
    stages: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkspaceTickResult":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


def _result_from_record(record: WorkspaceTickRecord) -> WorkspaceTickResult:
    payload = dict(record.payload or {})
    result = WorkspaceTickResult.from_dict(payload) if payload else WorkspaceTickResult()
    result.tick_id = record.id
    result.session_id = record.session_id
    result.sequence = record.sequence
    result.content_hash = record.content_hash
    result.input_mode = record.input_mode
    result.idempotency_key = record.idempotency_key
    result.duplicated = True
    if record.percept_id and not result.parallel_interpretation.get("percept_id"):
        result.parallel_interpretation = {
            **result.parallel_interpretation,
            "percept_id": record.percept_id,
            "reused": True,
        }
    return result


def _lookup_existing_tick(
    store: MemoryStore,
    *,
    session_id: str,
    sequence: Optional[int],
    content_hash: str,
    input_mode: str,
    interpret: bool,
    idempotency_key: str,
) -> Optional[WorkspaceTickRecord]:
    if not hasattr(store, "get_workspace_tick_by_idempotency_key"):
        return None
    existing = None
    if idempotency_key:
        existing = store.get_workspace_tick_by_idempotency_key(idempotency_key)
    if existing is None and session_id and sequence is not None:
        existing = store.get_workspace_tick_by_session_sequence(session_id, sequence)
    if (
        existing is None
        and interpret
        and input_mode == "delta"
        and session_id
        and content_hash
    ):
        existing = store.get_workspace_tick_by_session_delta_hash(session_id, content_hash)
    return existing


def workspace_tick(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    current_text: str,
    *,
    session_id: str = "",
    target_domain: Optional[str] = None,
    cwd: Optional[str] = None,
    policy: Optional[RecallPolicy] = None,
    interpret: bool = False,
    input_mode: InputMode = "snapshot",
    sequence: Optional[int] = None,
    idempotency_key: Optional[str] = None,
    firewall: Optional[Firewall] = None,
) -> WorkspaceTickResult:
    """Run one workspace evaluation tick.

    ``interpret=True`` only creates a Percept when ``input_mode="delta"``.
    Snapshots observe/recall only unless a future cursor derives a true delta.
    Identity: ``idempotency_key``, or ``session_id+sequence``, or
    ``session_id+content_hash`` for delta interpretation.
    """
    if input_mode not in ("snapshot", "delta"):
        raise ValueError(f"unknown input_mode: {input_mode!r}")

    text = (current_text or "").strip()
    ch = text_content_hash(text)
    key = (idempotency_key or "").strip()
    sid = session_id or ""

    existing = _lookup_existing_tick(
        store,
        session_id=sid,
        sequence=sequence,
        content_hash=ch,
        input_mode=input_mode,
        interpret=interpret,
        idempotency_key=key,
    )
    if existing is not None and existing.status == "completed":
        return _result_from_record(existing)

    previous_id = ""
    if sid and hasattr(store, "latest_workspace_tick_for_session"):
        prev = store.latest_workspace_tick_for_session(sid)
        if prev is not None:
            previous_id = prev.id

    tick = WorkspaceTickRecord(
        session_id=sid,
        sequence=sequence,
        content_hash=ch,
        input_mode=input_mode,
        idempotency_key=key,
        interpret=interpret and input_mode == "delta",
        status="running",
        previous_tick_id=previous_id,
        started_at=now_iso(),
    )
    created = True
    if hasattr(store, "try_begin_workspace_tick"):
        tick, created = store.try_begin_workspace_tick(tick)
        if not created and tick.status == "completed":
            return _result_from_record(tick)

    result = WorkspaceTickResult(
        tick_id=tick.id,
        session_id=sid,
        sequence=sequence,
        content_hash=ch,
        input_mode=input_mode,
        idempotency_key=key,
        duplicated=not created,
    )
    result.stages.append("reading")

    reading = read_context(store, cfg, text, cwd=cwd)
    result.reading = {
        "domain": reading.domain,
        "task_profile": reading.task_profile,
        "project_id": reading.project_id,
        "confidences": dict(reading.confidences or {}),
        "uncertain": reading.uncertain,
        "mode": reading.mode,
        "needs_domain_confirmation": reading.needs_domain_confirmation,
    }
    domain = target_domain or reading.domain
    result.inferred_domain = domain

    result.stages.append("observe")
    obs = observe(
        store, cfg, embedder, text,
        target_domain=domain if domain != UNCLASSIFIED_DOMAIN else None,
        firewall=firewall,
    )
    # Preserve observer retrieval score — never overwrite with confidence.
    suggested_rows = []
    for row in obs.suggested_context:
        suggested_rows.append({
            **row,
            "score": float(row["score"]) if row.get("score") is not None else 0.0,
        })

    result.stages.append("salience")
    mids = [r["memory_id"] for r in suggested_rows if r.get("memory_id")]
    scores = score_memories(store, mids, query_text=text)
    result.contradiction_memory_ids = list(scores.contradiction_ids)

    result.stages.append("recall")
    recall: RecallResult = apply_recall_policy(
        suggested_rows, obs.blocked_context,
        policy=policy,
        salience_by_id=scores.by_memory,
        novelty_by_id=scores.novelty,
    )
    result.suggestions = [
        {
            "memory_id": s.memory_id,
            "summary": s.summary,
            "why_relevant": s.why_relevant,
            "confidence": s.confidence,
            "score": s.score,
            "salience": s.salience,
            "novelty": s.novelty,
            "stage": s.stage,
        }
        for s in recall.suggestions
    ]
    result.blocked = list(recall.blocked)
    result.silent = recall.silent
    result.silence_reason = recall.silence_reason

    if interpret and text:
        result.stages.append("parallel_interpretation")
        if input_mode != "delta":
            result.parallel_interpretation = {
                "skipped": True,
                "reason": "interpret_requires_input_mode_delta",
            }
            result.notes.append("snapshot ticks do not invent session deltas")
        elif reading.needs_domain_confirmation and not target_domain:
            result.parallel_interpretation = {
                "skipped": True,
                "reason": "needs_domain_confirmation",
            }
            result.notes.append("refused to interpret while domain is unclassified")
        else:
            # Never coerce unclassified → technical.
            source_scope = (
                domain if domain and domain != UNCLASSIFIED_DOMAIN
                else UNCLASSIFIED_DOMAIN
            )
            percept = Percept(
                id=ids.new_id("pct"),
                percept_type="session_delta",
                source_sensor="workspace",
                occurred_at=now_iso(),
                ingested_at=now_iso(),
                content=text,
                source_trust=0.70,
                source_scope=source_scope,
                source_confidentiality="internal",
                project_id=reading.project_id,
                metadata={
                    "workspace_tick": True,
                    "tick_id": tick.id,
                    "session_id": sid,
                    "sequence": sequence,
                    "content_hash": ch,
                    "input_mode": input_mode,
                    "stage": "parallel_interpretation",
                },
            )
            percept.seal()
            store.insert_percept(percept)
            report = extract_percept(store, cfg, embedder, percept)
            result.parallel_interpretation = {
                "percept_id": percept.id,
                "deferred": report.deferred,
                "interpretation_status": report.interpretation_status,
                "inserted": list(report.inserted),
                "ungrounded": report.ungrounded,
                "invalid": report.invalid,
                "policy_dropped": report.policy_dropped,
                "stage_counts": report.stage_counts(),
            }
            result.candidate_memory_ids = list(report.inserted)
            tick.percept_id = percept.id

    result.stages.append("done")
    result.notes.append("tick never confirms Memory or Judgment")

    tick.status = "completed"
    tick.completed_at = now_iso()
    tick.payload = result.to_dict()
    if hasattr(store, "update_workspace_tick"):
        store.update_workspace_tick(tick)
    return result
