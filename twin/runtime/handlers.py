"""Job handlers — call the cognitive core; never invent meaning here."""

from __future__ import annotations

from typing import Any, Callable

from twin.config import Config
from twin.memory.embeddings import Embedder
from twin.memory.store.base import MemoryStore
from twin.runtime.models import ErrorClass, JobKind, RuntimeJob


class HandlerError(Exception):
    def __init__(self, message: str, *, error_class: ErrorClass = ErrorClass.transient, stage: str = ""):
        super().__init__(message)
        self.error_class = error_class
        self.stage = stage


Handler = Callable[[MemoryStore, Config, Embedder, RuntimeJob], dict[str, Any]]


def handle_interpret_percept(
    store: MemoryStore, cfg: Config, embedder: Embedder, job: RuntimeJob,
) -> dict[str, Any]:
    from twin.cognition.pipeline import extract_percept
    from twin.cognition.interpreter import service as interp_service

    percept_id = (job.payload or {}).get("percept_id")
    if not percept_id:
        raise HandlerError("missing percept_id", error_class=ErrorClass.permanent, stage="validate")
    percept = store.get_percept(percept_id)
    if percept is None:
        raise HandlerError(f"percept {percept_id} not found", error_class=ErrorClass.permanent, stage="validate")

    if interp_service.interpreting_mode(cfg) and cfg.extractor in ("auto", "ollama"):
        runtime = interp_service.InterpretationRuntime(cfg)
        if not runtime.available:
            raise HandlerError(
                "cognitive model unavailable",
                error_class=ErrorClass.model_unavailable,
                stage="interpret",
            )

    report = extract_percept(store, cfg, embedder, percept)
    return {
        "percept_id": percept_id,
        "inserted": list(report.inserted),
        "deferred": report.deferred,
        "interpretation_status": report.interpretation_status,
        "ungrounded": report.ungrounded,
    }


def handle_workspace_tick(
    store: MemoryStore, cfg: Config, embedder: Embedder, job: RuntimeJob,
) -> dict[str, Any]:
    from twin.cognition.workspace import workspace_tick

    p = job.payload or {}
    text = p.get("text") or p.get("current_text") or ""
    if not text.strip():
        raise HandlerError("missing text", error_class=ErrorClass.permanent, stage="validate")
    result = workspace_tick(
        store, cfg, embedder, text,
        session_id=p.get("session_id") or "",
        target_domain=p.get("target_domain"),
        interpret=bool(p.get("interpret", False)),
        input_mode=p.get("input_mode") or "snapshot",
        sequence=p.get("sequence"),
        idempotency_key=p.get("idempotency_key") or job.idempotency_key or None,
        retry=bool(p.get("retry", False)),
    )
    return result.to_dict()


def handle_consolidate_daily(
    store: MemoryStore, cfg: Config, embedder: Embedder, job: RuntimeJob,
) -> dict[str, Any]:
    from twin.cognition.consolidation_cycle import (
        ConsolidationInvariantError,
        run_consolidation_cycle,
    )

    p = job.payload or {}
    try:
        result = run_consolidation_cycle(
            store, cfg, embedder,
            kind="daily",
            dry_run=bool(p.get("dry_run", False)),
            retry=bool(p.get("retry", False)),
        )
    except ConsolidationInvariantError as exc:
        raise HandlerError(str(exc), error_class=ErrorClass.invariant, stage="invariant") from exc
    return result.to_dict()


def handle_consolidate_weekly(
    store: MemoryStore, cfg: Config, embedder: Embedder, job: RuntimeJob,
) -> dict[str, Any]:
    from twin.cognition.consolidation_cycle import (
        ConsolidationInvariantError,
        run_consolidation_cycle,
    )

    p = job.payload or {}
    try:
        result = run_consolidation_cycle(
            store, cfg, embedder,
            kind="weekly",
            dry_run=bool(p.get("dry_run", False)),
            retry=bool(p.get("retry", False)),
        )
    except ConsolidationInvariantError as exc:
        raise HandlerError(str(exc), error_class=ErrorClass.invariant, stage="invariant") from exc
    return result.to_dict()


def handle_reembed_memory(
    store: MemoryStore, cfg: Config, embedder: Embedder, job: RuntimeJob,
) -> dict[str, Any]:
    mid = (job.payload or {}).get("memory_id")
    if not mid:
        raise HandlerError("missing memory_id", error_class=ErrorClass.permanent, stage="validate")
    mem = store.get_memory(mid)
    if mem is None:
        raise HandlerError(f"memory {mid} not found", error_class=ErrorClass.permanent, stage="validate")
    vector = embedder.embed(f"{mem.title}\n{mem.summary}")
    store.store_embedding(mem.id, "memory", embedder.name, vector)
    return {"memory_id": mid, "embedder": embedder.name}


def handle_integrity_check(
    store: MemoryStore, cfg: Config, embedder: Embedder, job: RuntimeJob,
) -> dict[str, Any]:
    depths = store.runtime_queue_depth() if hasattr(store, "runtime_queue_depth") else {}
    mem_n = len(store.list_memories(limit=1))
    return {"queue": depths, "has_memories": mem_n > 0, "ok": True}


def handle_attention_evaluate(
    store: MemoryStore, cfg: Config, embedder: Embedder, job: RuntimeJob,
) -> dict[str, Any]:
    from twin.cognition.attention import evaluate_attention

    p = job.payload or {}
    session_id = p.get("session_id") or ""
    if not session_id:
        raise HandlerError("missing session_id", error_class=ErrorClass.permanent, stage="validate")
    outcomes = evaluate_attention(
        store, cfg, embedder, session_id, text=p.get("text") or None,
    )
    return {
        "session_id": session_id,
        "outcomes": [o.to_dict() for o in outcomes],
        "emitted": sum(1 for o in outcomes if o.kind.value != "silence"),
    }


def handle_connector_reconcile(
    store: MemoryStore, cfg: Config, embedder: Embedder, job: RuntimeJob,
) -> dict[str, Any]:
    # Lightweight stub: report connector sync states when present.
    if not hasattr(store, "list_connector_instances"):
        return {"reconciled": 0, "note": "connectors unavailable"}
    instances = store.list_connector_instances(limit=200)  # type: ignore[attr-defined]
    return {"reconciled": len(instances), "instance_ids": [i.id for i in instances[:50]]}


HANDLERS: dict[JobKind, Handler] = {
    JobKind.interpret_percept: handle_interpret_percept,
    JobKind.workspace_tick: handle_workspace_tick,
    JobKind.attention_evaluate: handle_attention_evaluate,
    JobKind.consolidate_daily: handle_consolidate_daily,
    JobKind.consolidate_weekly: handle_consolidate_weekly,
    JobKind.reembed_memory: handle_reembed_memory,
    JobKind.integrity_check: handle_integrity_check,
    JobKind.connector_reconcile: handle_connector_reconcile,
}


def dispatch(
    store: MemoryStore, cfg: Config, embedder: Embedder, job: RuntimeJob,
) -> dict[str, Any]:
    kind = job.kind if isinstance(job.kind, JobKind) else JobKind(str(job.kind))
    handler = HANDLERS.get(kind)
    if handler is None:
        raise HandlerError(f"no handler for {kind}", error_class=ErrorClass.permanent, stage="dispatch")
    return handler(store, cfg, embedder, job)
