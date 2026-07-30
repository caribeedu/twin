"""Durable cognitive runtime models.

Jobs are the unit of background cognitive work. Leases give exclusive
execution; dead letters capture terminal failures. This is not an autonomous
agent — handlers call the same cognitive core as CLI/MCP/API.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from twin import ids
from twin.clock import now_iso


class JobKind(str, Enum):
    interpret_percept = "interpret_percept"
    workspace_tick = "workspace_tick"
    attention_evaluate = "attention_evaluate"
    consolidate_daily = "consolidate_daily"
    consolidate_weekly = "consolidate_weekly"
    reembed_memory = "reembed_memory"
    integrity_check = "integrity_check"
    connector_reconcile = "connector_reconcile"
    backfill_partition = "backfill_partition"
    session_domain_resolve = "session_domain_resolve"
    session_complete = "session_complete"


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"          # retryable (or waiting backoff)
    cancelled = "cancelled"
    dead_letter = "dead_letter"


class ErrorClass(str, Enum):
    transient = "transient"
    model_unavailable = "model_unavailable"
    permanent = "permanent"
    invariant = "invariant"
    cancelled = "cancelled"


# Kinds that must never burn the attempt budget on LLM outage.
MODEL_GATED_KINDS = frozenset({
    JobKind.interpret_percept,
    JobKind.workspace_tick,
    JobKind.session_domain_resolve,
    JobKind.session_complete,
})


class RuntimeJob(BaseModel):
    id: str = Field(default_factory=ids.runtime_job_id)
    kind: JobKind
    status: JobStatus = JobStatus.pending
    priority: int = 100  # lower = sooner
    vault_id: str = "vault_general"
    idempotency_key: str = ""
    causal_parent_id: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    attempts: int = 0
    max_attempts: int = 8
    stage: str = ""
    error: str = ""
    error_class: str = ""
    worker_id: str = ""
    lease_token: str = ""
    lease_expires_at: str = ""
    not_before: str = ""
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    started_at: str = ""
    completed_at: str = ""


class WorkerLease(BaseModel):
    id: str = Field(default_factory=ids.worker_lease_id)
    worker_id: str
    job_id: str
    lease_token: str
    heartbeat_at: str = Field(default_factory=now_iso)
    expires_at: str = ""
    created_at: str = Field(default_factory=now_iso)


class DeadLetterItem(BaseModel):
    id: str = Field(default_factory=ids.dead_letter_id)
    job_id: str
    kind: str
    vault_id: str = "vault_general"
    attempts: int = 0
    stage: str = ""
    error: str = ""
    error_class: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    status: str = "open"  # open | requeued | discarded
