"""Local HTTP API + Twin review / continuity UI.

Run: twin serve → http://127.0.0.1:8765

JSON API powers MCP, CLI and the static SPA under ``twin/interfaces/web``.
The UI follows the Twin brand (purple + white) — review, search, pack,
memories and system status without a build step.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from ..cognition import extract_pending
from ..cognition.context_pack import build_context_pack
from ..cognition.observer import observe
from ..cognition.sessions import (
    complete_session,
    ensure_project,
    observe_session,
    record_feedback,
    start_session,
)
from ..cognition.workspace import workspace_tick
from ..config import ALL_DOMAINS, UNCLASSIFIED_DOMAIN
from ..judgment.profile import load_profile
from ..memory.models import (
    FeedbackVerdict,
    FindingStatus,
    MemoryStatus,
    TaskProfile,
)
from ..memory.search import search
from ..workspace import Workspace
from .web import STATIC_DIR, read_index

# domains accepted at the API edge; unclassified is a valid *target* (it
# means "operate default-deny"), never a memory domain
_TARGET_DOMAINS = set(ALL_DOMAINS) | {UNCLASSIFIED_DOMAIN}


def _validate_domain(value: Optional[str]) -> Optional[str]:
    if value is not None and value not in _TARGET_DOMAINS:
        raise ValueError(f"unknown domain {value!r}; expected one of "
                         f"{sorted(_TARGET_DOMAINS)}")
    return value


class IngestRequest(BaseModel):
    paths: list[str] = Field(min_length=1)


class ObserveRequest(BaseModel):
    current_text: str = Field(min_length=1, max_length=20_000)
    target_domain: Optional[str] = None

    _domain = field_validator("target_domain")(_validate_domain)


class WorkspaceTickRequest(BaseModel):
    current_text: str = Field(min_length=1, max_length=20_000)
    target_domain: Optional[str] = None
    session_id: str = ""
    cwd: Optional[str] = None
    interpret: bool = False
    input_mode: Literal["snapshot", "delta"] = "snapshot"
    sequence: Optional[int] = None
    idempotency_key: Optional[str] = None
    retry: bool = False

    _domain = field_validator("target_domain")(_validate_domain)


class ConsolidationRequest(BaseModel):
    apply: bool = False
    limit: int = Field(default=200, ge=1, le=5_000)
    retry: bool = False


class RuntimeEnqueueRequest(BaseModel):
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = ""
    vault_id: str = "vault_general"
    priority: int = Field(default=100, ge=0, le=10_000)
    max_attempts: int = Field(default=8, ge=1, le=100)


class PackRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20_000)
    target_domain: str = "technical"
    max_tokens: int = Field(default=1200, ge=100, le=16_000)
    include_judgment: bool = True
    include_candidates: bool = False  # packs are confirmed-only by default
    task_profile: TaskProfile = TaskProfile.general
    project: Optional[str] = None  # project name, alias or id
    client: Optional[str] = None  # registered tool client; omit → restricted
    persona: str = "individual"
    purpose: str = "memory_retrieval"
    audience: str = "self"
    api_token: Optional[str] = None
    mode: Literal["compact", "explainable", "references_only"] = "compact"
    session_id: Optional[str] = None
    request_scope: Optional[str] = None

    _domain = field_validator("target_domain")(_validate_domain)


class SessionStartRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20_000)
    client: str = Field(default="api", min_length=1, max_length=100)
    cwd: Optional[str] = None
    domain: Optional[str] = None
    project: Optional[str] = None
    task_profile: Optional[TaskProfile] = None
    max_tokens: int = Field(default=1200, ge=100, le=16_000)
    include_candidates: bool = False

    _domain = field_validator("domain")(_validate_domain)


class SessionObserveRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=50)
    ref: Optional[str] = Field(default=None, max_length=2_000)
    note: Optional[str] = Field(default=None, max_length=10_000)
    percept_id: Optional[str] = None  # artifact already ingested by a sensor


class SessionCompleteRequest(BaseModel):
    summary: str = Field(default="", max_length=50_000)
    abandoned: bool = False
    summary_origin: Literal["user", "assistant", "client", "derived"] = "client"
    user_confirmed: bool = False


class SessionFeedbackRequest(BaseModel):
    verdict: FeedbackVerdict
    memory_id: Optional[str] = None
    note: str = Field(default="", max_length=10_000)
    scope: Optional[Literal["session", "pack", "memory"]] = None


class ProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    repos: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)


class ProjectUpdateRequest(BaseModel):
    """Partial update — omitted fields keep their current value."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    aliases: Optional[list[str]] = None
    repos: Optional[list[str]] = None
    goals: Optional[list[str]] = None
    milestones: Optional[list[dict[str, Any]]] = None
    open_questions: Optional[list[str]] = None
    status: Optional[Literal["active", "paused", "done"]] = None
    metadata: Optional[dict[str, Any]] = None


class ConnectorAddRequest(BaseModel):
    connector_type: str = Field(min_length=1, max_length=100)
    source_owner: Literal["personal", "employer", "client", "opensource", "shared", "unknown"]
    vault_id: Optional[str] = None
    org_key: Optional[str] = None
    persona: str = "individual"
    default_domain: str = "work"
    display_name: str = ""
    external_account_id: str = ""
    secret: Optional[str] = None  # write-only; never returned
    configuration: Optional[dict[str, Any]] = None


class ConnectorSyncRequest(BaseModel):
    stream: Optional[str] = None
    emit_percepts: bool = True


class MergeRequest(BaseModel):
    memory_ids: list[str] = Field(min_length=2)
    title: Optional[str] = None
    summary: Optional[str] = None
    confirm_cross_scope_merge: bool = False
    human_confirmed_synthesis: bool = False
    output_type: Optional[str] = None
    output_domain: Optional[str] = None
    output_persona: Optional[str] = None
    output_project_id: Optional[str] = None
    output_canonical_claim: Optional[dict[str, Any]] = None
    set_output_project_id: bool = False
    set_output_canonical_claim: bool = False


class SplitRequest(BaseModel):
    parts: list[dict[str, Any]] = Field(min_length=2)


class ResolveRequest(BaseModel):
    """Resolve a review finding / neighbor relation for one memory."""

    action: str  # merge|contradict|supersede|supersede_by|dismiss|archive|split|…
    related_memory_id: Optional[str] = None
    finding_id: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    parts: Optional[list[dict[str, Any]]] = None
    confirm_cross_scope_merge: bool = False
    domain: Optional[str] = None
    sensitivity: Optional[str] = None


def _mem_dict(mem, store=None) -> dict[str, Any]:
    data = mem.model_dump()
    data["type"] = mem.type.value
    data["sensitivity"] = mem.sensitivity.value
    data["status"] = mem.status.value
    try:
        from ..cognition.quality import memory_altitude
        data["altitude"] = (mem.payload or {}).get("altitude") or memory_altitude(mem)
    except Exception:
        data["altitude"] = (mem.payload or {}).get("altitude") or "ground"
    data["condensed"] = bool(
        (mem.payload or {}).get("condensed")
        or (mem.payload or {}).get("merged_from")
    )
    if store is not None:
        try:
            from ..memory.provenance import memory_source_summary
            src = memory_source_summary(store, mem.id)
            data["sources"] = src.get("sensors") or []
            data["source_label"] = src.get("label") or ""
            data["source_refs"] = src.get("refs") or []
        except Exception:
            data["sources"] = []
            data["source_label"] = ""
            data["source_refs"] = []
        # Memories this one was condensed/merged from (for "Based in").
        based_in: list[dict[str, Any]] = []
        for mid in (mem.payload or {}).get("merged_from") or []:
            if not isinstance(mid, str):
                continue
            other = store.get_memory(mid)
            if other is None:
                based_in.append({
                    "id": mid, "title": mid, "status": "unknown",
                })
            else:
                based_in.append({
                    "id": other.id,
                    "title": other.title,
                    "status": other.status.value,
                    "type": other.type.value,
                })
        data["based_in"] = based_in
    else:
        data["based_in"] = []
    return data


