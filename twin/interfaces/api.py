"""Local HTTP API + Twin Web Command Center.

Run: twin serve → http://127.0.0.1:8765

JSON API powers MCP, CLI and the static SPA under ``twin/interfaces/web``.
The SPA is a single-route operator cockpit over Sense → Cognize → Inject.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from twin.cognize.services import extract_pending
from twin.inject.context_pack import build_context_pack
from twin.cognize.services.observer import observe
from twin.cognize.services.sessions import (
    complete_session,
    ensure_project,
    observe_session,
    record_feedback,
    start_session,
)
from twin.cognize.services.workspace import workspace_tick
from ..config import ALL_DOMAINS, UNCLASSIFIED_DOMAIN
from twin.cognize.stance_engine.profile import load_profile
from twin.store.models import (
    FeedbackVerdict,
    FindingStatus,
    ClaimStatus,
    TaskProfile,
)
from twin.store.search import search
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


class CognizeRunRequest(BaseModel):
    vault_id: str = "default"
    limit: int = Field(default=50, ge=1, le=200)
    dry_run: bool = False
    until: Optional[str] = None
    percept_ids: list[str] = Field(default_factory=list)
    priority: int = Field(default=100, ge=0, le=10_000)


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
    purpose: str = "context_retrieval"
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
    claim_id: Optional[str] = None
    note: str = Field(default="", max_length=10_000)
    scope: Optional[Literal["session", "pack", "claim"]] = None


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
    claim_ids: list[str] = Field(min_length=2)
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
    related_claim_id: Optional[str] = None
    finding_id: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    parts: Optional[list[dict[str, Any]]] = None
    confirm_cross_scope_merge: bool = False
    domain: Optional[str] = None
    sensitivity: Optional[str] = None


def _claim_dict(mem, store=None) -> dict[str, Any]:
    data = mem.model_dump()
    data["type"] = mem.type.value
    data["sensitivity"] = mem.sensitivity.value
    data["status"] = mem.status.value
    try:
        from twin.cognize.services.quality import claim_altitude
        data["altitude"] = (mem.payload or {}).get("altitude") or claim_altitude(mem)
    except Exception:
        data["altitude"] = (mem.payload or {}).get("altitude") or "ground"
    data["condensed"] = bool(
        (mem.payload or {}).get("condensed")
        or (mem.payload or {}).get("merged_from")
    )
    if store is not None:
        try:
            from twin.store.provenance import claim_source_summary
            src = claim_source_summary(store, mem.id)
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
            other = store.get_claim(mid)
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


class NarrativeCommitRequest(BaseModel):
    account: str
    evidence_ids: list[str]
    vault_id: str = "default"
    domain: str = ""
    actor: str
    preview_token: Optional[str] = None
    interpretation_ids: list[str] = Field(default_factory=list)
    dissent_ids: list[str] = Field(default_factory=list)


class StancePreviewBody(BaseModel):
    edits: Optional[dict[str, Any]] = None


class StanceApproveBody(BaseModel):
    preview_token: str
    confirm_constitutional: bool = False


class ProposalPreviewRequest(BaseModel):
    edits: Optional[dict[str, Any]] = None


class ProposalApproveRequest(BaseModel):
    preview_token: str
    edits: Optional[dict[str, Any]] = None
    confirm_constitutional: bool = False


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
        from twin.store.models import ClaimStatus

        reports = extract_pending(ws.store, ws.cfg, ws.embedder)
        auto_approved: list[str] = []
        if auto_approve:
            for r in reports:
                for mid in r.inserted:
                    mem = ws.store.get_claim(mid)
                    if mem is not None and mem.status.value == "candidate":
                        ws.store.set_status(mid, ClaimStatus.confirmed)
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
    def api_percepts(limit: int = 200):
        rows = ws.store.list_percepts()
        return [p.model_dump(mode="json") for p in rows[: max(1, min(limit, 2000))]]

    @app.get("/api/percepts/{percept_id}")
    def api_percept(percept_id: str):
        p = ws.store.get_percept(percept_id)
        if p is None:
            raise HTTPException(404, "percept not found")
        return p.model_dump(mode="json")

    @app.get("/api/claims")
    def api_memories(
        status: Optional[str] = None,
        domain: Optional[str] = None,
        type: Optional[str] = None,
        needs_review: Optional[bool] = None,
        limit: int = 500,
    ):
        memories = ws.store.list_claims(
            status=status, domain=domain, type_=type,
            needs_review=needs_review, limit=max(1, min(limit, 2000)),
        )
        return [_claim_dict(m, ws.store) for m in memories]

    @app.get("/api/claims/{claim_id}")
    def api_memory(claim_id: str):
        mem = ws.store.get_claim(claim_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        evidence = [e.model_dump() for e in ws.store.get_evidence(claim_id)]
        return {**_claim_dict(mem, ws.store), "evidence": evidence}

    @app.post("/api/claims/{claim_id}/review")
    def api_review(claim_id: str, action: str, domain: Optional[str] = None,
                   sensitivity: Optional[str] = None):
        from ..clock import now_iso
        from twin.store.lifecycle import archive_claim
        mem = ws.store.get_claim(claim_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        if domain:
            ws.store.update_claim(claim_id, domain=domain)
        if sensitivity:
            ws.store.update_claim(claim_id, sensitivity=sensitivity)
        if action == "approve":
            ws.store.set_status(claim_id, ClaimStatus.confirmed)
            ws.store.update_claim(claim_id, reviewed_at=now_iso(), needs_review=False)
        elif action == "reject":
            ws.store.set_status(claim_id, ClaimStatus.rejected)
            ws.store.update_claim(claim_id, reviewed_at=now_iso(), needs_review=False)
        elif action == "defer":
            ws.store.update_claim(claim_id, needs_review=True, review_reason="deferred")
        elif action == "archive":
            try:
                archive_claim(ws.store, claim_id)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        elif action != "update":
            raise HTTPException(
                400, "action must be approve | reject | update | defer | archive",
            )
        return _claim_dict(ws.store.get_claim(claim_id), ws.store)

    # -- memory formation ----------------------------------------------

    @app.get("/api/memory/candidates")
    def api_memory_candidates(state: Optional[str] = None, limit: int = 100):
        from twin.store.formation import list_candidates
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

    @app.post("/api/memory/candidates/{claim_id}/confirm")
    def api_formation_confirm(
        claim_id: str, req: FormationConfirmRequest = FormationConfirmRequest(),
    ):
        from twin.store.formation import confirm_candidate
        try:
            return confirm_candidate(
                ws.store, claim_id, note=req.note,
            ).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/memory/candidates/{claim_id}/reject")
    def api_formation_reject(claim_id: str, req: FormationRejectRequest):
        from twin.store.formation import reject_candidate
        try:
            return reject_candidate(
                ws.store, claim_id, reason=req.reason,
            ).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/memory/candidates/{claim_id}/edit")
    def api_formation_edit(claim_id: str, req: FormationEditRequest):
        from twin.store.formation import edit_candidate
        try:
            return edit_candidate(
                ws.store, claim_id,
                title=req.title, summary=req.summary, domain=req.domain,
            ).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/memory/candidates/{claim_id}/restore")
    def api_formation_restore(claim_id: str):
        from twin.store.formation import restore_candidate
        try:
            return restore_candidate(ws.store, claim_id).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/memory/{claim_id}/explain")
    def api_memory_explain(claim_id: str):
        from twin.store.formation import explain_memory
        try:
            return explain_memory(ws.store, claim_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/memory/{claim_id}/history")
    def api_memory_history(claim_id: str):
        from twin.store.formation import explain_memory
        try:
            return {"claim_id": claim_id, "history": explain_memory(ws.store, claim_id)["history"]}
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/search")
    def api_search(q: str, domain: str = "technical", type: Optional[str] = None,
                   limit: int = 10):
        result = search(ws.store, ws.embedder, q, target_domain=domain,
                        firewall=ws.firewall, type_=type, limit=limit)
        return {
            "hits": [{**_claim_dict(h.claim, ws.store), "score": h.score, "why": h.why} for h in result.hits],
            "blocked": [{"claim_id": b.claim_id, "reason": b.rule} for b in result.blocked],
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

    @app.get("/api/narratives")
    def api_narratives(vault: str = "default", domain: Optional[str] = None):
        if not hasattr(ws.store, "list_narratives"):
            return []
        rows = []
        for nar in ws.store.list_narratives(vault):
            if domain and nar.domain and nar.domain != domain:
                continue
            eps = (
                ws.store.get_epistemic_state(nar.epistemic_state_id)
                if nar.epistemic_state_id
                else None
            )
            rows.append({
                "id": nar.id,
                "account": nar.account,
                "domain": nar.domain,
                "sensitivity": nar.sensitivity,
                "epistemic_status": eps.status.value if eps else None,
                "stale_reason": eps.stale_reason if eps else "",
                "evidence_ids": list(nar.evidence_ids),
            })
        return rows

    @app.get("/api/narratives/{narrative_id}")
    def api_narrative(narrative_id: str):
        nar = ws.store.get_narrative(narrative_id) if hasattr(ws.store, "get_narrative") else None
        if nar is None:
            raise HTTPException(404, "narrative not found")
        eps = (
            ws.store.get_epistemic_state(nar.epistemic_state_id)
            if nar.epistemic_state_id
            else None
        )
        out = nar.model_dump(mode="json")
        out["epistemic"] = eps.model_dump(mode="json") if eps else None

        from twin.cognize.models import (
            EpistemicStatus,
            RelationType,
            derive_confidence,
        )

        evid = list(nar.evidence_ids or [])
        evid_set = set(evid)
        groups: list[list[str]] = []
        support_count = 0
        contradict_count = 0
        relations_out: list[dict[str, Any]] = []
        if hasattr(ws.store, "list_relations"):
            vault = nar.vault_id or "default"
            for rel in ws.store.list_relations(vault):
                dump = rel.model_dump(mode="json")
                touches = (
                    rel.from_id == nar.id
                    or rel.to_id == nar.id
                    or rel.from_id in evid_set
                    or rel.to_id in evid_set
                )
                if touches:
                    relations_out.append(dump)
                rtype = rel.type.value if hasattr(rel.type, "value") else str(rel.type)
                if rtype == RelationType.same_originating_decision.value:
                    groups.append([rel.from_id, rel.to_id])
                if rtype == RelationType.supports.value and (
                    rel.to_id in evid_set or rel.from_id in evid_set or nar.id in (rel.from_id, rel.to_id)
                ):
                    support_count += 1
                if rtype == RelationType.contradicts.value and (
                    rel.to_id in evid_set or rel.from_id in evid_set or nar.id in (rel.from_id, rel.to_id)
                ):
                    contradict_count += 1
        out["relations"] = relations_out

        eps_status = eps.status if eps else EpistemicStatus.fresh
        derived = derive_confidence(
            evidence_ids=evid,
            same_originating_decision_groups=groups,
            support_count=support_count,
            contradict_count=contradict_count,
            epistemic_status=eps_status,
        )
        out["derived_confidence"] = {
            **derived.model_dump(mode="json"),
            "derived": True,
            "supports": support_count,
            "contradicts": contradict_count,
        }

        evidence_rows: list[dict[str, Any]] = []
        if hasattr(ws.store, "list_evidence_anchors"):
            for a in ws.store.list_evidence_anchors(
                nar.vault_id or "default",
                target_kind="narrative",
                target_id=nar.id,
            ):
                evidence_rows.append(a.model_dump(mode="json"))
            for eid in evid:
                if any(r.get("id") == eid for r in evidence_rows):
                    continue
                if hasattr(ws.store, "get_evidence_anchor"):
                    got = ws.store.get_evidence_anchor(eid)
                    if got is not None:
                        evidence_rows.append(got.model_dump(mode="json"))
        out["evidence"] = evidence_rows

        open_refs: list[dict[str, Any]] = []
        if hasattr(ws.store, "list_open_reflections"):
            for ref in ws.store.list_open_reflections(nar.vault_id or "default"):
                ref_domain = (ref.metadata or {}).get("domain") or getattr(ref, "domain", "") or ""
                if nar.domain and ref_domain and ref_domain != nar.domain:
                    continue
                open_refs.append(ref.model_dump(mode="json"))
        out["open_reflections"] = open_refs
        return out

    @app.get("/api/reflections")
    def api_reflections(vault: str = "default", status: str = "open"):
        if status == "open" and hasattr(ws.store, "list_open_reflections"):
            return [r.model_dump(mode="json") for r in ws.store.list_open_reflections(vault)]
        if hasattr(ws.store, "list_reflections"):
            rows = [r.model_dump(mode="json") for r in ws.store.list_reflections(vault)]
            if status and status != "all":
                rows = [r for r in rows if r.get("status") == status]
            return rows
        return []

    @app.get("/api/reflections/{reflection_id}")
    def api_reflection(reflection_id: str):
        if not hasattr(ws.store, "get_reflection"):
            raise HTTPException(404, "reflection not found")
        ref = ws.store.get_reflection(reflection_id)
        if ref is None:
            raise HTTPException(404, "reflection not found")
        return ref.model_dump(mode="json")

    @app.get("/api/situations")
    def api_situations(vault: str = "default"):
        if not hasattr(ws.store, "list_situations"):
            return []
        return [s.model_dump(mode="json") for s in ws.store.list_situations(vault)]

    @app.get("/api/situations/{situation_id}")
    def api_situation(situation_id: str):
        if not hasattr(ws.store, "get_situation"):
            raise HTTPException(404, "situation not found")
        sit = ws.store.get_situation(situation_id)
        if sit is None:
            raise HTTPException(404, "situation not found")
        return sit.model_dump(mode="json")

    @app.get("/api/interpretations")
    def api_interpretations(vault: str = "default", status: Optional[str] = "competing"):
        if not hasattr(ws.store, "list_cognize_interpretations"):
            return []
        st = None if status in (None, "", "all") else status
        return [
            i.model_dump(mode="json")
            for i in ws.store.list_cognize_interpretations(vault, status=st)
        ]

    @app.get("/api/interpretations/{interpretation_id}")
    def api_interpretation(interpretation_id: str):
        if not hasattr(ws.store, "get_cognize_interpretation"):
            raise HTTPException(404, "interpretation not found")
        item = ws.store.get_cognize_interpretation(interpretation_id)
        if item is None:
            raise HTTPException(404, "interpretation not found")
        return item.model_dump(mode="json")

    @app.get("/api/relations")
    def api_relations(
        vault: str = "default",
        type: Optional[str] = None,
        from_id: Optional[str] = None,
        to_id: Optional[str] = None,
    ):
        if not hasattr(ws.store, "list_relations"):
            return []
        rows = ws.store.list_relations(vault, rel_type=type)
        out = [r.model_dump(mode="json") for r in rows]
        if from_id:
            out = [r for r in out if r.get("from_id") == from_id]
        if to_id:
            out = [r for r in out if r.get("to_id") == to_id]
        return out

    @app.get("/api/relations/{relation_id}")
    def api_relation(relation_id: str):
        if not hasattr(ws.store, "get_relation"):
            raise HTTPException(404, "relation not found")
        rel = ws.store.get_relation(relation_id)
        if rel is None:
            raise HTTPException(404, "relation not found")
        return rel.model_dump(mode="json")

    @app.get("/api/evidence")
    def api_evidence(
        vault: str = "default",
        target_kind: Optional[str] = None,
        target_id: Optional[str] = None,
    ):
        if not hasattr(ws.store, "list_evidence_anchors"):
            return []
        return [
            a.model_dump(mode="json")
            for a in ws.store.list_evidence_anchors(
                vault, target_kind=target_kind, target_id=target_id
            )
        ]

    @app.get("/api/evidence/{evidence_id}")
    def api_evidence_one(evidence_id: str):
        if not hasattr(ws.store, "get_evidence_anchor"):
            raise HTTPException(404, "evidence not found")
        a = ws.store.get_evidence_anchor(evidence_id)
        if a is None:
            raise HTTPException(404, "evidence not found")
        return a.model_dump(mode="json")

    @app.get("/api/traces")
    def api_traces(
        vault: str = "default",
        resource_id: Optional[str] = None,
        event_kind: Optional[str] = None,
        limit: int = 200,
    ):
        if not hasattr(ws.store, "list_traces"):
            return []
        return [
            t.model_dump(mode="json")
            for t in ws.store.list_traces(
                vault,
                event_kind=event_kind,
                resource_id=resource_id,
                limit=max(1, min(limit, 2000)),
            )
        ]

    @app.get("/api/traces/{trace_id}")
    def api_trace(trace_id: str):
        if not hasattr(ws.store, "get_trace"):
            raise HTTPException(404, "trace not found")
        t = ws.store.get_trace(trace_id)
        if t is None:
            raise HTTPException(404, "trace not found")
        return t.model_dump(mode="json")

    @app.get("/api/stances")
    def api_stances(vault: str = "default"):
        from twin.cognize.stance import list_stances

        return [s.model_dump(mode="json") for s in list_stances(ws.store, vault_id=vault)]

    @app.get("/api/stances/proposals")
    def api_stance_proposals(status: Optional[str] = "pending"):
        if not hasattr(ws.store, "list_judgment_proposals"):
            return []
        props = ws.store.list_judgment_proposals(status=status, limit=200)
        return [
            {
                "id": p.id,
                "status": p.status.value if hasattr(p.status, "value") else p.status,
                "reason": p.reason,
                "statement": (p.proposed_item or {}).get("statement"),
                "narrative_id": (p.metadata or {}).get("narrative_id"),
            }
            for p in props
        ]

    @app.post("/api/stances/proposals/{proposal_id}/preview")
    def api_stance_proposal_preview(
        proposal_id: str, req: StancePreviewBody = StancePreviewBody(),
    ):
        from twin.cognize.stance_engine.proposals import preview_proposal

        try:
            return preview_proposal(ws.store, proposal_id, edits=req.edits)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/stances/proposals/{proposal_id}/approve")
    def api_stance_proposal_approve(proposal_id: str, req: StanceApproveBody):
        from twin.cognize.stance_engine.proposals import approve_proposal

        if not (req.preview_token or "").strip():
            raise HTTPException(400, "preview_token required")
        try:
            return approve_proposal(
                ws.store,
                proposal_id,
                preview_token=req.preview_token,
                confirm_constitutional=req.confirm_constitutional,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/stances/{stance_id}")
    def api_stance(stance_id: str, vault: str = "default"):
        from twin.cognize.stance import judgment_to_stance

        if not hasattr(ws.store, "get_judgment_item"):
            raise HTTPException(404, "stance not found")
        item = ws.store.get_judgment_item(stance_id)
        if item is None:
            raise HTTPException(404, "stance not found")
        return judgment_to_stance(item, vault_id=vault).model_dump(mode="json")

    @app.get("/api/center/summary")
    def api_center_summary(vault: str = "default"):
        def _count(attr: str, *args, **kwargs) -> int:
            if not hasattr(ws.store, attr):
                return 0
            try:
                rows = getattr(ws.store, attr)(*args, **kwargs)
                return len(list(rows) if rows is not None else [])
            except TypeError:
                try:
                    rows = getattr(ws.store, attr)(*args)
                    return len(list(rows) if rows is not None else [])
                except Exception:
                    return 0
            except Exception:
                return 0

        open_refs = _count("list_open_reflections", vault)
        competing = _count("list_competing_interpretations", vault)
        narratives = _count("list_narratives", vault)
        reflections = _count("list_reflections", vault)
        interpretations = _count("list_cognize_interpretations", vault)
        if interpretations == 0:
            interpretations = _count("list_interpretations", vault)
        situations = _count("list_situations", vault)
        stances = 0
        try:
            from twin.cognize.stance import list_stances

            stances = len(list_stances(ws.store) or [])
        except Exception:
            stances = _count("list_stances", vault)
        evidence = _count("list_evidence_anchors", vault)
        if evidence == 0:
            evidence = _count("list_evidence", vault)
        relations = _count("list_relations", vault)
        traces = 0
        if hasattr(ws.store, "list_traces"):
            try:
                traces = len(ws.store.list_traces(vault, limit=5000) or [])
            except Exception:
                traces = 0
        percepts = _count("list_percepts")

        halt = ""
        if hasattr(ws.store, "last_cognize_run"):
            try:
                run = ws.store.last_cognize_run(vault)
                if run and run.get("halt_reason"):
                    halt = str(run.get("halt_reason"))
            except Exception:
                pass
        queue = {}
        if hasattr(ws.store, "runtime_queue_depth"):
            queue = ws.store.runtime_queue_depth() or {}
        jobs_pending = int(
            queue.get("pending")
            or queue.get("ready")
            or queue.get("queued")
            or 0
        )
        jobs_running = int(queue.get("running") or 0)
        connectors = 0
        if hasattr(ws.store, "list_connector_instances"):
            connectors = len(ws.store.list_connector_instances())

        review_items: list[dict[str, Any]] = []
        if hasattr(ws.store, "list_open_reflections"):
            for r in (ws.store.list_open_reflections(vault) or [])[:8]:
                text = (r.text or "").strip()
                status = r.status.value if hasattr(r.status, "value") else str(r.status or "open")
                review_items.append({
                    "kind": "reflection",
                    "kind_label": "Reflection",
                    "id": r.id,
                    "status": status,
                    "title": (text.split("\n")[0] or text)[:120],
                    "text": text[:280],
                    "created_at": getattr(r, "created_at", "") or "",
                    "meta": {
                        "situations": len(getattr(r, "situation_ids", None) or []),
                        "evidence": len(getattr(r, "evidence_ids", None) or []),
                    },
                    "href": f"#explore/reflection/{r.id}",
                })
        if hasattr(ws.store, "list_competing_interpretations"):
            for i in (ws.store.list_competing_interpretations(vault) or [])[:8]:
                text = (getattr(i, "explanation", "") or "").strip()
                status = i.status.value if hasattr(i.status, "value") else str(i.status or "competing")
                review_items.append({
                    "kind": "interpretation",
                    "kind_label": "Interpretation",
                    "id": i.id,
                    "status": status,
                    "title": (text.split("\n")[0] or text)[:120],
                    "text": text[:280],
                    "created_at": getattr(i, "created_at", "") or "",
                    "meta": {
                        "situations": len(getattr(i, "situation_ids", None) or []),
                        "evidence": len(getattr(i, "evidence_ids", None) or []),
                    },
                    "href": f"#explore/interpretation/{i.id}",
                })

        # Domains that actually have substrate content (empty ones stay hidden).
        from collections import Counter

        from twin.config import UNCLASSIFIED_DOMAIN

        domain_counts: Counter[str] = Counter()

        def _bump_domain(raw: Any) -> None:
            if raw is None:
                return
            value = getattr(raw, "value", raw)
            value = str(value or "").strip()
            if not value or value == UNCLASSIFIED_DOMAIN:
                return
            domain_counts[value] += 1

        if hasattr(ws.store, "list_narratives"):
            for nar in ws.store.list_narratives(vault) or []:
                _bump_domain(getattr(nar, "domain", None))
        if hasattr(ws.store, "list_situations"):
            for sit in ws.store.list_situations(vault) or []:
                _bump_domain(getattr(sit, "domain", None))
        if hasattr(ws.store, "list_claims"):
            try:
                for claim in ws.store.list_claims(limit=2000) or []:
                    _bump_domain(getattr(claim, "domain", None))
            except Exception:
                pass
        try:
            from twin.cognize.stance import list_stances

            for st in list_stances(ws.store) or []:
                _bump_domain(getattr(st, "domain", None))
        except Exception:
            pass

        domains = [
            {
                "id": name,
                "count": int(n),
                "label": name.replace("_", " ").title(),
            }
            for name, n in sorted(domain_counts.items(), key=lambda kv: (-kv[1], kv[0]))
            if n > 0
        ]

        return {
            "vault": vault,
            "open_reflections": open_refs,
            "competing_interpretations": competing,
            "narratives": narratives,
            "reflections": reflections or open_refs,
            "interpretations": interpretations or competing,
            "situations": situations,
            "stances": stances,
            "evidence": evidence,
            "relations": relations,
            "traces": traces,
            "percepts": percepts,
            "cognize_halt": halt,
            "jobs_pending": jobs_pending,
            "jobs_running": jobs_running,
            "connectors": connectors,
            "review_items": review_items[:12],
            "domains": domains,
            "counts": {
                "narratives": narratives,
                "reflections": reflections or open_refs,
                "interpretations": interpretations or competing,
                "situations": situations,
                "stances": stances,
                "evidence": evidence,
                "relations": relations,
                "traces": traces,
                "percepts": percepts,
            },
        }

    def _center_access():
        from twin.privacy.identity import ensure_local_identity, resolve_access
        ensure_local_identity(ws.store)
        return resolve_access(
            ws.store, surface="cli", purpose="context_retrieval", audience="self",
        )

    def _center_connector_row(inst) -> dict[str, Any]:
        from twin.sense.connectors import connector_health
        acc = ws.store.get_source_account(inst.account_id) if hasattr(ws.store, "get_source_account") else None
        health = {}
        try:
            health = connector_health(ws.store, inst.id) or {}
        except Exception as exc:
            health = {"health": "unknown", "detail": str(exc)}
        return {
            "connector_id": inst.id,
            "connector_type": inst.connector_type,
            "status": inst.status.value if hasattr(inst.status, "value") else str(inst.status),
            "account_id": inst.account_id,
            "has_credential": bool(getattr(inst, "credential_ref", None)),
            "source_owner": (
                acc.source_owner.value if acc and hasattr(acc.source_owner, "value")
                else (getattr(acc, "source_owner", None) if acc else None)
            ),
            "vault_id": getattr(acc, "vault_id", None) if acc else None,
            "configuration": getattr(inst, "configuration", None) or {},
            "health": health,
        }

    @app.get("/api/center/connectors")
    def api_center_connectors():
        from twin.sense.connectors import CAP_READ, authorize_connector, visible_connectors
        access = _center_access()
        auth = authorize_connector(ws.store, access, CAP_READ)
        if not auth.allowed:
            raise HTTPException(403, auth.reason)
        return [_center_connector_row(i) for i in visible_connectors(ws.store, access)]

    @app.get("/api/center/connectors/{connector_id}")
    def api_center_connector(connector_id: str):
        from twin.sense.connectors import CAP_READ, authorize_connector
        access = _center_access()
        auth = authorize_connector(ws.store, access, CAP_READ, connector_id=connector_id)
        if not auth.allowed:
            raise HTTPException(403, auth.reason)
        inst = ws.store.get_connector_instance(connector_id)
        if inst is None:
            raise HTTPException(404, "connector not found")
        return _center_connector_row(inst)

    @app.post("/api/center/connectors/{connector_id}/sync")
    def api_center_connector_sync(connector_id: str, stream: Optional[str] = None):
        from twin.sense.connectors import (
            CAP_SYNC, authorize_connector, build_credential_store, sync_connector,
        )
        access = _center_access()
        auth = authorize_connector(ws.store, access, CAP_SYNC, connector_id=connector_id)
        if not auth.allowed:
            raise HTTPException(403, auth.reason)
        try:
            result = sync_connector(
                ws.store, build_credential_store(ws.cfg.home), connector_id,
                streams=[stream] if stream else None,
                emit_percepts=True,
            )
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {
            "connector_id": connector_id,
            "health": result.health.value if hasattr(result.health, "value") else str(result.health),
            "percepts": result.percepts,
            "streams": [
                {
                    "stream": s.stream, "committed": s.committed, "skipped": s.skipped,
                    "raw": s.raw, "normalized": s.normalized, "deduplicated": s.deduplicated,
                    "quarantined": s.quarantined, "percepts": s.percepts, "failed": s.failed,
                }
                for s in (result.streams or [])
            ],
        }

    @app.post("/api/center/connectors/{connector_id}/validate")
    def api_center_connector_validate(connector_id: str):
        from twin.sense.connectors import (
            CAP_READ, authorize_connector, build_credential_store, validate_connector,
        )
        access = _center_access()
        auth = authorize_connector(ws.store, access, CAP_READ, connector_id=connector_id)
        if not auth.allowed:
            raise HTTPException(403, auth.reason)
        try:
            health = validate_connector(
                ws.store, build_credential_store(ws.cfg.home), connector_id,
            )
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {
            "status": health.status.value if hasattr(health.status, "value") else str(health.status),
            "detail": getattr(health, "detail", "") or "",
        }

    @app.post("/api/center/connectors/{connector_id}/pause")
    def api_center_connector_pause(connector_id: str):
        from twin.sense.connectors import CAP_OPERATE, authorize_connector, pause_connector
        access = _center_access()
        auth = authorize_connector(ws.store, access, CAP_OPERATE, connector_id=connector_id)
        if not auth.allowed:
            raise HTTPException(403, auth.reason)
        try:
            pause_connector(ws.store, connector_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"status": "paused"}

    @app.post("/api/center/connectors/{connector_id}/resume")
    def api_center_connector_resume(connector_id: str):
        from twin.sense.connectors import CAP_OPERATE, authorize_connector, resume_connector
        access = _center_access()
        auth = authorize_connector(ws.store, access, CAP_OPERATE, connector_id=connector_id)
        if not auth.allowed:
            raise HTTPException(403, auth.reason)
        try:
            resume_connector(ws.store, connector_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"status": "active"}

    @app.get("/api/cognize/status")
    def api_cognize_status(vault: str = "default"):
        from types import SimpleNamespace

        from twin.interfaces.commands.cognize_cmd import cognize_status

        return cognize_status(ws, SimpleNamespace(vault=vault))

    @app.get("/api/cognize/plan")
    def api_cognize_plan(vault: str = "default", limit: int = 50):
        from twin.cognize.orchestrator import plan_cognize

        return plan_cognize(
            ws.store,
            ws.cfg,
            limit=max(1, min(limit, 200)),
            vault_id=vault,
        )

    @app.post("/api/cognize/run")
    def api_cognize_run(req: CognizeRunRequest):
        from twin.interfaces.runtime.models import JobKind
        from twin.interfaces.runtime.queue import RuntimeQueue

        if req.until:
            from twin.cognize.orchestrator import CognizeStage

            try:
                CognizeStage(req.until)
            except ValueError as exc:
                raise HTTPException(400, f"unknown until stage: {req.until}") from exc

        payload: dict[str, Any] = {
            "vault_id": req.vault_id,
            "limit": req.limit,
            "dry_run": req.dry_run,
        }
        if req.until:
            payload["until"] = req.until
        if req.percept_ids:
            payload["percept_ids"] = list(req.percept_ids)

        job = RuntimeQueue(ws.store).enqueue(
            JobKind.cognize_batch,
            payload=payload,
            vault_id=req.vault_id,
            priority=req.priority,
            idempotency_key="",
        )
        return {"ok": True, "job": job.model_dump(mode="json")}

    @app.post("/api/narratives/commit")
    def api_narrative_commit(req: NarrativeCommitRequest):
        from twin.cognize.commit import CommitError, commit_narrative, preview_commit_token

        if not req.evidence_ids:
            raise HTTPException(400, "evidence_ids required")
        if not (req.actor or "").strip():
            raise HTTPException(400, "actor required")
        if not (req.preview_token or "").strip():
            raise HTTPException(400, "preview_token required — call commit-preview first")
        token = preview_commit_token(
            account=req.account,
            evidence_ids=req.evidence_ids,
            vault_id=req.vault_id,
            interpretation_ids=req.interpretation_ids,
            dissent_interpretation_ids=req.dissent_ids,
            domain=req.domain,
        )
        if req.preview_token != token:
            raise HTTPException(400, "preview_token mismatch — re-preview")
        try:
            nar = commit_narrative(
                ws.store,
                account=req.account,
                vault_id=req.vault_id,
                evidence_ids=req.evidence_ids,
                committed_by=req.actor,
                interpretation_ids=req.interpretation_ids,
                dissent_interpretation_ids=req.dissent_ids,
                domain=req.domain,
                preview_token=req.preview_token,
                require_preview_token=True,
            )
        except CommitError as exc:
            raise HTTPException(400, str(exc))
        return {"ok": True, "narrative_id": nar.id, "preview_token": token}

    @app.post("/api/narratives/commit-preview")
    def api_narrative_commit_preview(req: NarrativeCommitRequest):
        from twin.cognize.commit import preview_commit_token

        token = preview_commit_token(
            account=req.account,
            evidence_ids=req.evidence_ids,
            vault_id=req.vault_id,
            interpretation_ids=req.interpretation_ids,
            dissent_interpretation_ids=req.dissent_ids,
            domain=req.domain,
        )
        return {"preview_token": token, "account": req.account, "evidence_ids": req.evidence_ids}

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
                                      claim_id=req.claim_id, note=req.note,
                                      scope=req.scope)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return _session_dict(session)

    @app.post("/api/sessions/cleanup")
    def api_sessions_cleanup(max_idle_hours: float = 24.0):
        from twin.cognize.services.sessions import abandon_stale_sessions

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

    @app.post("/api/claims/{claim_id}/promote")
    def api_promote(claim_id: str):
        from twin.cognize.stance_engine.profile import promote_claim

        mem = ws.store.get_claim(claim_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        try:
            section = promote_claim(ws.cfg.judgment_path, mem, store=ws.store)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        ws.store.update_claim(claim_id, payload={**mem.payload, "promoted_to_judgment": True})
        return {"claim_id": claim_id, "promoted_to": section}

    @app.post("/api/claims/{claim_id}/supersede/{old_id}")
    def api_supersede(claim_id: str, old_id: str):
        from twin.store.lifecycle import supersede

        try:
            result = supersede(ws.store, claim_id, old_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return result.__dict__

    @app.post("/api/claims/{claim_id}/contradict/{other_id}")
    def api_contradict(claim_id: str, other_id: str):
        from twin.store.lifecycle import contradict

        try:
            result = contradict(ws.store, claim_id, other_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return result.__dict__

    @app.get("/api/metrics")
    def api_metrics():
        from twin.store.metrics import compute_metrics

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
        from twin.cognize.services.consolidation_cycle import run_consolidation_cycle
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
        from twin.interfaces.runtime.models import JobKind
        from twin.interfaces.runtime.queue import RuntimeQueue
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

    @app.get("/api/runtime/jobs")
    def api_runtime_jobs(
        status: Optional[str] = None,
        kind: Optional[str] = None,
        vault_id: Optional[str] = None,
        limit: int = 100,
    ):
        if not hasattr(ws.store, "list_runtime_jobs"):
            return []
        jobs = ws.store.list_runtime_jobs(
            status=status,
            kind=kind,
            vault_id=vault_id,
            limit=max(1, min(limit, 500)),
        )
        return [j.model_dump(mode="json") for j in jobs]

    @app.post("/api/runtime/jobs/{job_id}/retry")
    def api_runtime_retry(job_id: str):
        from twin.interfaces.runtime.queue import RuntimeQueue
        job = RuntimeQueue(ws.store).retry(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        return job.model_dump(mode="json")

    @app.post("/api/runtime/jobs/{job_id}/cancel")
    def api_runtime_cancel(job_id: str):
        from twin.interfaces.runtime.queue import RuntimeQueue
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
        from twin.interfaces.sovereignty.backup import create_backup
        db_path = Path(ws.store.path) if hasattr(ws.store, "path") else None
        manifest = create_backup(ws.store, req.dest, copy_sqlite_db=db_path)
        return manifest.model_dump(mode="json")

    @app.post("/api/backup/validate")
    def api_backup_validate(req: BackupValidateRequest):
        from twin.interfaces.sovereignty.backup import validate_backup
        return validate_backup(req.bundle)

    @app.post("/api/restore/validate")
    def api_restore_validate(req: BackupValidateRequest):
        from twin.interfaces.sovereignty.backup import validate_backup
        return validate_backup(req.bundle)

    @app.post("/api/restore")
    def api_restore(req: BackupRestoreRequest):
        from twin.interfaces.sovereignty.backup import restore_sqlite_backup
        return restore_sqlite_backup(req.bundle, req.target_db)

    @app.get("/api/health/cognition")
    def api_health_cognition():
        from twin.interfaces.sovereignty.integrity import run_integrity_checks
        return run_integrity_checks(ws.store)

    @app.get("/api/health/doctor")
    @app.get("/api/doctor")
    def api_doctor():
        """Item-by-item ``twin doctor`` snapshot for the Web Center health card."""
        from twin.interfaces.ops import FAIL, OK, WARN, doctor

        checks = doctor(ws.cfg)
        rows = [
            {
                "name": c.name,
                "status": c.status,
                "detail": c.detail or "",
            }
            for c in checks
        ]
        n_ok = sum(1 for c in checks if c.status == OK)
        n_warn = sum(1 for c in checks if c.status == WARN)
        n_fail = sum(1 for c in checks if c.status == FAIL)
        return {
            "checks_ok": n_ok,
            "checks_total": len(checks),
            "counts": {"ok": n_ok, "warn": n_warn, "fail": n_fail},
            "checks": rows,
            "extractor": ws.cfg.extractor,
            "embedder": ws.cfg.embedder,
            "llm": getattr(ws.cfg, "normalized_llm_provider", ""),
            "model": getattr(ws.cfg, "resolved_llm_model", "") or "",
            "home": str(ws.cfg.home),
        }

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
        from twin.cognize.services.session_lifecycle import append_session_delta
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
        from twin.cognize.services.attention import evaluate_attention
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
        from twin.cognize.services.attention import feedback_attention
        em = feedback_attention(ws.store, emission_id, verdict=req.verdict)
        if em is None:
            raise HTTPException(404, "emission not found")
        return em.to_dict()

    @app.post("/api/sessions/{session_id}/checkpoint")
    def api_session_checkpoint(session_id: str, req: SessionCheckpointRequest):
        from twin.cognize.services.session_lifecycle import checkpoint_session
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
        from twin.cognize.services.session_lifecycle import close_session_structured
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
        from twin.cognize.services.session_lifecycle import reopen_session
        try:
            session = reopen_session(ws.store, session_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return session.model_dump(mode="json")

    @app.post("/api/sessions/{session_id}/pause")
    def api_session_pause(session_id: str):
        from twin.cognize.services.session_lifecycle import pause_session
        try:
            return pause_session(ws.store, session_id).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/sessions/{session_id}/resume")
    def api_session_resume(session_id: str):
        from twin.cognize.services.session_lifecycle import resume_session
        try:
            return resume_session(ws.store, session_id).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/sessions/{session_id}/closure")
    def api_session_closure(session_id: str):
        from twin.cognize.services.session_lifecycle import get_session_closure
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
        from twin.cognize.services.quality import review_queue
        project_id = _resolve_project_id(project) if project else None
        queue = review_queue(
            ws.store, project_id=project_id, domain=domain, type_=type,
            sensitivity=sensitivity, min_priority=min_priority,
            conflicts_only=conflicts, limit=limit,
        )
        return [_claim_dict(m, ws.store) for m in queue]

    class BatchCreateRequest(BaseModel):
        name: str = Field(min_length=1, max_length=200)
        query: dict[str, Any] = Field(default_factory=dict)
        claim_ids: list[str] = Field(default_factory=list)

    class BatchApplyRequest(BaseModel):
        action: str
        claim_ids: Optional[list[str]] = None
        force: bool = False
        preview_token: Optional[str] = None

    def _finding_dict(finding, store) -> dict[str, Any]:
        data = finding.model_dump(mode="json")
        rid = finding.related_claim_id
        if rid:
            related = store.get_claim(rid)
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

    def _close_finding(store, claim_id: str, finding_id: Optional[str], *,
                       status: FindingStatus = FindingStatus.resolved,
                       operation_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        if not finding_id or not hasattr(store, "get_findings"):
            return None
        from ..clock import now_iso
        findings = store.get_findings(claim_id, unresolved_only=False)
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
        from twin.store.batches import create_batch
        batch = create_batch(ws.store, req.name, query=req.query, claim_ids=req.claim_ids or None)
        return batch.model_dump()

    @app.get("/api/review/batches/{batch_id}")
    def api_get_batch(batch_id: str):
        from twin.store.batches import get_batch
        batch = get_batch(ws.store, batch_id)
        if batch is None:
            raise HTTPException(404, "batch not found")
        return batch.model_dump()

    @app.post("/api/review/batches/{batch_id}/apply")
    def api_apply_batch(batch_id: str, req: BatchApplyRequest):
        from twin.store.automation import batch_apply, batch_preview
        from twin.store.batches import get_batch
        batch = get_batch(ws.store, batch_id)
        if batch is None:
            raise HTTPException(404, "batch not found")
        ids = req.claim_ids or batch.claim_ids
        preview = batch_preview(ws.store, ids, req.action)
        if req.force is False and preview.get("requires_individual_review"):
            return {**preview, "preview_only": True}
        return batch_apply(
            ws.store, ids, req.action,
            force=req.force, preview_token=req.preview_token,
        )

    @app.get("/api/claims/{claim_id}/neighbors")
    def api_neighbors(claim_id: str):
        from twin.cognize.services.quality import discover_neighbors
        mem = ws.store.get_claim(claim_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        neighbors = discover_neighbors(ws.store, ws.embedder, mem)
        return [
            {**_claim_dict(n, ws.store), "similarity": sim, "reason": reason}
            for n, sim, reason in neighbors
        ]

    @app.get("/api/claims/{claim_id}/quality")
    def api_quality(claim_id: str, refresh: bool = False):
        from twin.cognize.services.quality import analyze_claim
        mem = ws.store.get_claim(claim_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        # Prefer stored findings unless caller asks to re-analyze.
        if not refresh and hasattr(ws.store, "get_findings"):
            stored = ws.store.get_findings(claim_id, unresolved_only=True)
            if stored:
                from twin.cognize.services.quality import claim_altitude
                return {
                    "claim_id": claim_id,
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
                    "altitude": claim_altitude(mem),
                    "from_store": True,
                }
        try:
            report = analyze_claim(ws.store, ws.embedder, claim_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        data = report.model_dump(mode="json")
        data["issues"] = [_finding_dict(f, ws.store) for f in report.issues]
        data["from_store"] = False
        return data

    @app.get("/api/claims/{claim_id}/findings")
    def api_findings(claim_id: str, unresolved_only: bool = True):
        mem = ws.store.get_claim(claim_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        if not hasattr(ws.store, "get_findings"):
            return []
        return [
            _finding_dict(f, ws.store)
            for f in ws.store.get_findings(claim_id, unresolved_only=unresolved_only)
        ]

    @app.post("/api/claims/{claim_id}/findings/{finding_id}/dismiss")
    def api_dismiss_finding(claim_id: str, finding_id: str):
        closed = _close_finding(
            ws.store, claim_id, finding_id, status=FindingStatus.dismissed,
        )
        if closed is None:
            raise HTTPException(404, "finding not found")
        return closed

    @app.post("/api/claims/{claim_id}/resolve")
    def api_resolve(claim_id: str, req: ResolveRequest):
        from ..clock import now_iso
        from twin.store.lifecycle import (
            archive_claim,
            contradict,
            merge_claims,
            split_claim,
            supersede,
        )

        mem = ws.store.get_claim(claim_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        if req.domain:
            ws.store.update_claim(claim_id, domain=req.domain)
        if req.sensitivity:
            ws.store.update_claim(claim_id, sensitivity=req.sensitivity)

        action = (req.action or "").strip().lower()
        related_id = req.related_claim_id
        result: dict[str, Any] = {"action": action, "claim_id": claim_id}
        op_id: Optional[str] = None
        remove_ids: list[str] = []
        finding_status = FindingStatus.resolved

        try:
            if action == "dismiss":
                finding_status = FindingStatus.dismissed
            elif action == "merge":
                if not related_id:
                    raise ValueError("related_claim_id required for merge")
                merged = merge_claims(
                    ws.store, [claim_id, related_id],
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
                remove_ids = [claim_id, related_id]
            elif action == "contradict":
                if not related_id:
                    raise ValueError("related_claim_id required for contradict")
                out = contradict(ws.store, claim_id, related_id)
                op_id = out.operation_id
                result["operation_id"] = op_id
            elif action == "supersede":
                if not related_id:
                    raise ValueError("related_claim_id required for supersede")
                out = supersede(ws.store, claim_id, related_id)
                # Keep the newer claim as confirmed — matches legacy review form.
                ws.store.set_status(claim_id, ClaimStatus.confirmed)
                ws.store.update_claim(
                    claim_id, reviewed_at=now_iso(), needs_review=False,
                )
                op_id = out.operation_id
                result["operation_id"] = op_id
                remove_ids = [claim_id, related_id]
            elif action == "supersede_by":
                if not related_id:
                    raise ValueError("related_claim_id required for supersede_by")
                out = supersede(ws.store, related_id, claim_id)
                related_mem = ws.store.get_claim(related_id)
                if related_mem is not None and related_mem.status == ClaimStatus.candidate:
                    ws.store.set_status(related_id, ClaimStatus.confirmed)
                    ws.store.update_claim(
                        related_id, reviewed_at=now_iso(), needs_review=False,
                    )
                op_id = out.operation_id
                result["operation_id"] = op_id
                remove_ids = [claim_id, related_id]
            elif action == "split":
                parts = req.parts or []
                if len(parts) < 2:
                    raise ValueError("split requires at least two parts")
                out = split_claim(ws.store, claim_id, parts, embedder=ws.embedder)
                op_id = out.operation_id
                result.update({
                    "children": out.extras.get("children"),
                    "operation_id": op_id,
                })
                remove_ids = [claim_id]
            elif action == "archive":
                out = archive_claim(ws.store, claim_id)
                op_id = out.operation_id
                result["operation_id"] = op_id
                remove_ids = [claim_id]
            elif action == "request_evidence":
                ws.store.update_claim(
                    claim_id, needs_review=True,
                    review_reason="more evidence requested",
                    quality_flags=list(set((mem.quality_flags or []) + ["weak_evidence"])),
                )
            elif action == "defer":
                ws.store.update_claim(
                    claim_id, needs_review=True, review_reason="deferred",
                )
            elif action == "confirm":
                ws.store.set_status(claim_id, ClaimStatus.confirmed)
                ws.store.update_claim(
                    claim_id, reviewed_at=now_iso(), needs_review=False,
                )
                remove_ids = [claim_id]
            elif action == "reject":
                ws.store.set_status(claim_id, ClaimStatus.rejected)
                ws.store.update_claim(
                    claim_id, reviewed_at=now_iso(), needs_review=False,
                )
                remove_ids = [claim_id]
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
            ws.store, claim_id, req.finding_id,
            status=finding_status, operation_id=op_id,
        )
        if closed is not None:
            result["finding"] = closed
        result["removed_from_queue"] = remove_ids
        result["claim"] = _claim_dict(ws.store.get_claim(claim_id), ws.store) \
            if ws.store.get_claim(claim_id) else None
        return result

    @app.get("/api/claims/{claim_id}/provenance")
    def api_provenance(claim_id: str):
        from twin.store.provenance import claim_provenance
        try:
            return claim_provenance(ws.store, claim_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/claims/merge")
    def api_merge(req: MergeRequest):
        from twin.store.lifecycle import merge_claims
        from twin.store.models import CanonicalClaim
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
            result = merge_claims(ws.store, req.claim_ids, **merge_kwargs)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"action": result.action, "merged_id": result.extras.get("merged_id"),
                "operation_id": result.operation_id, **result.extras}

    @app.post("/api/claims/{claim_id}/split")
    def api_split(claim_id: str, req: SplitRequest):
        from twin.store.lifecycle import split_claim
        try:
            result = split_claim(ws.store, claim_id, req.parts, embedder=ws.embedder)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"action": result.action, "children": result.extras.get("children"),
                "operation_id": result.operation_id}

    @app.post("/api/claims/{claim_id}/archive")
    def api_archive(claim_id: str):
        from twin.store.lifecycle import archive_claim
        try:
            result = archive_claim(ws.store, claim_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"action": result.action, "operation_id": result.operation_id}

    @app.post("/api/claims/{claim_id}/request-evidence")
    def api_request_evidence(claim_id: str):
        mem = ws.store.get_claim(claim_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        ws.store.update_claim(
            claim_id, needs_review=True,
            review_reason="more evidence requested",
            quality_flags=list(set(mem.quality_flags + ["weak_evidence"])),
        )
        return _claim_dict(ws.store.get_claim(claim_id), ws.store)

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
        from twin.store.retention import delete_artifact
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
        from twin.cognize.stance_engine.versions import restore_version
        try:
            ver = restore_version(ws.store, version_id, actor="api")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return ver.model_dump(mode="json")

    @app.get("/api/judgment/snapshots/{snapshot_id}/explain")
    def api_judgment_snapshot_explain(snapshot_id: str):
        from twin.cognize.stance_engine.explain import explain_judgment_snapshot
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
        from twin.cognize.stance_engine.proposals import propose_from_pattern
        return [p.model_dump(mode="json") for p in propose_from_pattern(ws.store, domain=domain)]

    @app.post("/api/judgment/proposals/{proposal_id}/preview")
    def api_preview_proposal(proposal_id: str, req: ProposalPreviewRequest = ProposalPreviewRequest()):
        from twin.cognize.stance_engine.proposals import preview_proposal
        try:
            return preview_proposal(ws.store, proposal_id, edits=req.edits)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/judgment/proposals/{proposal_id}/approve")
    def api_approve_proposal(proposal_id: str, req: ProposalApproveRequest):
        from twin.cognize.stance_engine.proposals import approve_proposal
        try:
            return approve_proposal(
                ws.store, proposal_id, preview_token=req.preview_token,
                edits=req.edits, confirm_constitutional=req.confirm_constitutional,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/judgment/proposals/{proposal_id}/reject")
    def api_reject_proposal(proposal_id: str, reason: str = ""):
        from twin.cognize.stance_engine.proposals import reject_proposal
        try:
            return reject_proposal(ws.store, proposal_id, reason=reason).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/judgment/import")
    def api_judgment_import(req: JudgmentImportRequest):
        from twin.cognize.stance_engine.yaml_io import apply_yaml_import, preview_yaml_import
        preview = preview_yaml_import(ws.cfg.judgment_path)
        if not req.apply:
            return {"preview": preview, "count": len(preview)}
        return apply_yaml_import(ws.store, ws.cfg.judgment_path, classifications=preview)

    @app.post("/api/judgment/applicable")
    def api_judgment_applicable(req: JudgmentApplicableRequest):
        from twin.cognize.stance_engine.application import applicable_pack
        return applicable_pack(
            ws.store, domain=req.domain, persona=req.persona,
            task_profile=req.task_profile, project_id=req.project_id,
            audience=req.audience, client=req.client,
            project_stage=req.project_stage, query=req.query,
        )

    @app.post("/api/judgment/simulate")
    def api_judgment_simulate(req: JudgmentSimulateRequest):
        from twin.cognize.stance_engine.simulate import simulate
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

    from twin.sense.connectors import build_credential_store as _bcs
    from twin.sense.connectors import (
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
                from twin.sense.connectors import run_backfill_partition
                return run_backfill_partition(
                    ws.store, _conn_creds(), job_id)
            if create:
                from twin.sense.connectors import create_backfill_job
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
        from twin.sense.connectors.github.webhook import WebhookRejected, handle_github_webhook
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
        from twin.sense.connectors.slack.webhook import WebhookRejected, handle_slack_webhook
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
        memories = ws.store.list_claims(limit=100000)
        judgment_export = load_profile(ws.cfg.judgment_path)
        if hasattr(ws.store, "list_judgment_items"):
            judgment_export = {
                "yaml": judgment_export,
                "items": [i.model_dump(mode="json") for i in ws.store.list_judgment_items(status="active")],
            }
        return JSONResponse({
            "claims": [
                {**_claim_dict(m, ws.store), "evidence": [e.model_dump() for e in ws.store.get_evidence(m.id)]}
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

    @app.post("/review/{claim_id}")
    def ui_review(claim_id: str, action: str = Form(...), domain: str = Form(None),
                  sensitivity: str = Form(None), neighbor_id: str = Form(None)):
        from ..clock import now_iso
        from twin.store.lifecycle import archive_claim, contradict, merge_claims, supersede
        mem = ws.store.get_claim(claim_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        if domain:
            ws.store.update_claim(claim_id, domain=domain)
        if sensitivity:
            ws.store.update_claim(claim_id, sensitivity=sensitivity)
        if action == "approve":
            ws.store.set_status(claim_id, ClaimStatus.confirmed)
            ws.store.update_claim(claim_id, reviewed_at=now_iso())
        elif action == "reject":
            ws.store.set_status(claim_id, ClaimStatus.rejected)
            ws.store.update_claim(claim_id, reviewed_at=now_iso())
        elif action == "defer":
            ws.store.update_claim(claim_id, needs_review=True, review_reason="deferred")
        elif action == "archive":
            archive_claim(ws.store, claim_id)
        elif action == "supersede_hint" and neighbor_id:
            supersede(ws.store, claim_id, neighbor_id)
            ws.store.set_status(claim_id, ClaimStatus.confirmed)
        elif action == "contradict_hint" and neighbor_id:
            contradict(ws.store, claim_id, neighbor_id)
        elif action == "merge_hint" and neighbor_id:
            merge_claims(ws.store, [claim_id, neighbor_id], embedder=ws.embedder)
        elif action != "update":
            raise HTTPException(400, "unknown action")
        return RedirectResponse("/#review", status_code=303)

    return app


def main(home: Optional[str] = None, host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(create_app(home), host=host, port=port)
