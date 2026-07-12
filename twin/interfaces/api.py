"""Local HTTP API + minimal review UI.

Run:  twin serve   →  http://127.0.0.1:8765

The UI is intentionally tiny (server-rendered HTML, no build step): review
candidate memories, approve/reject, fix domain/sensitivity, inspect evidence,
export JSON. Everything else happens through the JSON API or MCP.
"""

from __future__ import annotations

import html
from typing import Any, Literal, Optional

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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
from ..config import ALL_DOMAINS, UNCLASSIFIED_DOMAIN
from ..judgment.profile import load_profile
from ..memory.models import FeedbackVerdict, MemoryStatus, TaskProfile
from ..memory.search import search
from ..workspace import Workspace

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


class PackRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20_000)
    target_domain: str = "technical"
    max_tokens: int = Field(default=1200, ge=100, le=16_000)
    include_judgment: bool = True
    include_candidates: bool = False  # packs are confirmed-only by default
    task_profile: TaskProfile = TaskProfile.general
    project: Optional[str] = None  # project name, alias or id

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


def _mem_dict(mem) -> dict[str, Any]:
    data = mem.model_dump()
    data["type"] = mem.type.value
    data["sensitivity"] = mem.sensitivity.value
    data["status"] = mem.status.value
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
    def api_extract():
        reports = extract_pending(ws.store, ws.cfg, ws.embedder)
        return [
            {
                "percept_id": r.percept_id, "extractor": r.extractor,
                "inserted": r.inserted, "duplicates": r.duplicates,
                "flagged_for_review": r.flagged_for_review,
                "pii_findings": r.pii_findings,
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
    ):
        memories = ws.store.list_memories(status=status, domain=domain, type_=type,
                                          needs_review=needs_review)
        return [_mem_dict(m) for m in memories]

    @app.get("/api/memories/{memory_id}")
    def api_memory(memory_id: str):
        mem = ws.store.get_memory(memory_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        evidence = [e.model_dump() for e in ws.store.get_evidence(memory_id)]
        return {**_mem_dict(mem), "evidence": evidence}

    @app.post("/api/memories/{memory_id}/review")
    def api_review(memory_id: str, action: str, domain: Optional[str] = None,
                   sensitivity: Optional[str] = None):
        mem = ws.store.get_memory(memory_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        if domain:
            ws.store.update_memory(memory_id, domain=domain)
        if sensitivity:
            ws.store.update_memory(memory_id, sensitivity=sensitivity)
        if action == "approve":
            ws.store.set_status(memory_id, MemoryStatus.confirmed)
        elif action == "reject":
            ws.store.set_status(memory_id, MemoryStatus.rejected)
        elif action != "update":
            raise HTTPException(400, "action must be approve | reject | update")
        return _mem_dict(ws.store.get_memory(memory_id))

    @app.get("/api/search")
    def api_search(q: str, domain: str = "technical", type: Optional[str] = None,
                   limit: int = 10):
        result = search(ws.store, ws.embedder, q, target_domain=domain,
                        firewall=ws.firewall, type_=type, limit=limit)
        return {
            "hits": [{**_mem_dict(h.memory), "score": h.score, "why": h.why} for h in result.hits],
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
        pack = build_context_pack(ws.store, ws.cfg, ws.embedder, req.query,
                                  target_domain=req.target_domain,
                                  max_tokens=req.max_tokens,
                                  include_judgment=req.include_judgment,
                                  include_candidates=req.include_candidates,
                                  task_profile=req.task_profile.value,
                                  project_id=_resolve_project_id(req.project),
                                  firewall=ws.firewall)
        return pack.__dict__

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

    # -- v0.3 review / quality / consolidation --------------------------------

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
        return [_mem_dict(m) for m in queue]

    class BatchCreateRequest(BaseModel):
        name: str = Field(min_length=1, max_length=200)
        query: dict[str, Any] = Field(default_factory=dict)
        memory_ids: list[str] = Field(default_factory=list)

    class BatchApplyRequest(BaseModel):
        action: str
        memory_ids: Optional[list[str]] = None
        force: bool = False
        preview_token: Optional[str] = None

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
            {**_mem_dict(n), "similarity": sim, "reason": reason}
            for n, sim, reason in neighbors
        ]

    @app.get("/api/memories/{memory_id}/quality")
    def api_quality(memory_id: str):
        from ..cognition.quality import analyze_memory
        try:
            report = analyze_memory(ws.store, ws.embedder, memory_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return report.model_dump(mode="json")

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
        return _mem_dict(ws.store.get_memory(memory_id))

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

    @app.get("/api/judgment/proposals")
    def api_judgment_proposals(status: str = "pending"):
        return [p.model_dump(mode="json") for p in ws.store.list_judgment_proposals(status=status)]

    @app.post("/api/judgment/proposals/generate")
    def api_generate_proposals(domain: str = "technical"):
        from ..judgment.proposals import propose_from_pattern
        return [p.model_dump(mode="json") for p in propose_from_pattern(ws.store, domain=domain)]

    @app.post("/api/judgment/proposals/{proposal_id}/preview")
    def api_preview_proposal(proposal_id: str):
        from ..judgment.proposals import preview_proposal
        try:
            return preview_proposal(ws.store, proposal_id)
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
            task_profile=req.task_profile, project_id=req.project_id, query=req.query,
        )

    @app.post("/api/judgment/simulate")
    def api_judgment_simulate(req: JudgmentSimulateRequest):
        from ..judgment.simulate import simulate
        return simulate(
            ws.store, req.query, domain=req.domain, task_profile=req.task_profile,
            project_id=req.project_id, options=req.options,
        )

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
                {**_mem_dict(m), "evidence": [e.model_dump() for e in ws.store.get_evidence(m.id)]}
                for m in memories
            ],
            "entities": [e.model_dump() for e in ws.store.list_entities()],
            "judgment": judgment_export,
        })

    # -- Review Workbench UI (v0.3) ----------------------------------------

    _PAGE = """<!doctype html><html><head><meta charset="utf-8">
    <title>twin — review workbench</title>
    <style>
      :root {{ --bg:#0f1419; --panel:#1a2332; --line:#2d3a4d; --text:#e7ecf3;
               --muted:#8b9bb4; --ok:#3d9a6a; --no:#c44b4b; --warn:#c9a227; --accent:#5b8def; }}
      * {{ box-sizing: border-box; }}
      body {{ font-family: "IBM Plex Sans", "Segoe UI", sans-serif; margin: 0;
              background: linear-gradient(160deg,#0f1419 0%,#15202b 50%,#1a1f2e 100%);
              color: var(--text); min-height: 100vh; }}
      header {{ padding: 1rem 1.5rem; border-bottom: 1px solid var(--line);
                display:flex; gap:1rem; align-items:baseline; flex-wrap:wrap; }}
      header h1 {{ font-family: "IBM Plex Serif", Georgia, serif; font-size: 1.35rem;
                   margin:0; letter-spacing:.02em; }}
      nav a {{ color: var(--muted); text-decoration:none; margin-right:1rem; font-size:.9rem; }}
      nav a:hover {{ color: var(--accent); }}
      .wrap {{ max-width: 1100px; margin: 0 auto; padding: 1.25rem; }}
      .filters {{ display:flex; flex-wrap:wrap; gap:.5rem; margin-bottom:1rem; }}
      .filters select, .filters input {{ background:var(--panel); color:var(--text);
        border:1px solid var(--line); border-radius:4px; padding:.35rem .5rem; }}
      .pair {{ display:grid; grid-template-columns:1fr 1fr; gap:1rem; margin-bottom:1rem; }}
      @media (max-width:800px) {{ .pair {{ grid-template-columns:1fr; }} }}
      .card {{ background:var(--panel); border:1px solid var(--line); border-radius:6px;
               padding:1rem; }}
      .card h3 {{ margin:0 0 .4rem; font-size:1rem; }}
      .meta {{ color:var(--muted); font-size:.78rem; margin-bottom:.5rem; line-height:1.4; }}
      .reason {{ color:var(--warn); font-size:.82rem; margin-bottom:.4rem; }}
      .flags span {{ display:inline-block; background:#243044; color:var(--muted);
                     font-size:.7rem; padding:.1rem .4rem; margin:.1rem; border-radius:3px; }}
      blockquote {{ border-left:2px solid var(--line); margin:.4rem 0; padding:.2rem .6rem;
                    color:var(--muted); font-size:.85rem; }}
      .actions {{ display:flex; flex-wrap:wrap; gap:.4rem; margin-top:.75rem; }}
      button, .actions a.btn {{ padding:.4rem .75rem; border-radius:4px; border:1px solid var(--line);
        cursor:pointer; background:#243044; color:var(--text); font-size:.82rem; text-decoration:none; }}
      button.ok {{ background:var(--ok); border-color:var(--ok); color:#fff; }}
      button.no {{ background:var(--no); border-color:var(--no); color:#fff; }}
      .keys {{ color:var(--muted); font-size:.75rem; margin-top:1rem; }}
      .prio {{ color:var(--accent); font-weight:600; }}
    </style></head><body>
    <header>
      <h1>twin</h1>
      <nav><a href="/">workbench</a><a href="/all">all</a><a href="/api/export">export</a>
           <a href="/api/metrics">metrics</a></nav>
    </header>
    <div class="wrap">{body}</div>
    <script>
    document.addEventListener('keydown', (e) => {{
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'TEXTAREA') return;
      const form = document.querySelector('.work-item form');
      if (!form) return;
      const map = {{a:'approve',r:'reject',e:'update',d:'defer',m:'merge_hint',s:'supersede_hint',c:'contradict_hint'}};
      if (map[e.key]) {{
        const btn = form.querySelector('[value="'+map[e.key]+'"]');
        if (btn) {{ e.preventDefault(); btn.click(); }}
      }}
      if (e.key === 'n') {{ const n = document.querySelector('a.next'); if (n) n.click(); }}
      if (e.key === 'p') {{ const p = document.querySelector('a.prev'); if (p) p.click(); }}
    }});
    </script>
    </body></html>"""

    def _render_side(mem, evidence, label: str) -> str:
        quotes = "".join(f"<blockquote>{html.escape(e.quote[:240])}</blockquote>" for e in evidence[:2])
        flags = "".join(f"<span>{html.escape(f)}</span>" for f in mem.quality_flags[:6])
        return f"""
        <div class="card">
          <div class="meta">{html.escape(label)}</div>
          <h3>{html.escape(mem.title)}</h3>
          <div class="meta">{mem.type.value} · {mem.domain} · {mem.sensitivity.value}
            · conf {mem.confidence:.2f} · prio <span class="prio">{mem.review_priority:.2f}</span>
            · {html.escape((mem.created_at or '')[:16])}
            · entities: {html.escape(", ".join(mem.entities) or "—")}</div>
          <div class="flags">{flags}</div>
          <p>{html.escape(mem.summary)}</p>
          {quotes}
        </div>"""

    def _render_work_item(mem, neighbor, evidence, n_evidence, idx: int, total: int) -> str:
        domain_opts = "".join(
            f'<option value="{d}" {"selected" if d == mem.domain else ""}>{d}</option>'
            for d in ALL_DOMAINS
        )
        sens_opts = "".join(
            f'<option value="{s}" {"selected" if s == mem.sensitivity.value else ""}>{s}</option>'
            for s in ["public", "internal", "private", "restricted"]
        )
        reason = (
            f'<div class="reason">⚠ {html.escape(mem.review_reason or "")}</div>'
            if mem.needs_review else ""
        )
        pair = _render_side(mem, evidence, "Candidate")
        if neighbor:
            pair = f'<div class="pair">{pair}{_render_side(neighbor, n_evidence, "Neighbor")}</div>'
        else:
            pair = f'<div class="pair">{pair}<div class="card"><div class="meta">No close neighbor</div></div></div>'
        prev_href = f"/?i={idx-1}" if idx > 0 else "#"
        next_href = f"/?i={idx+1}" if idx + 1 < total else "#"
        return f"""
        <div class="work-item">
          <div class="meta">item {idx+1} / {total}
            <a class="prev" href="{prev_href}">prev</a> ·
            <a class="next" href="{next_href}">next</a></div>
          {reason}
          {pair}
          <form method="post" action="/review/{mem.id}" class="actions">
            domain <select name="domain">{domain_opts}</select>
            sensitivity <select name="sensitivity">{sens_opts}</select>
            <input type="hidden" name="neighbor_id" value="{neighbor.id if neighbor else ''}">
            <button class="ok" name="action" value="approve">A approve</button>
            <button class="no" name="action" value="reject">R reject</button>
            <button name="action" value="update">E edit/save</button>
            <button name="action" value="defer">D defer</button>
            <button name="action" value="supersede_hint">S supersede neighbor</button>
            <button name="action" value="contradict_hint">C contradict</button>
            <button name="action" value="merge_hint">M merge</button>
            <button name="action" value="archive">archive</button>
          </form>
          <p class="keys">Keyboard: A approve · R reject · E edit · M merge · S supersede · C contradict · D defer · N/P next/prev</p>
        </div>"""

    @app.get("/", response_class=HTMLResponse)
    def ui_review_queue(i: int = 0, conflicts: bool = False):
        from ..cognition.quality import discover_neighbors, review_queue
        pending = review_queue(ws.store, conflicts_only=conflicts, limit=200)
        if not pending:
            return _PAGE.format(body="<p>Nothing to review.</p>")
        i = max(0, min(i, len(pending) - 1))
        mem = pending[i]
        neighbors = discover_neighbors(ws.store, ws.embedder, mem, limit=1)
        neighbor = neighbors[0][0] if neighbors else None
        body = f"<h2>{len(pending)} in priority queue</h2>" + _render_work_item(
            mem, neighbor,
            ws.store.get_evidence(mem.id),
            ws.store.get_evidence(neighbor.id) if neighbor else [],
            i, len(pending),
        )
        return _PAGE.format(body=body)

    @app.get("/all", response_class=HTMLResponse)
    def ui_all():
        memories = ws.store.list_memories(limit=500)
        cards = []
        for mem in memories:
            cards.append(f"""
            <div class="card" style="margin-bottom:.6rem">
              <h3>{html.escape(mem.title)}</h3>
              <div class="meta">{mem.status.value} · {mem.type.value} · prio {mem.review_priority:.2f}</div>
              <p>{html.escape(mem.summary[:280])}</p>
            </div>""")
        body = "".join(cards) or "<p>No memories yet.</p>"
        return _PAGE.format(body=body)

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
        return RedirectResponse("/", status_code=303)

    return app


def main(home: Optional[str] = None, host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(create_app(home), host=host, port=port)