def create_app(home: Optional[str] = None) -> FastAPI:
    ws = Workspace(home)
    app = FastAPI(title="twin", description="Personal Cognitive OS — local API")

    # -- JSON API --------------------------------------------------------

    @app.post("/api/ingest")
    def api_ingest(req: IngestRequest):
        new_ids, skipped = ws.ingest(req.paths)
        return {"ingested": new_ids, "skipped": skipped}

    @app.post("/api/extract")
    def api_extract(auto_approve: bool = False):
        from ..memory.models import MemoryStatus

        reports = extract_pending(ws.store, ws.cfg, ws.embedder)
        auto_approved: list[str] = []
        if auto_approve:
            for r in reports:
                for mid in r.inserted:
                    mem = ws.store.get_memory(mid)
                    if mem is not None and mem.status.value == "candidate":
                        ws.store.set_status(mid, MemoryStatus.confirmed)
                        auto_approved.append(mid)
        return [
            {
                "percept_id": r.percept_id, "extractor": r.extractor,
                "inserted": r.inserted, "duplicates": r.duplicates,
                "flagged_for_review": r.flagged_for_review,
                "pii_findings": r.pii_findings,
                "deferred": r.deferred,
                "interpretation_status": r.interpretation_status,
                "unresolved_references": r.unresolved_references,
                "auto_approved": [m for m in auto_approved if m in r.inserted],
            }
            for r in reports
        ]

    @app.get("/api/percepts")
    def api_percepts():
        return [p.model_dump() for p in ws.store.list_percepts()]

    @app.get("/api/memories")
    def api_memories(
        status: Optional[str] = None,
        domain: Optional[str] = None,
        type: Optional[str] = None,
        needs_review: Optional[bool] = None,
        limit: int = 500,
    ):
        memories = ws.store.list_memories(
            status=status, domain=domain, type_=type,
            needs_review=needs_review, limit=max(1, min(limit, 2000)),
        )
        return [_mem_dict(m, ws.store) for m in memories]

    @app.get("/api/memories/{memory_id}")
    def api_memory(memory_id: str):
        mem = ws.store.get_memory(memory_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        evidence = [e.model_dump() for e in ws.store.get_evidence(memory_id)]
        return {**_mem_dict(mem, ws.store), "evidence": evidence}

    @app.post("/api/memories/{memory_id}/review")
    def api_review(memory_id: str, action: str, domain: Optional[str] = None,
                   sensitivity: Optional[str] = None):
        from ..clock import now_iso
        from ..memory.lifecycle import archive_memory
        mem = ws.store.get_memory(memory_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        if domain:
            ws.store.update_memory(memory_id, domain=domain)
        if sensitivity:
            ws.store.update_memory(memory_id, sensitivity=sensitivity)
        if action == "approve":
            ws.store.set_status(memory_id, MemoryStatus.confirmed)
            ws.store.update_memory(memory_id, reviewed_at=now_iso(), needs_review=False)
        elif action == "reject":
            ws.store.set_status(memory_id, MemoryStatus.rejected)
            ws.store.update_memory(memory_id, reviewed_at=now_iso(), needs_review=False)
        elif action == "defer":
            ws.store.update_memory(memory_id, needs_review=True, review_reason="deferred")
        elif action == "archive":
            try:
                archive_memory(ws.store, memory_id)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        elif action != "update":
            raise HTTPException(
                400, "action must be approve | reject | update | defer | archive",
            )
        return _mem_dict(ws.store.get_memory(memory_id), ws.store)

    # -- memory formation ----------------------------------------------

    @app.get("/api/memory/candidates")
    def api_memory_candidates(state: Optional[str] = None, limit: int = 100):
        from ..memory.formation import list_candidates
        return [
            c.model_dump(mode="json")
            for c in list_candidates(ws.store, state=state, limit=limit)
        ]

    class FormationRejectRequest(BaseModel):
        reason: str = Field(min_length=1, max_length=2000)

    class FormationConfirmRequest(BaseModel):
        note: str = ""

    class FormationEditRequest(BaseModel):
        title: Optional[str] = None
        summary: Optional[str] = None
        domain: Optional[str] = None

    @app.post("/api/memory/candidates/{memory_id}/confirm")
    def api_formation_confirm(
        memory_id: str, req: FormationConfirmRequest = FormationConfirmRequest(),
    ):
        from ..memory.formation import confirm_candidate
        try:
            return confirm_candidate(
                ws.store, memory_id, note=req.note,
            ).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/memory/candidates/{memory_id}/reject")
    def api_formation_reject(memory_id: str, req: FormationRejectRequest):
        from ..memory.formation import reject_candidate
        try:
            return reject_candidate(
                ws.store, memory_id, reason=req.reason,
            ).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/memory/candidates/{memory_id}/edit")
    def api_formation_edit(memory_id: str, req: FormationEditRequest):
        from ..memory.formation import edit_candidate
        try:
            return edit_candidate(
                ws.store, memory_id,
                title=req.title, summary=req.summary, domain=req.domain,
            ).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/memory/candidates/{memory_id}/restore")
    def api_formation_restore(memory_id: str):
        from ..memory.formation import restore_candidate
        try:
            return restore_candidate(ws.store, memory_id).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/memory/{memory_id}/explain")
    def api_memory_explain(memory_id: str):
        from ..memory.formation import explain_memory
        try:
            return explain_memory(ws.store, memory_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/memory/{memory_id}/history")
    def api_memory_history(memory_id: str):
        from ..memory.formation import explain_memory
        try:
            return {"memory_id": memory_id, "history": explain_memory(ws.store, memory_id)["history"]}
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/search")
    def api_search(q: str, domain: str = "technical", type: Optional[str] = None,
                   limit: int = 10):
        result = search(ws.store, ws.embedder, q, target_domain=domain,
                        firewall=ws.firewall, type_=type, limit=limit)
        return {
            "hits": [{**_mem_dict(h.memory, ws.store), "score": h.score, "why": h.why} for h in result.hits],
            "blocked": [{"memory_id": b.memory_id, "reason": b.rule} for b in result.blocked],
        }

    def _resolve_project_id(project: Optional[str]) -> Optional[str]:
        if not project:
            return None
        found = ws.store.get_project(project) or ws.store.find_project(project)
        if found is None:
            raise HTTPException(404, f"project '{project}' not found")
        return found.id

    @app.post("/api/context_pack")
    def api_pack(req: PackRequest):
        from ..privacy.identity import resolve_access
        access = resolve_access(
            ws.store, surface="api", client=req.client,
            persona=req.persona, purpose=req.purpose, audience=req.audience,
            project_id=_resolve_project_id(req.project),
            requested_domains=[req.target_domain],
            api_token=req.api_token,
        )
        pack = build_context_pack(ws.store, ws.cfg, ws.embedder, req.query,
                                  target_domain=req.target_domain,
                                  max_tokens=req.max_tokens,
                                  include_judgment=req.include_judgment,
                                  include_candidates=req.include_candidates,
                                  task_profile=req.task_profile.value,
                                  project_id=_resolve_project_id(req.project),
                                  firewall=ws.firewall,
                                  access=access,
                                  session_id=req.session_id,
                                  mode=req.mode,
                                  request_scope=req.request_scope)
        return pack.to_dict()

    # -- Cognitive sessions ------------------------------------------------

    def _session_dict(session) -> dict[str, Any]:
        data = session.model_dump()
        data["status"] = session.status.value
        data["consolidation_status"] = session.consolidation_status.value
        return data

    @app.post("/api/sessions")
    def api_session_start(req: SessionStartRequest):
        try:
            started = start_session(
                ws.store, ws.cfg, ws.embedder, req.query,
                client=req.client, cwd=req.cwd, domain=req.domain,
                project=req.project,
                task_profile=req.task_profile.value if req.task_profile else None,
                max_tokens=req.max_tokens, include_candidates=req.include_candidates,
            )
        except ValueError as exc:
            # an explicit-but-unknown project must fail, never be inferred over
            raise HTTPException(404 if "not found" in str(exc) else 400, str(exc))
        return {
            "session": _session_dict(started.session),
            "context_pack": started.pack.__dict__,
            "reading_confidences": started.reading_confidences,
            "observer_mode": started.observer_mode,
            "needs_domain_confirmation": started.needs_domain_confirmation,
            "observer_fallback": started.observer_fallback,
        }

    @app.get("/api/sessions")
    def api_sessions(status: Optional[str] = None, project_id: Optional[str] = None):
        sessions = ws.store.list_sessions(status=status, project_id=project_id)
        return [_session_dict(s) for s in sessions]

    @app.get("/api/sessions/{session_id}")
    def api_session(session_id: str):
        session = ws.store.get_session(session_id)
        if session is None:
            raise HTTPException(404, "session not found")
        return _session_dict(session)

    @app.post("/api/sessions/{session_id}/observe")
    def api_session_observe(session_id: str, req: SessionObserveRequest):
        artifact: dict[str, Any] = {"kind": req.kind}
        if req.ref:
            artifact["ref"] = req.ref
        if req.note:
            artifact["note"] = req.note
        if req.percept_id:
            artifact["percept_id"] = req.percept_id
        try:
            session = observe_session(ws.store, session_id, artifact)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return _session_dict(session)

    @app.post("/api/sessions/{session_id}/complete")
    def api_session_complete(session_id: str, req: SessionCompleteRequest):
        try:
            session = complete_session(ws.store, ws.cfg, ws.embedder, session_id,
                                       summary=req.summary, abandoned=req.abandoned,
                                       summary_origin=req.summary_origin,
                                       user_confirmed=req.user_confirmed)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return _session_dict(session)

    @app.post("/api/sessions/{session_id}/feedback")
    def api_session_feedback(session_id: str, req: SessionFeedbackRequest):
        try:
            session = record_feedback(ws.store, session_id, req.verdict.value,
                                      memory_id=req.memory_id, note=req.note,
                                      scope=req.scope)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return _session_dict(session)

    @app.post("/api/sessions/cleanup")
    def api_sessions_cleanup(max_idle_hours: float = 24.0):
        from ..cognition.sessions import abandon_stale_sessions

        return {"abandoned": abandon_stale_sessions(ws.store, max_idle_hours)}

    # -- Projects ----------------------------------------------------------

    @app.post("/api/projects")
    def api_project_add(req: ProjectRequest):
        project = ensure_project(ws.store, req.name, repos=req.repos,
                                 aliases=req.aliases)
        return project.model_dump()

    @app.get("/api/projects")
    def api_projects(status: Optional[str] = None):
        return [p.model_dump() for p in ws.store.list_projects(status=status)]

    @app.get("/api/projects/{project_id}")
    def api_project(project_id: str):
        project = ws.store.get_project(project_id) or ws.store.find_project(project_id)
        if project is None:
            raise HTTPException(404, "project not found")
        return project.model_dump()

    @app.patch("/api/projects/{project_id}")
    def api_project_update(project_id: str, req: ProjectUpdateRequest):
        project = ws.store.get_project(project_id) or ws.store.find_project(project_id)
        if project is None:
            raise HTTPException(404, "project not found")
        for field_name, value in req.model_dump(exclude_none=True).items():
            setattr(project, field_name, value)
        ws.store.update_project(project)
        return ws.store.get_project(project.id).model_dump()

    @app.post("/api/memories/{memory_id}/promote")
    def api_promote(memory_id: str):
        from ..judgment.profile import promote_memory

        mem = ws.store.get_memory(memory_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        try:
            section = promote_memory(ws.cfg.judgment_path, mem, store=ws.store)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        ws.store.update_memory(memory_id, payload={**mem.payload, "promoted_to_judgment": True})
        return {"memory_id": memory_id, "promoted_to": section}

    @app.post("/api/memories/{memory_id}/supersede/{old_id}")
    def api_supersede(memory_id: str, old_id: str):
        from ..memory.lifecycle import supersede

        try:
            result = supersede(ws.store, memory_id, old_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return result.__dict__

    @app.post("/api/memories/{memory_id}/contradict/{other_id}")
    def api_contradict(memory_id: str, other_id: str):
        from ..memory.lifecycle import contradict

        try:
            result = contradict(ws.store, memory_id, other_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return result.__dict__

    @app.get("/api/metrics")
    def api_metrics():
        from ..memory.metrics import compute_metrics

        return compute_metrics(ws.store)

    @app.post("/api/observer")
    def api_observer(req: ObserveRequest):
        s = observe(ws.store, ws.cfg, ws.embedder, req.current_text, req.target_domain)
        return {
            "inferred_domain": s.inferred_domain,
            "suggested_context": s.suggested_context,
            "blocked_context": s.blocked_context,
        }

    @app.post("/api/workspace/tick")
    def api_workspace_tick(req: WorkspaceTickRequest):
        result = workspace_tick(
            ws.store, ws.cfg, ws.embedder, req.current_text,
            session_id=req.session_id,
            target_domain=req.target_domain,
            cwd=req.cwd,
            interpret=req.interpret,
            input_mode=req.input_mode,
            sequence=req.sequence,
            idempotency_key=req.idempotency_key,
            retry=req.retry,
            firewall=ws.firewall,
        )
        return result.to_dict()

    @app.post("/api/consolidate/{kind}")
    def api_consolidate(kind: str, req: ConsolidationRequest):
        from ..cognition.consolidation_cycle import run_consolidation_cycle
        if kind not in ("daily", "weekly"):
            raise HTTPException(400, "kind must be daily or weekly")
        result = run_consolidation_cycle(
            ws.store, ws.cfg, ws.embedder,
            kind=kind, dry_run=not req.apply, analyze_limit=req.limit,
            retry=req.retry,
        )
        return result.to_dict()

    # -- durable cognitive runtime ---------------------------------------

    @app.post("/api/runtime/jobs")
    def api_runtime_enqueue(req: RuntimeEnqueueRequest):
        from ..runtime.models import JobKind
        from ..runtime.queue import RuntimeQueue
        try:
            kind = JobKind(req.kind)
        except ValueError as exc:
            raise HTTPException(400, f"unknown kind: {req.kind}") from exc
        job = RuntimeQueue(ws.store).enqueue(
            kind,
            payload=req.payload,
            idempotency_key=req.idempotency_key,
            vault_id=req.vault_id,
            priority=req.priority,
            max_attempts=req.max_attempts,
        )
        return job.model_dump(mode="json")

    @app.get("/api/runtime/jobs/{job_id}")
    def api_runtime_job(job_id: str):
        job = ws.store.get_runtime_job(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        return job.model_dump(mode="json")

    @app.post("/api/runtime/jobs/{job_id}/retry")
    def api_runtime_retry(job_id: str):
        from ..runtime.queue import RuntimeQueue
        job = RuntimeQueue(ws.store).retry(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        return job.model_dump(mode="json")

    @app.post("/api/runtime/jobs/{job_id}/cancel")
    def api_runtime_cancel(job_id: str):
        from ..runtime.queue import RuntimeQueue
        ok = RuntimeQueue(ws.store).cancel(job_id)
        if not ok:
            raise HTTPException(409, "job not cancellable")
        return {"id": job_id, "cancelled": True}

    @app.get("/api/runtime/health")
    def api_runtime_health():
        return {
            "ok": True,
            "queue": ws.store.runtime_queue_depth(),
            "dead_letters_open": len(ws.store.list_runtime_dead_letters(limit=500)),
        }

    class BackupCreateRequest(BaseModel):
        dest: str

    class BackupValidateRequest(BaseModel):
        bundle: str

    class BackupRestoreRequest(BaseModel):
        bundle: str
        target_db: str

    @app.post("/api/backup")
    def api_backup_create(req: BackupCreateRequest):
        from pathlib import Path
        from ..sovereignty.backup import create_backup
        db_path = Path(ws.store.path) if hasattr(ws.store, "path") else None
        manifest = create_backup(ws.store, req.dest, copy_sqlite_db=db_path)
        return manifest.model_dump(mode="json")

    @app.post("/api/backup/validate")
    def api_backup_validate(req: BackupValidateRequest):
        from ..sovereignty.backup import validate_backup
        return validate_backup(req.bundle)

    @app.post("/api/restore/validate")
    def api_restore_validate(req: BackupValidateRequest):
        from ..sovereignty.backup import validate_backup
        return validate_backup(req.bundle)

    @app.post("/api/restore")
    def api_restore(req: BackupRestoreRequest):
        from ..sovereignty.backup import restore_sqlite_backup
        return restore_sqlite_backup(req.bundle, req.target_db)

    @app.get("/api/health/cognition")
    def api_health_cognition():
        from ..sovereignty.integrity import run_integrity_checks
        return run_integrity_checks(ws.store)

    class SessionEventRequest(BaseModel):
        text: str = ""
        kind: str = "delta"
        sequence: Optional[int] = None
        external_session_id: str = ""
        client: str = ""
        payload: dict[str, Any] = Field(default_factory=dict)

    class SessionCheckpointRequest(BaseModel):
        summary: str = ""
        active_goal: str = ""
        unresolved_items: list[str] = Field(default_factory=list)
        constraints: list[str] = Field(default_factory=list)

    class SessionCloseRequest(BaseModel):
        summary: str = ""
        abandoned: bool = False
        summary_origin: str = "client"
        user_confirmed: bool = False
        closure: dict[str, Any] = Field(default_factory=dict)
        related_session_ids: list[str] = Field(default_factory=list)

    @app.post("/api/sessions/{session_id}/events")
    def api_session_event(session_id: str, req: SessionEventRequest):
        from ..cognition.session_lifecycle import append_session_delta
        try:
            ev = append_session_delta(
                ws.store, session_id,
                text=req.text, kind=req.kind, sequence=req.sequence,
                external_session_id=req.external_session_id,
                client=req.client, payload=req.payload,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return ev.model_dump(mode="json")

    @app.get("/api/sessions/{session_id}/attention")
    def api_session_attention(session_id: str, evaluate: bool = False):
        from ..cognition.attention import evaluate_attention
        if evaluate:
            outcomes = evaluate_attention(
                ws.store, ws.cfg, ws.embedder, session_id,
            )
            return {"session_id": session_id, "outcomes": [o.to_dict() for o in outcomes]}
        rows = ws.store.list_attention_emissions(session_id, limit=50)
        return {
            "session_id": session_id,
            "outcomes": [o.to_dict() for o in rows],
        }

    class AttentionFeedbackRequest(BaseModel):
        verdict: str = Field(min_length=1, max_length=40)

    @app.post("/api/attention/{emission_id}/feedback")
    def api_attention_feedback(emission_id: str, req: AttentionFeedbackRequest):
        from ..cognition.attention import feedback_attention
        em = feedback_attention(ws.store, emission_id, verdict=req.verdict)
        if em is None:
            raise HTTPException(404, "emission not found")
        return em.to_dict()

    @app.post("/api/sessions/{session_id}/checkpoint")
    def api_session_checkpoint(session_id: str, req: SessionCheckpointRequest):
        from ..cognition.session_lifecycle import checkpoint_session
        try:
            cp = checkpoint_session(
                ws.store, session_id,
                summary=req.summary, active_goal=req.active_goal,
                unresolved_items=req.unresolved_items,
                constraints=req.constraints,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return cp.model_dump(mode="json")

    @app.post("/api/sessions/{session_id}/close")
    def api_session_close(session_id: str, req: SessionCloseRequest):
        from ..cognition.session_lifecycle import close_session_structured
        try:
            session, closure = close_session_structured(
                ws.store, ws.cfg, ws.embedder, session_id,
                summary=req.summary, abandoned=req.abandoned,
                closure=req.closure, related_session_ids=req.related_session_ids,
                summary_origin=req.summary_origin,
                user_confirmed=req.user_confirmed,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {
            "session": session.model_dump(mode="json"),
            "closure": closure.model_dump(mode="json"),
        }

    @app.post("/api/sessions/{session_id}/reopen")
    def api_session_reopen(session_id: str):
        from ..cognition.session_lifecycle import reopen_session
        try:
            session = reopen_session(ws.store, session_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return session.model_dump(mode="json")

    @app.post("/api/sessions/{session_id}/pause")
    def api_session_pause(session_id: str):
        from ..cognition.session_lifecycle import pause_session
        try:
            return pause_session(ws.store, session_id).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/sessions/{session_id}/resume")
    def api_session_resume(session_id: str):
        from ..cognition.session_lifecycle import resume_session
        try:
            return resume_session(ws.store, session_id).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/sessions/{session_id}/closure")
    def api_session_closure(session_id: str):
        from ..cognition.session_lifecycle import get_session_closure
        closure = get_session_closure(ws.store, session_id)
        if closure is None:
            raise HTTPException(404, "closure not found")
        return closure.model_dump(mode="json")

    # -- review / quality / consolidation --------------------------------

    @app.get("/api/review/queue")
    def api_review_queue(
        project: Optional[str] = None,
        domain: Optional[str] = None,
        type: Optional[str] = None,
        sensitivity: Optional[str] = None,
        min_priority: float = 0.0,
        conflicts: bool = False,
        limit: int = 100,
    ):
        from ..cognition.quality import review_queue
        project_id = _resolve_project_id(project) if project else None
        queue = review_queue(
            ws.store, project_id=project_id, domain=domain, type_=type,
            sensitivity=sensitivity, min_priority=min_priority,
            conflicts_only=conflicts, limit=limit,
        )
        return [_mem_dict(m, ws.store) for m in queue]

    class BatchCreateRequest(BaseModel):
        name: str = Field(min_length=1, max_length=200)
        query: dict[str, Any] = Field(default_factory=dict)
        memory_ids: list[str] = Field(default_factory=list)

    class BatchApplyRequest(BaseModel):
        action: str
        memory_ids: Optional[list[str]] = None
        force: bool = False
        preview_token: Optional[str] = None

    def _finding_dict(finding, store) -> dict[str, Any]:
        data = finding.model_dump(mode="json")
        rid = finding.related_memory_id
        if rid:
            related = store.get_memory(rid)
            if related is not None:
                data["related"] = {
                    "id": related.id,
                    "title": related.title,
                    "summary": related.summary,
                    "status": getattr(related.status, "value", related.status),
                    "type": getattr(related.type, "value", related.type),
                    "domain": getattr(related.domain, "value", related.domain),
                }
        return data

    def _close_finding(store, memory_id: str, finding_id: Optional[str], *,
                       status: FindingStatus = FindingStatus.resolved,
                       operation_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        if not finding_id or not hasattr(store, "get_findings"):
            return None
        from ..clock import now_iso
        findings = store.get_findings(memory_id, unresolved_only=False)
        finding = next((f for f in findings if f.id == finding_id), None)
        if finding is None:
            return None
        finding.status = status
        finding.resolved = True
        finding.resolved_at = now_iso()
        if operation_id:
            finding.resolution_operation_id = operation_id
        store.update_finding(finding)
        return _finding_dict(finding, store)

    @app.post("/api/review/batches")
    def api_create_batch(req: BatchCreateRequest):
        from ..memory.batches import create_batch
        batch = create_batch(ws.store, req.name, query=req.query, memory_ids=req.memory_ids or None)
        return batch.model_dump()

    @app.get("/api/review/batches/{batch_id}")
    def api_get_batch(batch_id: str):
        from ..memory.batches import get_batch
        batch = get_batch(ws.store, batch_id)
        if batch is None:
            raise HTTPException(404, "batch not found")
        return batch.model_dump()

    @app.post("/api/review/batches/{batch_id}/apply")
    def api_apply_batch(batch_id: str, req: BatchApplyRequest):
        from ..memory.automation import batch_apply, batch_preview
        from ..memory.batches import get_batch
        batch = get_batch(ws.store, batch_id)
        if batch is None:
            raise HTTPException(404, "batch not found")
        ids = req.memory_ids or batch.memory_ids
        preview = batch_preview(ws.store, ids, req.action)
        if req.force is False and preview.get("requires_individual_review"):
            return {**preview, "preview_only": True}
        return batch_apply(
            ws.store, ids, req.action,
            force=req.force, preview_token=req.preview_token,
        )

    @app.get("/api/memories/{memory_id}/neighbors")
    def api_neighbors(memory_id: str):
        from ..cognition.quality import discover_neighbors
        mem = ws.store.get_memory(memory_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        neighbors = discover_neighbors(ws.store, ws.embedder, mem)
        return [
            {**_mem_dict(n, ws.store), "similarity": sim, "reason": reason}
            for n, sim, reason in neighbors
        ]

    @app.get("/api/memories/{memory_id}/quality")
    def api_quality(memory_id: str, refresh: bool = False):
        from ..cognition.quality import analyze_memory
        mem = ws.store.get_memory(memory_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        # Prefer stored findings unless caller asks to re-analyze.
        if not refresh and hasattr(ws.store, "get_findings"):
            stored = ws.store.get_findings(memory_id, unresolved_only=True)
            if stored:
                from ..cognition.quality import memory_altitude
                return {
                    "memory_id": memory_id,
                    "quality_score": mem.quality_score,
                    "review_priority": mem.review_priority,
                    "impact": mem.impact,
                    "issues": [_finding_dict(f, ws.store) for f in stored],
                    "suggested_action": (
                        stored[0].suggested_action.value if stored else "none"
                    ),
                    "requires_human_review": bool(mem.needs_review),
                    "quality_flags": list(mem.quality_flags or []),
                    "neighbors": [],
                    "altitude": memory_altitude(mem),
                    "from_store": True,
                }
        try:
            report = analyze_memory(ws.store, ws.embedder, memory_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        data = report.model_dump(mode="json")
        data["issues"] = [_finding_dict(f, ws.store) for f in report.issues]
        data["from_store"] = False
        return data

    @app.get("/api/memories/{memory_id}/findings")
    def api_findings(memory_id: str, unresolved_only: bool = True):
        mem = ws.store.get_memory(memory_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        if not hasattr(ws.store, "get_findings"):
            return []
        return [
            _finding_dict(f, ws.store)
            for f in ws.store.get_findings(memory_id, unresolved_only=unresolved_only)
        ]

    @app.post("/api/memories/{memory_id}/findings/{finding_id}/dismiss")
    def api_dismiss_finding(memory_id: str, finding_id: str):
        closed = _close_finding(
            ws.store, memory_id, finding_id, status=FindingStatus.dismissed,
        )
        if closed is None:
            raise HTTPException(404, "finding not found")
        return closed

    @app.post("/api/memories/{memory_id}/resolve")
    def api_resolve(memory_id: str, req: ResolveRequest):
        from ..clock import now_iso
        from ..memory.lifecycle import (
            archive_memory,
            contradict,
            merge_memories,
            split_memory,
            supersede,
        )

        mem = ws.store.get_memory(memory_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        if req.domain:
            ws.store.update_memory(memory_id, domain=req.domain)
        if req.sensitivity:
            ws.store.update_memory(memory_id, sensitivity=req.sensitivity)

        action = (req.action or "").strip().lower()
        related_id = req.related_memory_id
        result: dict[str, Any] = {"action": action, "memory_id": memory_id}
        op_id: Optional[str] = None
        remove_ids: list[str] = []
        finding_status = FindingStatus.resolved

        try:
            if action == "dismiss":
                finding_status = FindingStatus.dismissed
            elif action == "merge":
                if not related_id:
                    raise ValueError("related_memory_id required for merge")
                merged = merge_memories(
                    ws.store, [memory_id, related_id],
                    title=req.title, summary=req.summary,
                    embedder=ws.embedder,
                    confirm_cross_scope_merge=req.confirm_cross_scope_merge,
                    human_confirmed_synthesis=True,
                )
                op_id = merged.operation_id
                merged_id = merged.extras.get("merged_id")
                result.update({
                    "merged_id": merged_id,
                    "operation_id": op_id,
                    **merged.extras,
                })
                remove_ids = [memory_id, related_id]
            elif action == "contradict":
                if not related_id:
                    raise ValueError("related_memory_id required for contradict")
                out = contradict(ws.store, memory_id, related_id)
                op_id = out.operation_id
                result["operation_id"] = op_id
            elif action == "supersede":
                if not related_id:
                    raise ValueError("related_memory_id required for supersede")
                out = supersede(ws.store, memory_id, related_id)
                # Keep the newer claim as confirmed — matches legacy review form.
                ws.store.set_status(memory_id, MemoryStatus.confirmed)
                ws.store.update_memory(
                    memory_id, reviewed_at=now_iso(), needs_review=False,
                )
                op_id = out.operation_id
                result["operation_id"] = op_id
                remove_ids = [memory_id, related_id]
            elif action == "supersede_by":
                if not related_id:
                    raise ValueError("related_memory_id required for supersede_by")
                out = supersede(ws.store, related_id, memory_id)
                related_mem = ws.store.get_memory(related_id)
                if related_mem is not None and related_mem.status == MemoryStatus.candidate:
                    ws.store.set_status(related_id, MemoryStatus.confirmed)
                    ws.store.update_memory(
                        related_id, reviewed_at=now_iso(), needs_review=False,
                    )
                op_id = out.operation_id
                result["operation_id"] = op_id
                remove_ids = [memory_id, related_id]
            elif action == "split":
                parts = req.parts or []
                if len(parts) < 2:
                    raise ValueError("split requires at least two parts")
                out = split_memory(ws.store, memory_id, parts, embedder=ws.embedder)
                op_id = out.operation_id
                result.update({
                    "children": out.extras.get("children"),
                    "operation_id": op_id,
                })
                remove_ids = [memory_id]
            elif action == "archive":
                out = archive_memory(ws.store, memory_id)
                op_id = out.operation_id
                result["operation_id"] = op_id
                remove_ids = [memory_id]
            elif action == "request_evidence":
                ws.store.update_memory(
                    memory_id, needs_review=True,
                    review_reason="more evidence requested",
                    quality_flags=list(set((mem.quality_flags or []) + ["weak_evidence"])),
                )
            elif action == "defer":
                ws.store.update_memory(
                    memory_id, needs_review=True, review_reason="deferred",
                )
            elif action == "confirm":
                ws.store.set_status(memory_id, MemoryStatus.confirmed)
                ws.store.update_memory(
                    memory_id, reviewed_at=now_iso(), needs_review=False,
                )
                remove_ids = [memory_id]
            elif action == "reject":
                ws.store.set_status(memory_id, MemoryStatus.rejected)
                ws.store.update_memory(
                    memory_id, reviewed_at=now_iso(), needs_review=False,
                )
                remove_ids = [memory_id]
            else:
                raise HTTPException(
                    400,
                    "unknown action; expected merge | contradict | supersede | "
                    "supersede_by | dismiss | archive | split | request_evidence | "
                    "defer | confirm | reject",
                )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        closed = _close_finding(
            ws.store, memory_id, req.finding_id,
            status=finding_status, operation_id=op_id,
        )
        if closed is not None:
            result["finding"] = closed
        result["removed_from_queue"] = remove_ids
        result["memory"] = _mem_dict(ws.store.get_memory(memory_id), ws.store) \
            if ws.store.get_memory(memory_id) else None
        return result

    @app.get("/api/memories/{memory_id}/provenance")
    def api_provenance(memory_id: str):
        from ..memory.provenance import memory_provenance
        try:
            return memory_provenance(ws.store, memory_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/memories/merge")
    def api_merge(req: MergeRequest):
        from ..memory.lifecycle import merge_memories
        from ..memory.models import CanonicalClaim
        merge_kwargs: dict[str, Any] = {
            "title": req.title,
            "summary": req.summary,
            "embedder": ws.embedder,
            "confirm_cross_scope_merge": req.confirm_cross_scope_merge,
            "human_confirmed_synthesis": req.human_confirmed_synthesis,
            "output_type": req.output_type,
            "output_domain": req.output_domain,
            "output_persona": req.output_persona,
        }
        if req.set_output_project_id or req.output_project_id is not None:
            merge_kwargs["output_project_id"] = req.output_project_id
        if req.set_output_canonical_claim or req.output_canonical_claim is not None:
            claim = req.output_canonical_claim
            merge_kwargs["output_canonical_claim"] = (
                CanonicalClaim(**claim) if isinstance(claim, dict) else claim
            )
        try:
            result = merge_memories(ws.store, req.memory_ids, **merge_kwargs)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"action": result.action, "merged_id": result.extras.get("merged_id"),
                "operation_id": result.operation_id, **result.extras}

    @app.post("/api/memories/{memory_id}/split")
    def api_split(memory_id: str, req: SplitRequest):
        from ..memory.lifecycle import split_memory
        try:
            result = split_memory(ws.store, memory_id, req.parts, embedder=ws.embedder)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"action": result.action, "children": result.extras.get("children"),
                "operation_id": result.operation_id}

    @app.post("/api/memories/{memory_id}/archive")
    def api_archive(memory_id: str):
        from ..memory.lifecycle import archive_memory
        try:
            result = archive_memory(ws.store, memory_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"action": result.action, "operation_id": result.operation_id}

    @app.post("/api/memories/{memory_id}/request-evidence")
    def api_request_evidence(memory_id: str):
        mem = ws.store.get_memory(memory_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        ws.store.update_memory(
            memory_id, needs_review=True,
            review_reason="more evidence requested",
            quality_flags=list(set(mem.quality_flags + ["weak_evidence"])),
        )
        return _mem_dict(ws.store.get_memory(memory_id), ws.store)

    @app.get("/api/artifacts/{artifact_id}")
    def api_artifact(artifact_id: str):
        if not hasattr(ws.store, "get_artifact"):
            raise HTTPException(501, "artifacts not supported")
        art = ws.store.get_artifact(artifact_id)
        if art is None:
            raise HTTPException(404, "artifact not found")
        return art.model_dump()

    @app.delete("/api/artifacts/{artifact_id}")
    def api_delete_artifact(artifact_id: str, dry_run: bool = True):
        from ..memory.retention import delete_artifact
        try:
            return delete_artifact(ws.store, artifact_id, dry_run=dry_run)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/evals/extraction")
    def api_eval_extraction():
        from pathlib import Path
        from ..evals import default_eval_root, run_extraction_eval
        run = run_extraction_eval(
            ws.store, ws.cfg, ws.embedder,
            default_eval_root() / "extraction",
        )
        return {"id": run.id, "kind": run.kind, "summary": run.summary,
                "cases": [c.__dict__ for c in run.cases]}

    @app.post("/api/evals/retrieval")
    def api_eval_retrieval():
        from ..evals import default_eval_root, run_retrieval_eval
        run = run_retrieval_eval(
            ws.store, ws.embedder, default_eval_root() / "retrieval",
            firewall=ws.firewall,
        )
        return {"id": run.id, "kind": run.kind, "summary": run.summary,
                "cases": [c.__dict__ for c in run.cases]}

    @app.get("/api/judgment")
    def api_judgment():
        """YAML bootstrap fields plus active DB items when present."""
        payload = dict(load_profile(ws.cfg.judgment_path))
        if hasattr(ws.store, "list_judgment_items"):
            payload["items"] = [
                i.model_dump(mode="json")
                for i in ws.store.list_judgment_items(status="active")
            ]
            v = ws.store.get_active_judgment_version()
            payload["active_version"] = v.model_dump(mode="json") if v else None
        return payload

    class JudgmentImportRequest(BaseModel):
        apply: bool = False

    class ProposalApproveRequest(BaseModel):
        preview_token: str
        edits: Optional[dict[str, Any]] = None
        confirm_constitutional: bool = False

    class ProposalPreviewRequest(BaseModel):
        edits: Optional[dict[str, Any]] = None

    class JudgmentSimulateRequest(BaseModel):
        query: str
        domain: str = "technical"
        task_profile: str = "architecture"
        project_id: Optional[str] = None
        options: Optional[list[str]] = None

    class JudgmentApplicableRequest(BaseModel):
        domain: str = "technical"
        persona: str = "individual"
        task_profile: str = "general"
        project_id: Optional[str] = None
        audience: Optional[str] = None
        client: Optional[str] = None
        project_stage: Optional[str] = None
        query: str = ""

    @app.get("/api/judgment/items")
    def api_judgment_items(status: str = "active", kind: Optional[str] = None):
        return [i.model_dump(mode="json") for i in ws.store.list_judgment_items(
            status=status, kind=kind,
        )]

    @app.get("/api/judgment/items/{judgment_id}")
    def api_judgment_item(judgment_id: str):
        item = ws.store.get_judgment_item(judgment_id)
        if item is None:
            raise HTTPException(404, "not found")
        return item.model_dump(mode="json")

    @app.get("/api/judgment/versions")
    def api_judgment_versions():
        return [v.model_dump(mode="json") for v in ws.store.list_judgment_versions()]

    @app.post("/api/judgment/versions/{version_id}/restore")
    def api_judgment_restore(version_id: str):
        from ..judgment.versions import restore_version
        try:
            ver = restore_version(ws.store, version_id, actor="api")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return ver.model_dump(mode="json")

    @app.get("/api/judgment/snapshots/{snapshot_id}/explain")
    def api_judgment_snapshot_explain(snapshot_id: str):
        from ..judgment.explain import explain_judgment_snapshot
        try:
            return explain_judgment_snapshot(ws.store, snapshot_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/personas")
    def api_personas():
        from ..privacy.identity import ensure_local_identity
        ensure_local_identity(ws.store)
        return [p.model_dump(mode="json") for p in ws.store.list_personas()]

    @app.get("/api/judgment/proposals")
    def api_judgment_proposals(status: str = "pending"):
        return [p.model_dump(mode="json") for p in ws.store.list_judgment_proposals(status=status)]

    @app.post("/api/judgment/proposals/generate")
    def api_generate_proposals(domain: str = "technical"):
        from ..judgment.proposals import propose_from_pattern
        return [p.model_dump(mode="json") for p in propose_from_pattern(ws.store, domain=domain)]

    @app.post("/api/judgment/proposals/{proposal_id}/preview")
    def api_preview_proposal(proposal_id: str, req: ProposalPreviewRequest = ProposalPreviewRequest()):
        from ..judgment.proposals import preview_proposal
        try:
            return preview_proposal(ws.store, proposal_id, edits=req.edits)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/judgment/proposals/{proposal_id}/approve")
    def api_approve_proposal(proposal_id: str, req: ProposalApproveRequest):
        from ..judgment.proposals import approve_proposal
        try:
            return approve_proposal(
                ws.store, proposal_id, preview_token=req.preview_token,
                edits=req.edits, confirm_constitutional=req.confirm_constitutional,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/judgment/proposals/{proposal_id}/reject")
    def api_reject_proposal(proposal_id: str, reason: str = ""):
        from ..judgment.proposals import reject_proposal
        try:
            return reject_proposal(ws.store, proposal_id, reason=reason).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/judgment/import")
    def api_judgment_import(req: JudgmentImportRequest):
        from ..judgment.yaml_io import apply_yaml_import, preview_yaml_import
        preview = preview_yaml_import(ws.cfg.judgment_path)
        if not req.apply:
            return {"preview": preview, "count": len(preview)}
        return apply_yaml_import(ws.store, ws.cfg.judgment_path, classifications=preview)

    @app.post("/api/judgment/applicable")
    def api_judgment_applicable(req: JudgmentApplicableRequest):
        from ..judgment.application import applicable_pack
        return applicable_pack(
            ws.store, domain=req.domain, persona=req.persona,
            task_profile=req.task_profile, project_id=req.project_id,
            audience=req.audience, client=req.client,
            project_stage=req.project_stage, query=req.query,
        )

    @app.post("/api/judgment/simulate")
    def api_judgment_simulate(req: JudgmentSimulateRequest):
        from ..judgment.simulate import simulate
        return simulate(
            ws.store, req.query, domain=req.domain, task_profile=req.task_profile,
            project_id=req.project_id, options=req.options,
        )

    # -- connectors  ------------------------------------------------
    #
    # Connector administration is a privileged surface: every endpoint
    # resolves the caller's identity (x-twin-client / x-twin-token headers)
    # and requires a specific connector:* capability. Global API access
    # never implies connector authority, and credentials never return.
    from fastapi import Header

    from ..connectors import build_credential_store as _bcs
    from ..connectors import (
        CAP_BACKFILL,
        CAP_CONFIGURE,
        CAP_CREDENTIALS,
        CAP_OPERATE,
        CAP_READ,
        CAP_READ_ERRORS,
        CAP_REVOKE,
        CAP_SYNC,
        add_connector_instance,
        authorize_connector,
        backfill_preview,
        connector_health,
        pause_connector,
        register_source_account,
        resume_connector,
        retry_dead_letter,
        revoke_connector,
        sync_connector,
        validate_connector,
        visible_connectors,
    )
    _conn_creds_cache: dict[str, Any] = {}

    def _conn_creds():
        # built lazily so a missing crypto backend fails the connector call,
        # not the whole API process
        if "store" not in _conn_creds_cache:
            _conn_creds_cache["store"] = _bcs(ws.cfg.home)
        return _conn_creds_cache["store"]

    def _connector_access(client: Optional[str], token: Optional[str],
                          capability: str, connector_id: Optional[str] = None):
        from ..privacy.identity import resolve_access
        access = resolve_access(ws.store, surface="api", client=client,
                                api_token=token)
        auth = authorize_connector(ws.store, access, capability,
                                   connector_id=connector_id)
        if not auth.allowed:
            raise HTTPException(status_code=403, detail=auth.reason)
        return access

    def _instance_dict(inst) -> dict[str, Any]:
        acc = ws.store.get_source_account(inst.account_id)
        return {
            "connector_id": inst.id,
            "connector_type": inst.connector_type,
            "status": inst.status.value,
            "account_id": inst.account_id,
            "has_credential": bool(inst.credential_ref),  # never the secret itself
            "source_owner": acc.source_owner.value if acc else None,
            "vault_id": acc.vault_id if acc else None,
            "configuration": inst.configuration,
        }

    @app.post("/api/connectors")
    def api_connector_add(
        req: ConnectorAddRequest,
        x_twin_client: Optional[str] = Header(default=None),
        x_twin_token: Optional[str] = Header(default=None),
    ):
        access = _connector_access(x_twin_client, x_twin_token, CAP_CONFIGURE)
        if req.secret:  # supplying a secret is a separate authority
            _connector_access(x_twin_client, x_twin_token, CAP_CREDENTIALS)
        try:
            acc = register_source_account(
                ws.store, connector_type=req.connector_type,
                source_owner=req.source_owner, vault_id=req.vault_id,
                org_key=req.org_key, persona=req.persona,
                default_domain=req.default_domain, display_name=req.display_name,
                external_account_id=req.external_account_id,
                # the account belongs to the resolved principal, never a default
                owner_principal_id=access.principal_id,
            )
            inst = add_connector_instance(
                ws.store, _conn_creds(), account_id=acc.id, secret=req.secret,
                configuration=req.configuration,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return _instance_dict(inst)

    @app.get("/api/connectors")
    def api_connectors(
        x_twin_client: Optional[str] = Header(default=None),
        x_twin_token: Optional[str] = Header(default=None),
    ):
        access = _connector_access(x_twin_client, x_twin_token, CAP_READ)
        return [_instance_dict(i) for i in visible_connectors(ws.store, access)]

    @app.get("/api/connectors/{connector_id}")
    def api_connector(
        connector_id: str,
        x_twin_client: Optional[str] = Header(default=None),
        x_twin_token: Optional[str] = Header(default=None),
    ):
        _connector_access(x_twin_client, x_twin_token, CAP_READ, connector_id)
        inst = ws.store.get_connector_instance(connector_id)
        if inst is None:
            raise HTTPException(status_code=404, detail="connector not found")
        return {**_instance_dict(inst), "health": connector_health(ws.store, connector_id)}

    @app.post("/api/connectors/{connector_id}/validate")
    def api_connector_validate(
        connector_id: str,
        x_twin_client: Optional[str] = Header(default=None),
        x_twin_token: Optional[str] = Header(default=None),
    ):
        _connector_access(x_twin_client, x_twin_token, CAP_READ, connector_id)
        try:
            health = validate_connector(ws.store, _conn_creds(), connector_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"status": health.status.value, "detail": health.detail}

    @app.post("/api/connectors/{connector_id}/sync")
    def api_connector_sync(
        connector_id: str, req: ConnectorSyncRequest,
        x_twin_client: Optional[str] = Header(default=None),
        x_twin_token: Optional[str] = Header(default=None),
    ):
        _connector_access(x_twin_client, x_twin_token, CAP_SYNC, connector_id)
        try:
            result = sync_connector(
                ws.store, _conn_creds(), connector_id,
                streams=[req.stream] if req.stream else None,
                emit_percepts=req.emit_percepts,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {
            "health": result.health.value,
            "percepts": result.percepts,
            "streams": [
                {"stream": s.stream, "committed": s.committed,
                 "skipped": s.skipped, "raw": s.raw,
                 "normalized": s.normalized, "deduplicated": s.deduplicated,
                 "quarantined": s.quarantined, "percepts": s.percepts,
                 "failed": s.failed}
                for s in result.streams
            ],
        }

    @app.post("/api/connectors/{connector_id}/pause")
    def api_connector_pause(
        connector_id: str,
        x_twin_client: Optional[str] = Header(default=None),
        x_twin_token: Optional[str] = Header(default=None),
    ):
        _connector_access(x_twin_client, x_twin_token, CAP_OPERATE, connector_id)
        return {"status": pause_connector(ws.store, connector_id).status.value}

    @app.post("/api/connectors/{connector_id}/resume")
    def api_connector_resume(
        connector_id: str,
        x_twin_client: Optional[str] = Header(default=None),
        x_twin_token: Optional[str] = Header(default=None),
    ):
        _connector_access(x_twin_client, x_twin_token, CAP_OPERATE, connector_id)
        try:
            return {"status": resume_connector(ws.store, connector_id).status.value}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/connectors/{connector_id}/revoke")
    def api_connector_revoke(
        connector_id: str,
        x_twin_client: Optional[str] = Header(default=None),
        x_twin_token: Optional[str] = Header(default=None),
    ):
        _connector_access(x_twin_client, x_twin_token, CAP_REVOKE, connector_id)
        try:
            return {"status": revoke_connector(ws.store, _conn_creds(), connector_id).status.value}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.get("/api/connectors/{connector_id}/health")
    def api_connector_health(
        connector_id: str,
        x_twin_client: Optional[str] = Header(default=None),
        x_twin_token: Optional[str] = Header(default=None),
    ):
        _connector_access(x_twin_client, x_twin_token, CAP_READ, connector_id)
        return connector_health(ws.store, connector_id)

    @app.get("/api/connectors/{connector_id}/checkpoints")
    def api_connector_checkpoints(
        connector_id: str,
        x_twin_client: Optional[str] = Header(default=None),
        x_twin_token: Optional[str] = Header(default=None),
    ):
        _connector_access(x_twin_client, x_twin_token, CAP_READ, connector_id)
        return [
            {"stream": c.stream, "cursor": c.cursor, "version": c.version,
             "committed_batch_id": c.committed_batch_id}
            for c in ws.store.list_connector_checkpoints(connector_id)
        ]

    @app.get("/api/connectors/{connector_id}/batches")
    def api_connector_batches(
        connector_id: str,
        x_twin_client: Optional[str] = Header(default=None),
        x_twin_token: Optional[str] = Header(default=None),
    ):
        _connector_access(x_twin_client, x_twin_token, CAP_READ, connector_id)
        return [
            {"id": b.id, "stream": b.stream, "status": b.status.value,
             "raw": b.raw_count, "normalized": b.normalized_count,
             "quarantined": b.quarantined_count, "percepts": b.percept_count,
             "failed": b.failed_count}
            for b in ws.store.list_connector_batches(connector_id)
        ]

    @app.get("/api/connectors/{connector_id}/dead-letters")
    def api_connector_dead_letters(
        connector_id: str,
        x_twin_client: Optional[str] = Header(default=None),
        x_twin_token: Optional[str] = Header(default=None),
    ):
        _connector_access(x_twin_client, x_twin_token, CAP_READ_ERRORS, connector_id)
        return [
            {"id": d.id, "failure_class": d.failure_class.value,
             "status": d.status.value, "attempts": d.attempts,
             "external_type": d.external_type, "external_id": d.external_id,
             "last_error": d.last_error}
            for d in ws.store.list_connector_dead_letters(connector_id)
        ]

    @app.post("/api/connectors/{connector_id}/dead-letters/{item_id}/retry")
    def api_connector_dead_letter_retry(
        connector_id: str, item_id: str,
        x_twin_client: Optional[str] = Header(default=None),
        x_twin_token: Optional[str] = Header(default=None),
    ):
        _connector_access(x_twin_client, x_twin_token, CAP_SYNC, connector_id)
        try:
            dlq = retry_dead_letter(ws.store, _conn_creds(), item_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"id": dlq.id, "status": dlq.status.value,
                "attempts": dlq.attempts, "last_error": dlq.last_error}

    @app.get("/api/connectors/{connector_id}/deletion-events")
    def api_connector_deletion_events(
        connector_id: str,
        x_twin_client: Optional[str] = Header(default=None),
        x_twin_token: Optional[str] = Header(default=None),
    ):
        _connector_access(x_twin_client, x_twin_token, CAP_READ, connector_id)
        return [
            {"id": e.id, "external_type": e.external_type,
             "external_id": e.external_id, "status": e.status.value,
             "prior_record_ids": e.prior_record_ids,
             "affected_percept_ids": e.affected_percept_ids}
            for e in ws.store.list_connector_deletion_events(connector_id)
        ]

    @app.post("/api/connectors/{connector_id}/backfill")
    def api_connector_backfill(
        connector_id: str, preview: bool = True,
        create: bool = False, job_id: Optional[str] = None,
        x_twin_client: Optional[str] = Header(default=None),
        x_twin_token: Optional[str] = Header(default=None),
    ):
        access = _connector_access(x_twin_client, x_twin_token, CAP_BACKFILL,
                                   connector_id)
        try:
            if job_id:
                from ..connectors import run_backfill_partition
                return run_backfill_partition(
                    ws.store, _conn_creds(), job_id)
            if create:
                from ..connectors import create_backfill_job
                job = create_backfill_job(
                    ws.store, _conn_creds(), connector_id)
                return {
                    "job_id": job.id,
                    "status": job.status.value,
                    "total_partitions": (job.progress or {}).get(
                        "total_partitions"),
                    "started": False,
                }
            if not preview:
                # Continuous/first-sync backfill still goes through /sync;
                # partition jobs use create=true / job_id=.
                raise HTTPException(
                    status_code=400,
                    detail="use preview=true, create=true, or job_id=…; "
                           "or set configuration.backfill_since and /sync")
            return backfill_preview(ws.store, _conn_creds(), connector_id,
                                    principal_id=access.principal_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.post("/api/webhooks/github/{connector_id}")
    async def api_github_webhook(connector_id: str, request: Request):
        # Authenticated by HMAC against a dedicated webhook secret — never by
        # twin identity, never by the API token. A valid delivery only nudges
        # the scheduler; the payload never becomes canonical state.
        from ..connectors.github.webhook import WebhookRejected, handle_github_webhook
        body = await request.body()
        try:
            return handle_github_webhook(
                ws.store, _conn_creds(), connector_id,
                event=request.headers.get("X-GitHub-Event"),
                body=body,
                signature=request.headers.get("X-Hub-Signature-256"),
            )
        except WebhookRejected as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.reason)

    @app.post("/api/webhooks/slack/{connector_id}")
    async def api_slack_webhook(connector_id: str, request: Request):
        from ..connectors.slack.webhook import WebhookRejected, handle_slack_webhook
        body = await request.body()
        try:
            return handle_slack_webhook(
                ws.store, _conn_creds(), connector_id,
                body=body,
                timestamp=request.headers.get("X-Slack-Request-Timestamp"),
                signature=request.headers.get("X-Slack-Signature"),
            )
        except WebhookRejected as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.reason)

    @app.get("/api/judgment/conflicts")
    def api_judgment_conflicts(status: str = "open"):
        return [c.model_dump(mode="json") for c in ws.store.list_judgment_conflicts(status=status)]

    @app.get("/api/export")
    def api_export():
        """Full JSON export (vendor-independence guarantee)."""
        memories = ws.store.list_memories(limit=100000)
        judgment_export = load_profile(ws.cfg.judgment_path)
        if hasattr(ws.store, "list_judgment_items"):
            judgment_export = {
                "yaml": judgment_export,
                "items": [i.model_dump(mode="json") for i in ws.store.list_judgment_items(status="active")],
            }
        return JSONResponse({
            "memories": [
                {**_mem_dict(m, ws.store), "evidence": [e.model_dump() for e in ws.store.get_evidence(m.id)]}
                for m in memories
            ],
            "entities": [e.model_dump() for e in ws.store.list_entities()],
            "judgment": judgment_export,
        })

    # -- Twin web UI (static SPA) ------------------------------------------

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def ui_home():
        return HTMLResponse(read_index())

    @app.get("/all", response_class=HTMLResponse)
    def ui_all_redirect():
        return RedirectResponse("/#memories", status_code=302)

    @app.get("/favicon.ico")
    def favicon():
        # Tiny inline avoidance of 404 noise in logs
        return RedirectResponse("/static/app.css", status_code=302)

    @app.post("/review/{memory_id}")
    def ui_review(memory_id: str, action: str = Form(...), domain: str = Form(None),
                  sensitivity: str = Form(None), neighbor_id: str = Form(None)):
        from ..clock import now_iso
        from ..memory.lifecycle import archive_memory, contradict, merge_memories, supersede
        mem = ws.store.get_memory(memory_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        if domain:
            ws.store.update_memory(memory_id, domain=domain)
        if sensitivity:
            ws.store.update_memory(memory_id, sensitivity=sensitivity)
        if action == "approve":
            ws.store.set_status(memory_id, MemoryStatus.confirmed)
            ws.store.update_memory(memory_id, reviewed_at=now_iso())
        elif action == "reject":
            ws.store.set_status(memory_id, MemoryStatus.rejected)
            ws.store.update_memory(memory_id, reviewed_at=now_iso())
        elif action == "defer":
            ws.store.update_memory(memory_id, needs_review=True, review_reason="deferred")
        elif action == "archive":
            archive_memory(ws.store, memory_id)
        elif action == "supersede_hint" and neighbor_id:
            supersede(ws.store, memory_id, neighbor_id)
            ws.store.set_status(memory_id, MemoryStatus.confirmed)
        elif action == "contradict_hint" and neighbor_id:
            contradict(ws.store, memory_id, neighbor_id)
        elif action == "merge_hint" and neighbor_id:
            merge_memories(ws.store, [memory_id, neighbor_id], embedder=ws.embedder)
        elif action != "update":
            raise HTTPException(400, "unknown action")
        return RedirectResponse("/#review", status_code=303)

    return app


def main(home: Optional[str] = None, host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(create_app(home), host=host, port=port)
