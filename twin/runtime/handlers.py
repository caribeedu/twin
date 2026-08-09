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

    if interp_service.interpreting_mode(cfg) and cfg.extractor != "echo":
        runtime = interp_service.InterpretationRuntime(cfg)
        try:
            if not runtime.available:
                raise HandlerError(
                    "cognitive model unavailable",
                    error_class=ErrorClass.model_unavailable,
                    stage="interpret",
                )
        finally:
            runtime.close()

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
    from twin.sovereignty.integrity import run_integrity_checks
    report = run_integrity_checks(store)
    return report


def handle_cognize_batch(
    store: MemoryStore, cfg: Config, embedder: Embedder, job: RuntimeJob,
) -> dict[str, Any]:
    from twin.cognize.orchestrator import CognizeStage, run_cognize

    p = job.payload or {}
    until = p.get("until")
    until_stage = CognizeStage(until) if until else None
    report = run_cognize(
        store,
        cfg,
        percept_ids=list(p.get("percept_ids") or []) or None,
        until=until_stage,
        dry_run=bool(p.get("dry_run")),
        limit=int(p.get("limit") or 50),
        vault_id=p.get("vault_id") or p.get("vault") or None,
    )
    return report.to_dict()


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
    """Run due connector syncs via the shared scheduler (recovery path)."""
    if not hasattr(store, "list_connector_instances"):
        return {"reconciled": 0, "note": "connectors unavailable"}
    from twin.connectors.credentials import build_credential_store
    from twin.connectors.scheduler import sync_due

    payload = job.payload or {}
    emit = bool(payload.get("emit_percepts", True))
    creds = build_credential_store(cfg.home)
    results = sync_due(store, creds, cfg.home, emit_percepts=emit)
    return {
        "reconciled": len(results),
        "ok": sum(1 for r in results if r.ok),
        "results": [
            {
                "connector_id": r.connector_id,
                "ok": r.ok,
                "health": r.health.value if hasattr(r.health, "value") else str(r.health),
                "percepts": r.percepts,
            }
            for r in results
        ],
    }


def handle_backfill_partition(
    store: MemoryStore, cfg: Config, embedder: Embedder, job: RuntimeJob,
) -> dict[str, Any]:
    """Advance one BackfillJob partition (historical; not continuous sync)."""
    if not hasattr(store, "get_backfill_job"):
        return {"done": True, "note": "backfill unavailable"}
    from twin.connectors.credentials import build_credential_store
    from twin.connectors.service import run_backfill_partition
    from twin.runtime.backfill_sched import enqueue_backfill_partition_jobs
    from twin.runtime.queue import RuntimeQueue

    payload = job.payload or {}
    backfill_job_id = payload.get("backfill_job_id") or ""
    if not backfill_job_id:
        raise HandlerError(
            "missing backfill_job_id",
            error_class=ErrorClass.permanent,
            stage="validate",
        )
    emit = bool(payload.get("emit_percepts", True))
    worker_id = job.worker_id or f"runtime_{job.id[:12]}"
    creds = build_credential_store(cfg.home)
    try:
        out = run_backfill_partition(
            store, creds, backfill_job_id,
            emit_percepts=emit,
            worker_id=worker_id,
        )
    except ValueError as exc:
        msg = str(exc)
        if "already claimed" in msg:
            raise HandlerError(
                msg, error_class=ErrorClass.transient, stage="claim",
            ) from exc
        if "not found" in msg:
            raise HandlerError(
                msg, error_class=ErrorClass.permanent, stage="validate",
            ) from exc
        if " is completed" in msg or " is cancelled" in msg:
            return {
                "job_id": backfill_job_id,
                "done": True,
                "note": msg,
            }
        raise HandlerError(
            msg, error_class=ErrorClass.permanent, stage="validate",
        ) from exc

    # Keep draining without waiting for the next scheduler tick.
    if not out.get("done") and out.get("partition_status") != "failed":
        try:
            bf = store.get_backfill_job(backfill_job_id)
            vault = (
                ((bf.metadata or {}).get("vault_id") if bf else None)
                or job.vault_id
                or "vault_general"
            )
            enqueue_backfill_partition_jobs(
                RuntimeQueue(store), store,
                vault_id=str(vault),
                backfill_job_id=backfill_job_id,
            )
        except Exception:
            # Scheduler tick remains the recovery path.
            pass
    return out


