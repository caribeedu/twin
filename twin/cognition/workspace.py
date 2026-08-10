"""Workspace tick — Global-Workspace-shaped observation spine.

Synchronous, invocable evaluation — not a continuous background worker.
Separates stages clearly:

```text
reading → observe → salience → recall → [parallel_interpretation] → done
```

A tick never writes confirmed Memory or Judgment. Optional interpretation
reuses the pipeline and only produces reviewable candidates, and only
for ``input_mode="delta"`` with an idempotent identity.

Execution exclusivity: only the caller that *creates* the running row may
execute. Concurrent callers seeing ``running`` get ``blocked_concurrent``.
Failures persist as ``error`` (sanitized); reclaim with ``retry=True``.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

from .. import ids
from ..clock import now_iso
from ..config import UNCLASSIFIED_DOMAIN, Config
from twin.sense.connectors.errors import sanitize_error
from twin.privacy.firewall import Firewall
from twin.store.embeddings import Embedder
from twin.store.store.base import MemoryStore
from twin.store.store.workspace_ops_mixin import WorkspaceTickRecord
from twin.sense.sensory.percept import Percept
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
    status: str = ""
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
    error: str = ""
    error_stage: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkspaceTickResult":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


def _result_from_record(record: WorkspaceTickRecord, *, duplicated: bool = True) -> WorkspaceTickResult:
    payload = dict(record.payload or {})
    result = WorkspaceTickResult.from_dict(payload) if payload else WorkspaceTickResult()
    result.tick_id = record.id
    result.session_id = record.session_id
    result.sequence = record.sequence
    result.content_hash = record.content_hash
    result.input_mode = record.input_mode
    result.idempotency_key = record.idempotency_key
    result.duplicated = duplicated
    result.status = record.status
    result.error = record.error or result.error
    result.error_stage = record.error_stage or result.error_stage
    if record.percept_id and not result.parallel_interpretation.get("percept_id"):
        result.parallel_interpretation = {
            **result.parallel_interpretation,
            "percept_id": record.percept_id,
            "reused": True,
        }
    return result


def _blocked_concurrent(record: WorkspaceTickRecord) -> WorkspaceTickResult:
    return WorkspaceTickResult(
        tick_id=record.id,
        session_id=record.session_id,
        sequence=record.sequence,
        content_hash=record.content_hash,
        input_mode=record.input_mode,
        idempotency_key=record.idempotency_key,
        duplicated=True,
        status="running",
        silent=True,
        stages=["blocked_concurrent"],
        notes=["another workspace executor owns this tick"],
    )


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


def _fail_tick(
    store: MemoryStore,
    tick: WorkspaceTickRecord,
    *,
    stage: str,
    exc: BaseException,
    result: Optional[WorkspaceTickResult] = None,
) -> None:
    tick.status = "error"
    tick.error = sanitize_error(exc)
    tick.error_stage = stage
    tick.completed_at = now_iso()
    if result is not None:
        result.status = "error"
        result.error = tick.error
        result.error_stage = stage
        result.stages = list(result.stages) + ["error"]
        result.notes.append(f"failed at {stage}: {type(exc).__name__}")
        tick.payload = result.to_dict()
    if hasattr(store, "update_workspace_tick"):
        store.update_workspace_tick(tick)


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
    retry: bool = False,
    firewall: Optional[Firewall] = None,
) -> WorkspaceTickResult:
    """Run one workspace evaluation tick.

    ``interpret=True`` only creates a Percept when ``input_mode="delta"``.
    Concurrent callers that see an existing ``running`` row do not execute.
    Prior ``error`` rows are returned unless ``retry=True`` reclaims them.
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
    if existing is not None:
        if existing.status == "completed":
            return _result_from_record(existing)
        if existing.status == "running":
            return _blocked_concurrent(existing)
        if existing.status == "error" and not retry:
            out = _result_from_record(existing)
            out.notes = list(out.notes) + [
                "prior tick failed; pass retry=True to reclaim",
            ]
            return out

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
        error="",
        error_stage="",
    )
    created = True
    if existing is not None and existing.status == "error" and retry:
        # Atomic reclaim: only one caller may flip error → running.
        claimed = False
        if hasattr(store, "try_claim_workspace_tick_retry"):
            claimed = store.try_claim_workspace_tick_retry(
                existing.id, started_at=now_iso(),
            )
        if not claimed:
            current = store.get_workspace_tick(existing.id) if hasattr(store, "get_workspace_tick") else existing
            if current is None:
                current = existing
            if current.status == "running":
                return _blocked_concurrent(current)
            if current.status == "completed":
                return _result_from_record(current)
            out = _result_from_record(current)
            out.notes = list(out.notes) + ["retry claim lost to another executor"]
            return out
        tick = store.get_workspace_tick(existing.id)  # type: ignore[assignment]
        assert tick is not None
        # Keep percept_id from the failed attempt for reuse.
        created = True
    elif hasattr(store, "try_begin_workspace_tick"):
        tick, created = store.try_begin_workspace_tick(tick)
        if not created:
            if tick.status == "completed":
                return _result_from_record(tick)
            if tick.status == "running":
                return _blocked_concurrent(tick)
            if tick.status == "error" and not retry:
                out = _result_from_record(tick)
                out.notes = list(out.notes) + [
                    "prior tick failed; pass retry=True to reclaim",
                ]
                return out
            if tick.status == "error" and retry:
                claimed = False
                if hasattr(store, "try_claim_workspace_tick_retry"):
                    claimed = store.try_claim_workspace_tick_retry(
                        tick.id, started_at=now_iso(),
                    )
                if not claimed:
                    current = store.get_workspace_tick(tick.id) if hasattr(store, "get_workspace_tick") else tick
                    if current is None:
                        current = tick
                    if current.status == "running":
                        return _blocked_concurrent(current)
                    if current.status == "completed":
                        return _result_from_record(current)
                    out = _result_from_record(current)
                    out.notes = list(out.notes) + ["retry claim lost to another executor"]
                    return out
                tick = store.get_workspace_tick(tick.id)  # type: ignore[assignment]
                assert tick is not None
                created = True

    result = WorkspaceTickResult(
        tick_id=tick.id,
        session_id=sid,
        sequence=sequence,
        content_hash=ch,
        input_mode=input_mode,
        idempotency_key=key,
        duplicated=not created,
        status="running",
    )
    stage = "reading"

    try:
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

        stage = "observe"
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

        stage = "salience"
        result.stages.append("salience")
        mids = [r["memory_id"] for r in suggested_rows if r.get("memory_id")]
        scores = score_memories(store, mids, query_text=text)
        result.contradiction_memory_ids = list(scores.contradiction_ids)

        stage = "recall"
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
            stage = "parallel_interpretation"
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
                source_scope = (
                    domain if domain and domain != UNCLASSIFIED_DOMAIN
                    else UNCLASSIFIED_DOMAIN
                )
                # Reuse Percept from a prior failed attempt when present.
                reused_percept = False
                percept = None
                if tick.percept_id:
                    percept = store.get_percept(tick.percept_id)
                    if percept is not None:
                        reused_percept = True
                if percept is None:
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
                    # Persist association immediately so retry cannot orphan/duplicate.
                    tick.percept_id = percept.id
                    if hasattr(store, "update_workspace_tick"):
                        store.update_workspace_tick(tick)
                else:
                    result.notes.append("reused percept from prior tick attempt")

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
                    "reused_percept": reused_percept,
                }
                result.candidate_memory_ids = list(report.inserted)
                tick.percept_id = percept.id

        stage = "done"
        result.stages.append("done")
        result.notes.append("tick never confirms Memory or Judgment")
        result.status = "completed"

        tick.status = "completed"
        tick.completed_at = now_iso()
        tick.error = ""
        tick.error_stage = ""
        tick.payload = result.to_dict()
        if hasattr(store, "update_workspace_tick"):
            store.update_workspace_tick(tick)
        return result
    except Exception as exc:
        _fail_tick(store, tick, stage=stage, exc=exc, result=result)
        raise