def handle_session_domain_resolve(
    store: MemoryStore, cfg: Config, embedder: Embedder, job: RuntimeJob,
) -> dict[str, Any]:
    """Background domain freeze from multi-message session evidence (LLM)."""
    from twin.cognition.host_session import apply_background_domain_resolve
    from twin.cognition.interpreter import service as interp_service

    p = job.payload or {}
    binding_id = p.get("binding_id") or ""
    if not binding_id:
        raise HandlerError("missing binding_id", error_class=ErrorClass.permanent, stage="validate")

    if interp_service.interpreting_mode(cfg) and cfg.extractor != "echo":
        runtime = interp_service.InterpretationRuntime(cfg)
        try:
            if not runtime.available:
                raise HandlerError(
                    "cognitive model unavailable",
                    error_class=ErrorClass.model_unavailable,
                    stage="domain_resolve",
                )
        finally:
            runtime.close()

    return apply_background_domain_resolve(
        store, cfg, embedder,
        binding_id=binding_id,
        cwd=p.get("cwd") or None,
    )


def handle_session_complete(
    store: MemoryStore, cfg: Config, embedder: Embedder, job: RuntimeJob,
) -> dict[str, Any]:
    """Background session consolidation + extract after native SessionEnd."""
    from twin.cognition.sessions import complete_session
    from twin.cognition.interpreter import service as interp_service

    p = job.payload or {}
    session_id = p.get("session_id") or ""
    if not session_id:
        raise HandlerError("missing session_id", error_class=ErrorClass.permanent, stage="validate")

    if (
        not p.get("abandoned")
        and interp_service.interpreting_mode(cfg)
        and cfg.extractor != "echo"
    ):
        runtime = interp_service.InterpretationRuntime(cfg)
        try:
            if not runtime.available:
                raise HandlerError(
                    "cognitive model unavailable",
                    error_class=ErrorClass.model_unavailable,
                    stage="session_complete",
                )
        finally:
            runtime.close()

    session = complete_session(
        store, cfg, embedder, session_id,
        summary=p.get("summary") or "",
        abandoned=bool(p.get("abandoned", False)),
        summary_origin=p.get("summary_origin") or "assistant",
    )
    return {
        "session_id": session.id,
        "status": session.status.value if hasattr(session.status, "value") else str(session.status),
        "consolidation_status": (
            session.consolidation_status.value
            if hasattr(session.consolidation_status, "value")
            else str(session.consolidation_status)
        ),
        "summary_percept_id": session.summary_percept_id,
        "created_memory_ids": list(session.created_memory_ids or []),
    }


HANDLERS: dict[JobKind, Handler] = {
    JobKind.interpret_percept: handle_interpret_percept,
    JobKind.workspace_tick: handle_workspace_tick,
    JobKind.attention_evaluate: handle_attention_evaluate,
    JobKind.consolidate_daily: handle_consolidate_daily,
    JobKind.consolidate_weekly: handle_consolidate_weekly,
    JobKind.reembed_memory: handle_reembed_memory,
    JobKind.integrity_check: handle_integrity_check,
    JobKind.cognize_batch: handle_cognize_batch,
    JobKind.connector_reconcile: handle_connector_reconcile,
    JobKind.backfill_partition: handle_backfill_partition,
    JobKind.session_domain_resolve: handle_session_domain_resolve,
    JobKind.session_complete: handle_session_complete,
}


def dispatch(
    store: MemoryStore, cfg: Config, embedder: Embedder, job: RuntimeJob,
) -> dict[str, Any]:
    kind = job.kind if isinstance(job.kind, JobKind) else JobKind(str(job.kind))
    handler = HANDLERS.get(kind)
    if handler is None:
        raise HandlerError(f"no handler for {kind}", error_class=ErrorClass.permanent, stage="dispatch")
    return handler(store, cfg, embedder, job)
