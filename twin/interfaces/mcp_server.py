"""MCP server (stdio) — exposes the memory layer to Cursor, Claude Desktop,
Claude Code and any other MCP client.

Run: twin mcp (or: python -m twin.interfaces.mcp_server)

Identity is process-env only (``TWIN_MCP_CLIENT`` + ``TWIN_MCP_CLIENT_TOKEN``).
Tool calls cannot supply or override credentials — provision via
``twin setup mcp <client>``.

Client config example:
 {
 "mcpServers": {
 "twin": {
 "command": "twin",
 "args": ["mcp"],
 "env": {
 "TWIN_MCP_CLIENT": "cursor",
 "TWIN_MCP_CLIENT_TOKEN": "…"
 }
 }
 }
 }
"""

from __future__ import annotations

import json
from typing import Any, Optional

from twin.inject.context_pack import build_context_pack
from twin.cognize.services.sessions import (
    complete_session,
    observe_session,
    record_feedback,
    start_session,
)
from twin.cognize.stance_engine.profile import load_profile
from twin.store.search import search
from ..workspace import Workspace
from .mcp_auth import MCP_CLIENT_ENV, mcp_process_identity, resolve_mcp_access


def _claim_to_dict(mem) -> dict[str, Any]:
    return {
        "id": mem.id, "type": mem.type.value, "title": mem.title,
        "summary": mem.summary, "domain": mem.domain, "persona": mem.persona,
        "sensitivity": mem.sensitivity.value, "confidence": mem.confidence,
        "status": mem.status.value, "valid_from": mem.valid_from,
        "valid_until": mem.valid_until, "entities": mem.entities,
        "percept_ids": mem.percept_ids, "payload": mem.payload,
    }


def create_server(home: Optional[str] = None):
    from mcp.server.fastmcp import FastMCP

    ws = Workspace(home)
    mcp = FastMCP(
        "twin",
        instructions=(
            "Personal cognitive layer for the user. Call inject_context_pack "
            "at the start of technical tasks to load relevant Narratives and "
            "Stance without re-asking. Results are filtered by the Domain "
            "Firewall. Identity is configured by the host via process env "
            f"({MCP_CLIENT_ENV} / TWIN_MCP_CLIENT_TOKEN) — never pass credentials "
            "as tool arguments."
        ),
    )

    def _mcp_client_label() -> str:
        client, _ = mcp_process_identity()
        return client or "mcp"

    @mcp.tool()
    def claim_search(
        query: str,
        domain: str = "technical",
        type: Optional[str] = None,
        limit: int = 10,
    ) -> str:
        """Hybrid search (text + semantic + graph) over store claims.
        `domain` is the domain of YOUR current task (work, technical,
        personal_preferences, assistant_preferences) and controls privacy
        filtering. Optional `type` filters by memory type (decision, task,
        preference, belief, fact, event, procedure, constraint)."""
        result = search(ws.store, ws.embedder, query, target_domain=domain,
                        firewall=ws.firewall, type_=type, limit=limit)
        return json.dumps({
            "hits": [
                {**_claim_to_dict(h.claim), "score": h.score, "why": h.why}
                for h in result.hits
            ],
            "blocked": [{"claim_id": b.claim_id, "reason": b.rule} for b in result.blocked],
        }, ensure_ascii=False)

    @mcp.tool()
    def claim_get(claim_id: str) -> str:
        """Fetch one claim by id, including its evidence quotes and percepts."""
        mem = ws.store.get_claim(claim_id)
        if mem is None:
            return json.dumps({"error": "not found"})
        evidence = [{"quote": e.quote, "percept_id": e.percept_id}
                    for e in ws.store.get_evidence(claim_id)]
        return json.dumps({**_claim_to_dict(mem), "evidence": evidence}, ensure_ascii=False)

    @mcp.tool()
    def claim_related(entity: str) -> str:
        """Entities and claims connected to a given entity name in the
        knowledge graph (projects, people, systems, tools)."""
        ent = ws.store.get_entity_by_name(entity)
        if ent is None:
            return json.dumps({"error": f"entity '{entity}' not found"})
        memories = ws.store.claims_for_entity(ent.id)
        relations = ws.store.relations_for(ent.id)
        return json.dumps({
            "entity": {"id": ent.id, "name": ent.name, "type": ent.entity_type},
            "claims": [_claim_to_dict(m) for m in memories[:20]],
            "relations": [
                {"subject": r.subject_id, "predicate": r.predicate, "object": r.object_id}
                for r in relations[:50]
            ],
        }, ensure_ascii=False)

    @mcp.tool()
    def claim_project_context(project_name: str) -> str:
        """Everything known about a project: claims linked to it plus the
        most recent decisions."""
        ent = ws.store.get_entity_by_name(project_name)
        memories = ws.store.claims_for_entity(ent.id) if ent else []
        result = search(ws.store, ws.embedder, project_name, target_domain="technical",
                        firewall=ws.firewall, limit=10)
        by_id = {m.id: m for m in memories}
        for h in result.hits:
            by_id.setdefault(h.claim.id, h.claim)
        items = sorted(by_id.values(), key=lambda m: m.created_at, reverse=True)
        return json.dumps({
            "project": project_name,
            "claims": [_claim_to_dict(m) for m in items[:25]],
        }, ensure_ascii=False)

    @mcp.tool()
    def claim_recent_decisions(project_name: Optional[str] = None, limit: int = 10) -> str:
        """Most recent technical/work decisions, optionally scoped to a project."""
        decisions = ws.store.list_claims(type_="decision", limit=100)
        if project_name:
            needle = project_name.lower()
            decisions = [
                d for d in decisions
                if needle in d.title.lower() or needle in d.summary.lower()
                or any(needle == e.lower() for e in d.entities)
            ]
        return json.dumps(
            [_claim_to_dict(d) for d in decisions[:limit]], ensure_ascii=False
        )

    @mcp.tool()
    def claim_user_preferences(context: str = "") -> str:
        """The user's stable preferences (technical + communication),
        optionally ranked by relevance to `context`."""
        prefs = ws.store.list_claims(type_="preference", limit=100)
        if context:
            ranked = search(ws.store, ws.embedder, context, target_domain="assistant_preferences",
                            firewall=ws.firewall, type_="preference", limit=20)
            ids_ranked = [h.claim.id for h in ranked.hits]
            prefs.sort(key=lambda p: ids_ranked.index(p.id) if p.id in ids_ranked else 999)
        return json.dumps([_claim_to_dict(p) for p in prefs[:20]], ensure_ascii=False)

    def _resolve_project_id(project: Optional[str]) -> Optional[str]:
        if not project:
            return None
        found = ws.store.get_project(project) or ws.store.find_project(project)
        return found.id if found else None

    @mcp.tool()
    def inject_context_pack(
        query: str,
        target_domain: str = "technical",
        max_tokens: int = 1200,
        include_judgment: bool = True,
        include_candidates: bool = False,
        task_profile: str = "general",
        project: Optional[str] = None,
        persona: str = "individual",
        purpose: str = "context_retrieval",
        audience: str = "self",
        mode: str = "compact",
        session_id: Optional[str] = None,
    ) -> str:
        """Privacy-filtered context pack with EpistemicState, Narratives,
        open Reflections, and derived confidence/independence."""
        access = resolve_mcp_access(
            ws.store,
            persona=persona, purpose=purpose, audience=audience,
            project_id=_resolve_project_id(project),
            requested_domains=[target_domain],
        )
        if mode not in ("compact", "explainable", "references_only"):
            mode = "compact"
        pack = build_context_pack(
            ws.store, ws.cfg, ws.embedder, query,
            target_domain=target_domain, max_tokens=max_tokens,
            include_judgment=include_judgment,
            include_candidates=include_candidates,
            task_profile=task_profile,
            project_id=_resolve_project_id(project),
            firewall=ws.firewall,
            access=access,
            session_id=session_id,
            mode=mode,  # type: ignore[arg-type]
        )
        return json.dumps({
            "tool": "inject_context_pack",
            "context_pack": pack.context_pack,
            "sources": pack.sources,
            "confidence": pack.confidence,
            "blocked": pack.blocked,
            "blocked_count": pack.blocked_count,
            "task_profile": pack.task_profile,
            "project_id": pack.project_id,
            "privacy_decision_id": pack.privacy_decision_id,
            "privacy_meta": pack.privacy_meta,
            "evidence_included": pack.evidence_included,
            "evidence_omitted_due_to_budget": pack.evidence_omitted_due_to_budget,
            "mode": pack.mode,
            "active": pack.active,
            "provenance_summary": pack.provenance_summary,
            "token_budget": pack.token_budget,
            "explanation": pack.explanation,
            "narratives": pack.narratives,
            "open_reflections": pack.open_reflections,
            "epistemic": pack.epistemic,
            "derived_confidence": pack.derived_confidence,
            "applicable_stance": pack.applicable_stance,
        }, ensure_ascii=False)

    # -- Cognitive session lifecycle --------------------------------------

    def _session_dict(session) -> dict[str, Any]:
        data = session.model_dump()
        data["status"] = session.status.value
        return data

    @mcp.tool()
    def session_start(
        query: str,
        cwd: Optional[str] = None,
        domain: Optional[str] = None,
        project: Optional[str] = None,
        task_profile: Optional[str] = None,
        max_tokens: int = 1200,
    ) -> str:
        """MAIN TOOL — call this when starting a unit of work. twin identifies
        the project, domain and task profile (pass `cwd` so the working
        directory helps identify the project), builds a task-aware context
        pack and opens a cognitive session that tracks what was supplied.
        Returns {session_id, context_pack, sources, blocked, reading}.
        Prepend the context_pack to your work; when the work is done call
        session_complete with a summary so twin learns from what happened.

        If the response has needs_domain_confirmation=true, twin could not
        classify the task's domain and supplied NO context (default-deny):
        ask the user which domain applies (work, technical,
        personal_preferences, assistant_preferences) and start again with
        `domain` set explicitly. An unknown explicit `project` is an error —
        it is never silently replaced by an inferred one.

        Host identity is process env only (twin setup mcp)."""
        client = _mcp_client_label()
        _, token = mcp_process_identity()
        try:
            started = start_session(
                ws.store, ws.cfg, ws.embedder, query,
                client=client, cwd=cwd, domain=domain, project=project,
                task_profile=task_profile, max_tokens=max_tokens,
                api_token=token,
            )
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps({
            "session_id": started.session.id,
            "project_id": started.session.project_id,
            "domain": started.session.domain,
            "task_profile": started.session.task_profile,
            "needs_domain_confirmation": started.needs_domain_confirmation,
            "context_pack": started.pack.context_pack,
            "sources": started.pack.sources,
            "blocked": started.pack.blocked,
            "evidence_included": started.pack.evidence_included,
            "reading": {
                "confidences": started.reading_confidences,
                "observer_mode": started.observer_mode,
                "fallback": started.observer_fallback,
            },
        }, ensure_ascii=False)

    @mcp.tool()
    def session_observe(
        session_id: str,
        kind: str,
        ref: Optional[str] = None,
        note: Optional[str] = None,
        percept_id: Optional[str] = None,
    ) -> str:
        """Record an artifact produced or changed during the session — a
        file, commit, PR, document or decision made along the way.
        `kind` is free-form (file, commit, pr, doc, decision, note);
        `ref` points at the artifact (path, sha, url); `note` says what
        happened; `percept_id` links an artifact twin already ingested via
        a sensor (its note is then never duplicated as text). Call it as
        you work so session_complete has material."""
        artifact: dict[str, Any] = {"kind": kind}
        if ref:
            artifact["ref"] = ref
        if note:
            artifact["note"] = note
        if percept_id:
            artifact["percept_id"] = percept_id
        try:
            session = observe_session(ws.store, session_id, artifact)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps({
            "session_id": session.id,
            "artifacts": len(session.artifacts),
        }, ensure_ascii=False)

    @mcp.tool()
    def append_session_delta(
        session_id: str,
        text: str,
        sequence: Optional[int] = None,
        external_session_id: str = "",
    ) -> str:
        """Append an ordered session delta (enqueues attention evaluate job)."""
        from twin.cognize.services.session_lifecycle import append_session_delta as _append
        try:
            ev = _append(
                ws.store, session_id, text=text, sequence=sequence,
                external_session_id=external_session_id,
                client=_mcp_client_label(),
            )
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps(ev.model_dump(mode="json"), ensure_ascii=False)

    @mcp.tool()
    def get_active_session(session_id: str) -> str:
        """Fetch a cognitive session by id."""
        session = ws.store.get_session(session_id)
        if session is None:
            return json.dumps({"error": "not found"})
        return json.dumps(_session_dict(session), ensure_ascii=False, default=str)

    @mcp.tool()
    def get_attention(session_id: str, evaluate: bool = False) -> str:
        """List or re-evaluate attention outcomes for a session (prefer silence)."""
        from twin.cognize.services.attention import evaluate_attention
        if evaluate:
            outcomes = evaluate_attention(
                ws.store, ws.cfg, ws.embedder, session_id,
            )
            return json.dumps({
                "session_id": session_id,
                "outcomes": [o.to_dict() for o in outcomes],
            }, ensure_ascii=False)
        rows = ws.store.list_attention_emissions(session_id, limit=50)
        return json.dumps({
            "session_id": session_id,
            "outcomes": [o.to_dict() for o in rows],
        }, ensure_ascii=False)

    @mcp.tool()
    def provide_feedback(
        emission_id: str = "",
        session_id: str = "",
        verdict: str = "useful",
        claim_id: Optional[str] = None,
        note: str = "",
    ) -> str:
        """Feedback on attention emission or session usefulness."""
        if emission_id:
            from twin.cognize.services.attention import feedback_attention
            em = feedback_attention(ws.store, emission_id, verdict=verdict)
            if em is None:
                return json.dumps({"error": "emission not found"})
            return json.dumps(em.to_dict(), ensure_ascii=False)
        if session_id:
            try:
                session = record_feedback(
                    ws.store, session_id, verdict,
                    claim_id=claim_id, note=note,
                )
            except ValueError as exc:
                return json.dumps({"error": str(exc)})
            return json.dumps(_session_dict(session), ensure_ascii=False, default=str)
        return json.dumps({"error": "emission_id or session_id required"})

    @mcp.tool()
    def narrative_list(vault: str = "default", domain: str = "") -> str:
        """List committed Narratives with EpistemicState status (not memory blobs)."""
        if not hasattr(ws.store, "list_narratives"):
            return json.dumps({"narratives": []})
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
                "epistemic_status": eps.status.value if eps else None,
                "stale_reason": eps.stale_reason if eps else "",
                "sensitivity": nar.sensitivity,
            })
        return json.dumps({"count": len(rows), "narratives": rows}, ensure_ascii=False)

    @mcp.tool()
    def narrative_show(narrative_id: str) -> str:
        """Show one Narrative + EpistemicState."""
        nar = ws.store.get_narrative(narrative_id) if hasattr(ws.store, "get_narrative") else None
        if nar is None:
            return json.dumps({"error": "narrative not found"})
        eps = (
            ws.store.get_epistemic_state(nar.epistemic_state_id)
            if nar.epistemic_state_id
            else None
        )
        return json.dumps({
            "narrative": nar.model_dump(mode="json"),
            "epistemic": eps.model_dump(mode="json") if eps else None,
        }, ensure_ascii=False, default=str)

    @mcp.tool()
    def stance_list() -> str:
        """List active Stances (approved Judgment items)."""
        from twin.cognize.stance import list_stances

        rows = [s.model_dump(mode="json") for s in list_stances(ws.store)]
        return json.dumps({"count": len(rows), "stances": rows}, ensure_ascii=False)

    @mcp.tool()
    def stance_proposals(status: str = "pending") -> str:
        """List Stance/Judgment proposals (pending until human approve)."""
        if not hasattr(ws.store, "list_judgment_proposals"):
            return json.dumps({"proposals": []})
        rows = [
            {
                "id": p.id,
                "status": p.status.value,
                "reason": p.reason,
                "statement": (p.proposed_item or {}).get("statement"),
                "narrative_id": (p.metadata or {}).get("narrative_id"),
            }
            for p in ws.store.list_judgment_proposals(status=status, limit=100)
        ]
        return json.dumps({"count": len(rows), "proposals": rows}, ensure_ascii=False)

    @mcp.tool()
    def capabilities() -> str:
        """Negotiable MCP capability list for Twin cognitive core."""
        return json.dumps({
            "schema_version": "2.1",
            "tools": [
                "inject_context_pack",
                "narrative_list", "narrative_show", "stance_list", "stance_proposals",
                "stance_applicable", "stance_simulate", "stance_profile",
                "stance_proposal_preview", "stance_proposal_approve",
                "get_active_session", "get_attention", "append_session_delta",
                "session_start", "session_complete", "provide_feedback",
                "workspace_tick", "consolidate_cycle", "health", "capabilities",
            ],
            "pack_contract": "v2",
            "inject_observer": False,
            "attention": True,
            "runtime_jobs": True,
            "formation": True,
            "personas": True,
        }, ensure_ascii=False)

    @mcp.tool()
    def health() -> str:
        """Runtime + store health snapshot."""
        queue = {}
        if hasattr(ws.store, "runtime_queue_depth"):
            queue = ws.store.runtime_queue_depth()
        client, token = mcp_process_identity()
        return json.dumps({
            "ok": True,
            "queue": queue,
            "extractor": ws.cfg.extractor,
            "embedder": ws.cfg.embedder,
            "identity": {
                "client": client,
                "token_configured": bool(token),
                "source": "env",
            },
        }, ensure_ascii=False)

    @mcp.tool()
    def session_complete(
        session_id: str,
        summary: str = "",
        abandoned: bool = False,
        summary_origin: str = "assistant",
        user_confirmed: bool = False,
    ) -> str:
        """Close the session. `summary` should state what was decided, built
        or changed — it becomes a percept and goes through extraction, so
        decisions made during the work turn into candidate memories (reviewed
        by the user later). Set abandoned=true when the work was dropped.

        `summary_origin` declares who wrote the summary (assistant | user |
        client | derived) and sets how much it is trusted; only pass
        user_confirmed=true when the human explicitly approved the text.
        The response carries consolidation_status: "failed" means the
        summary was saved but extraction failed — calling session_complete
        again retries it without duplicating anything."""
        try:
            session = complete_session(ws.store, ws.cfg, ws.embedder, session_id,
                                       summary=summary, abandoned=abandoned,
                                       summary_origin=summary_origin,
                                       user_confirmed=user_confirmed)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps({
            "session_id": session.id,
            "status": session.status.value,
            "consolidation_status": session.consolidation_status.value,
            "consolidation_error": session.consolidation_error,
            "created_claim_ids": session.created_claim_ids,
        }, ensure_ascii=False)

    @mcp.tool()
    def session_feedback(
        session_id: str,
        verdict: str,
        claim_id: Optional[str] = None,
        note: str = "",
        scope: Optional[str] = None,
    ) -> str:
        """Record how useful the supplied context actually was. `verdict` is
        one of: useful, partially_useful, irrelevant, incorrect,
        missing_context (the user had to re-explain something twin should
        have known), privacy_overblock, privacy_underblock. `scope` says what
        the verdict is about (session | pack | memory; defaults to memory
        when claim_id is given, session otherwise). A claim_id must be one
        of the memories this session supplied or created. This feeds twin's
        product metrics."""
        try:
            session = record_feedback(ws.store, session_id, verdict,
                                      claim_id=claim_id, note=note, scope=scope)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps({
            "session_id": session.id,
            "feedback_count": len(session.feedback),
        }, ensure_ascii=False)

    @mcp.tool()
    def native_bindings(host_type: Optional[str] = None, limit: int = 50) -> str:
        """List HostSessionBindings from the native adapter.

        Proves MCP and native observation share the same store: bindings
        point at CognitiveSession ids that session_* tools already use.
        Credentials and host payloads are never returned."""
        if not hasattr(ws.store, "list_host_session_bindings"):
            return json.dumps({"error": "host bindings unsupported"})
        rows = ws.store.list_host_session_bindings(host_type=host_type, limit=limit)
        return json.dumps([
            {
                "id": b.id,
                "host_type": b.host_type,
                "external_session_id": b.external_session_id,
                "cognitive_session_id": b.cognitive_session_id,
                "project_id": b.project_id,
                "started_at": b.started_at,
                "ended_at": b.ended_at,
            }
            for b in rows
        ], ensure_ascii=False)

    @mcp.tool()
    def native_session_status(external_session_id: str, host_type: str = "claude-code") -> str:
        """Look up the CognitiveSession bound to a host conversation.

        Same Projects / Memories / Sessions as MCP — no parallel native store."""
        if not hasattr(ws.store, "find_host_session_binding"):
            return json.dumps({"error": "host bindings unsupported"})
        binding = None
        if hasattr(ws.store, "find_active_host_session_binding"):
            binding = ws.store.find_active_host_session_binding(
                host_type=host_type, external_session_id=external_session_id,
            )
        if binding is None:
            binding = ws.store.find_host_session_binding(
                host_type=host_type, external_session_id=external_session_id,
            )
        if binding is None:
            return json.dumps({"error": "not found"})
        session = ws.store.get_session(binding.cognitive_session_id)
        return json.dumps({
            "binding": {
                "id": binding.id,
                "host_type": binding.host_type,
                "external_session_id": binding.external_session_id,
                "occurrence": binding.occurrence,
                "cognitive_session_id": binding.cognitive_session_id,
                "domain": binding.domain,
                "project_id": binding.project_id,
                "ended_at": binding.ended_at,
            },
            "session": _session_dict(session) if session else None,
        }, ensure_ascii=False, default=str)

    @mcp.tool()
    def workspace_tick(
        current_text: str,
        target_domain: Optional[str] = None,
        session_id: str = "",
        interpret: bool = False,
        input_mode: str = "snapshot",
        sequence: Optional[int] = None,
        idempotency_key: Optional[str] = None,
    ) -> str:
        """Workspace evaluation tick : reading → recall → optional
        delta interpretation (candidates only). Idempotent via session+sequence
        or idempotency_key. Never confirms Memory or Judgment."""
        from twin.cognize.services.workspace import workspace_tick as _tick
        if input_mode not in ("snapshot", "delta"):
            return json.dumps({"error": "input_mode must be snapshot or delta"})
        result = _tick(
            ws.store, ws.cfg, ws.embedder, current_text,
            session_id=session_id or "",
            target_domain=target_domain,
            interpret=interpret,
            input_mode=input_mode,  # type: ignore[arg-type]
            sequence=sequence,
            idempotency_key=idempotency_key,
            firewall=ws.firewall,
        )
        return json.dumps(result.to_dict(), ensure_ascii=False, default=str)

    @mcp.tool()
    def consolidate_cycle(kind: str = "daily", apply: bool = False, limit: int = 200) -> str:
        """Run a daily or weekly consolidation cycle (quality, safe automation,
        temporal belief/goal refresh; weekly may propose judgment). Default
        dry-run; set apply=true to write. Never confirms Memory/Judgment."""
        from twin.cognize.services.consolidation_cycle import run_consolidation_cycle
        if kind not in ("daily", "weekly"):
            return json.dumps({"error": "kind must be daily or weekly"})
        result = run_consolidation_cycle(
            ws.store, ws.cfg, ws.embedder,
            kind=kind, dry_run=not apply, analyze_limit=limit,
        )
        return json.dumps(result.to_dict(), ensure_ascii=False, default=str)

    # -- quality / review (read tools + gated mutations) -----------------

    @mcp.tool()
    def claim_quality(claim_id: str) -> str:
        """Analyze a claim for duplicates, conflicts, merge/split suggestions
        and review priority."""
        from twin.cognize.services.quality import analyze_claim
        report = analyze_claim(ws.store, ws.embedder, claim_id)
        return json.dumps(report.model_dump(mode="json"), ensure_ascii=False)

    @mcp.tool()
    def claim_neighbors(claim_id: str) -> str:
        """Find semantically/entity-related neighbor claims for side-by-side review."""
        from twin.cognize.services.quality import discover_neighbors
        mem = ws.store.get_claim(claim_id)
        if mem is None:
            return json.dumps({"error": "not found"})
        neighbors = discover_neighbors(ws.store, ws.embedder, mem)
        return json.dumps([
            {"claim": _claim_to_dict(n), "similarity": sim, "reason": reason}
            for n, sim, reason in neighbors
        ], ensure_ascii=False)

    @mcp.tool()
    def claim_provenance(claim_id: str) -> str:
        """Navigable lineage: memory → evidence → percept → artifact."""
        from twin.store.provenance import claim_provenance as prov
        return json.dumps(prov(ws.store, claim_id), ensure_ascii=False, default=str)

    @mcp.tool()
    def review_queue(limit: int = 20, conflicts_only: bool = False) -> str:
        """Priority-ordered review queue (risk × impact, not FIFO)."""
        from twin.cognize.services.quality import review_queue as rq
        queue = rq(ws.store, conflicts_only=conflicts_only, limit=limit)
        return json.dumps([_claim_to_dict(m) for m in queue], ensure_ascii=False)

    @mcp.tool()
    def review_batch_get(batch_id: str) -> str:
        """Get a review batch and its progress."""
        from twin.store.batches import get_batch
        batch = get_batch(ws.store, batch_id)
        if batch is None:
            return json.dumps({"error": "not found"})
        return json.dumps(batch.model_dump(), ensure_ascii=False)

    @mcp.tool()
    def review_suggest_action(claim_id: str) -> str:
        """Suggest a curation action without applying it (safe for external clients)."""
        from twin.cognize.services.quality import analyze_claim
        report = analyze_claim(ws.store, ws.embedder, claim_id, persist=False)
        return json.dumps({
            "claim_id": claim_id,
            "suggested_action": report.suggested_action.value,
            "requires_human_review": report.requires_human_review,
            "quality_flags": report.quality_flags,
            "review_priority": report.review_priority,
            "issues": [i.model_dump(mode="json") for i in report.issues],
        }, ensure_ascii=False)

    @mcp.tool()
    def claim_confirm(claim_id: str, confirm: bool = False) -> str:
        """Confirm a candidate claim. Requires confirm=true."""
        if not confirm:
            return json.dumps({"error": "pass confirm=true to apply"})
        from twin.store.models import ClaimStatus
        ws.store.set_status(claim_id, ClaimStatus.confirmed)
        return json.dumps(_claim_to_dict(ws.store.get_claim(claim_id)), ensure_ascii=False)

    @mcp.tool()
    def claim_reject(claim_id: str, confirm: bool = False) -> str:
        """Reject a candidate claim. Requires confirm=true."""
        if not confirm:
            return json.dumps({"error": "pass confirm=true to apply"})
        from twin.store.models import ClaimStatus
        ws.store.set_status(claim_id, ClaimStatus.rejected)
        return json.dumps(_claim_to_dict(ws.store.get_claim(claim_id)), ensure_ascii=False)

    @mcp.tool()
    def claim_archive(claim_id: str, confirm: bool = False) -> str:
        """Archive a claim (removed from default retrieval). Requires confirm=true."""
        if not confirm:
            return json.dumps({"error": "pass confirm=true to apply"})
        from twin.store.lifecycle import archive_claim
        result = archive_claim(ws.store, claim_id)
        return json.dumps({"action": result.action, "operation_id": result.operation_id})

    @mcp.tool()
    def claim_merge(claim_ids: list[str], confirm: bool = False,
                     title: Optional[str] = None, summary: Optional[str] = None,
                     confirm_cross_scope_merge: bool = False,
                     output_type: Optional[str] = None,
                     output_domain: Optional[str] = None,
                     output_persona: Optional[str] = None,
                     output_project_id: Optional[str] = None) -> str:
        """Merge claims into one. Requires confirm=true.

        Mixed type/domain/persona/project requires the matching output_* field;
        confirm_cross_scope_merge only authorizes the attempt.
        """
        if not confirm:
            return json.dumps({"error": "pass confirm=true to apply", "preview": claim_ids})
        from twin.store.lifecycle import merge_claims
        kwargs: dict = {
            "title": title, "summary": summary, "embedder": ws.embedder,
            "confirm_cross_scope_merge": confirm_cross_scope_merge,
            "output_type": output_type, "output_domain": output_domain,
            "output_persona": output_persona,
        }
        if output_project_id is not None:
            kwargs["output_project_id"] = output_project_id
        try:
            result = merge_claims(ws.store, claim_ids, **kwargs)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps({"merged_id": result.extras.get("merged_id"),
                           "operation_id": result.operation_id})

    @mcp.tool()
    def claim_split(claim_id: str, parts: list[str], confirm: bool = False) -> str:
        """Split a compound claim. parts are titles/summaries. Requires confirm=true."""
        if not confirm:
            return json.dumps({"error": "pass confirm=true to apply", "parts": parts})
        from twin.store.lifecycle import split_memory
        result = split_memory(
            ws.store, claim_id,
            [{"title": p, "summary": p} for p in parts],
            embedder=ws.embedder,
        )
        return json.dumps({"children": result.extras.get("children"),
                           "operation_id": result.operation_id})

    # -- Stance -------------------------------------------------------------

    @mcp.tool()
    def stance_applicable(domain: str = "technical", task_profile: str = "general",
                            project: Optional[str] = None, query: str = "") -> str:
        """Return only Stance items applicable to this domain/task — not the full profile."""
        from twin.cognize.stance_engine.application import applicable_pack
        pack = applicable_pack(
            ws.store, domain=domain, task_profile=task_profile,
            project_id=_resolve_project_id(project), query=query,
        )
        return json.dumps(pack, ensure_ascii=False)

    @mcp.tool()
    def stance_simulate(query: str, domain: str = "technical",
                          task_profile: str = "architecture",
                          project: Optional[str] = None) -> str:
        """Explain how active Stance would influence a recommendation (no side effects)."""
        from twin.cognize.stance_engine.simulate import simulate
        return json.dumps(simulate(
            ws.store, query, domain=domain, task_profile=task_profile,
            project_id=_resolve_project_id(project),
        ), ensure_ascii=False, default=str)

    @mcp.tool()
    def stance_proposal_preview(proposal_id: str) -> str:
        """Preview a Stance proposal and obtain a state-aware preview_token for approval."""
        from twin.cognize.stance_engine.proposals import preview_proposal
        try:
            return json.dumps(preview_proposal(ws.store, proposal_id), ensure_ascii=False)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

    @mcp.tool()
    def stance_proposal_approve(proposal_id: str, preview_token: str,
                                  confirm: bool = False,
                                  confirm_constitutional: bool = False) -> str:
        """Approve a Stance proposal (creates a new version). Requires confirm=true."""
        if not confirm:
            return json.dumps({"error": "pass confirm=true to apply"})
        from twin.cognize.stance_engine.proposals import approve_proposal
        try:
            return json.dumps(approve_proposal(
                ws.store, proposal_id, preview_token=preview_token,
                confirm_constitutional=confirm_constitutional,
            ), ensure_ascii=False)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

    @mcp.tool()
    def stance_proposal_reject(proposal_id: str, confirm: bool = False,
                                 reason: str = "") -> str:
        if not confirm:
            return json.dumps({"error": "pass confirm=true to apply"})
        from twin.cognize.stance_engine.proposals import reject_proposal
        try:
            p = reject_proposal(ws.store, proposal_id, reason=reason)
            return json.dumps(p.model_dump(mode="json"), ensure_ascii=False)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

    @mcp.tool()
    def stance_conflicts(status: str = "open") -> str:
        return json.dumps(
            [c.model_dump(mode="json") for c in ws.store.list_judgment_conflicts(status=status)],
            ensure_ascii=False,
        )

    @mcp.tool()
    def stance_version() -> str:
        v = ws.store.get_active_judgment_version()
        return json.dumps(v.model_dump(mode="json") if v else None, ensure_ascii=False)

    @mcp.tool()
    def stance_profile() -> str:
        """Active Stance items (DB) plus YAML bootstrap. Prefer stance_applicable
        for scoped injection into a task."""
        payload = dict(load_profile(ws.cfg.judgment_path))
        if hasattr(ws.store, "list_judgment_items"):
            payload["items"] = [
                i.model_dump(mode="json")
                for i in ws.store.list_judgment_items(status="active")
            ]
        return json.dumps(payload, ensure_ascii=False)

    @mcp.tool()
    def privacy_evaluate(
        claim_ids: Optional[list[str]] = None,
        persona: str = "individual",
        purpose: str = "context_retrieval",
        audience: str = "self",
    ) -> str:
        """Evaluate privacy policies for memories under the MCP process identity
        (env credentials from ``twin setup mcp``)."""
        from ..privacy.engine import evaluate_access
        from ..privacy.yaml_io import bootstrap_policy_set
        bootstrap_policy_set(ws.store, policies_path=ws.cfg.policies_path)
        access = resolve_mcp_access(
            ws.store, persona=persona, purpose=purpose, audience=audience,
        )
        memories = []
        for mid in claim_ids or []:
            m = ws.store.get_claim(mid)
            if m:
                memories.append(m)
        if not memories:
            memories = ws.store.list_claims(status="confirmed", limit=20)
        result = evaluate_access(ws.store, access, memories, persist=True)
        d = result["decision"]
        return json.dumps({
            "decision_id": d.id,
            "effect": d.effect.value,
            "execution_location": result.get("execution_location"),
            "tool_id": access.tool_id,
            "restricted": access.is_restricted_mode,
            "resources": [
                {"id": rd.resource_id, "effect": rd.effect.value, "reason": rd.reason}
                for rd in d.resource_decisions
            ],
        }, ensure_ascii=False)

    @mcp.tool()
    def privacy_explain(decision_id: str) -> str:
        """Explain a privacy decision without exposing blocked content."""
        from ..privacy.engine import explain_decision
        try:
            return json.dumps(explain_decision(ws.store, decision_id), ensure_ascii=False)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

    @mcp.tool()
    def privacy_validate_output(text: str) -> str:
        """Scan generated/exported text before release."""
        from ..privacy.engine import validate_output
        access = resolve_mcp_access(ws.store)
        return json.dumps(validate_output(text, access=access, store=ws.store), ensure_ascii=False)

    # -- connectors  — admin/read only; never exposes raw payloads ---
    #
    # Every tool resolves the MCP process identity and checks a connector:*
    # capability. read_context_pack never implies connector:read, and
    # connector:read never implies connector:sync.

    def _connector_access():
        return resolve_mcp_access(ws.store)

    def _connector_denied(auth) -> str:
        return json.dumps({"error": "not_authorized", "reason": auth.reason})

    @mcp.tool()
    def connector_list() -> str:
        """List connector instances (type, status, ownership) this client is
        allowed to see. Requires capability connector:read. No secrets."""
        from twin.sense.connectors import CAP_READ, authorize_connector, connector_health
        from twin.sense.connectors import visible_connectors
        access = _connector_access()
        auth = authorize_connector(ws.store, access, CAP_READ)
        if not auth.allowed:
            return _connector_denied(auth)
        out = []
        for inst in visible_connectors(ws.store, access):
            acc = ws.store.get_source_account(inst.account_id)
            out.append({
                "connector_id": inst.id,
                "connector_type": inst.connector_type,
                "status": inst.status.value,
                "source_owner": acc.source_owner.value if acc else None,
                "vault_id": acc.vault_id if acc else None,
                "health": connector_health(ws.store, inst.id).get("health"),
            })
        return json.dumps(out, ensure_ascii=False)

    @mcp.tool()
    def connector_status(connector_id: str) -> str:
        """Health, last batch, checkpoints and dead-letter depth for a
        connector. Requires capability connector:read on that connector."""
        from twin.sense.connectors import CAP_READ, authorize_connector, connector_health
        access = _connector_access()
        auth = authorize_connector(ws.store, access, CAP_READ,
                                   connector_id=connector_id)
        if not auth.allowed:
            return _connector_denied(auth)
        return json.dumps(connector_health(ws.store, connector_id), ensure_ascii=False)

    @mcp.tool()
    def connector_health_all() -> str:
        """Aggregate health across the connectors this client may read.
        Requires capability connector:read."""
        from twin.sense.connectors import CAP_READ, authorize_connector, connector_health
        from twin.sense.connectors import visible_connectors
        access = _connector_access()
        auth = authorize_connector(ws.store, access, CAP_READ)
        if not auth.allowed:
            return _connector_denied(auth)
        return json.dumps(
            [connector_health(ws.store, i.id)
             for i in visible_connectors(ws.store, access)],
            ensure_ascii=False,
        )

    @mcp.tool()
    def connector_dead_letters(connector_id: str) -> str:
        """Open dead letters for a connector (sanitized errors only).
        Requires capability connector:read (or connector:read:errors)."""
        from twin.sense.connectors import CAP_READ_ERRORS, authorize_connector
        access = _connector_access()
        auth = authorize_connector(ws.store, access, CAP_READ_ERRORS,
                                   connector_id=connector_id)
        if not auth.allowed:
            return _connector_denied(auth)
        return json.dumps([
            {"id": d.id, "failure_class": d.failure_class.value,
             "status": d.status.value, "attempts": d.attempts,
             "external_type": d.external_type, "external_id": d.external_id,
             "error": d.last_error}
            for d in ws.store.list_connector_dead_letters(connector_id)
        ], ensure_ascii=False)

    @mcp.tool()
    def connector_backfill_preview(connector_id: str) -> str:
        """What a backfill WOULD ingest for a connector — per-stream scope,
        vault, ingestion policy and provider-side volume estimates. Read
        only: previewing never starts ingestion. Requires capability
        connector:backfill on that connector."""
        from twin.sense.connectors import (
            CAP_BACKFILL,
            authorize_connector,
            backfill_preview,
            build_credential_store,
        )
        access = _connector_access()
        auth = authorize_connector(ws.store, access, CAP_BACKFILL,
                                   connector_id=connector_id)
        if not auth.allowed:
            return _connector_denied(auth)
        try:
            preview = backfill_preview(
                ws.store, build_credential_store(ws.cfg.home), connector_id,
                principal_id=access.principal_id,
            )
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps(preview, ensure_ascii=False)

    @mcp.tool()
    def connector_sync(
        connector_id: str,
        confirm: bool = False,
        confirm_token: Optional[str] = None,
    ) -> str:
        """Trigger one sync pass (mutating). Requires capability
        connector:sync on the connector's vault.

        Two-step: call without confirm to receive a preview with a
        `confirm_token` (a fingerprint of the connector's exact state —
        account, vault, configuration, checkpoints, adapter version and your
        identity). Then call again with confirm=true and that token; if the
        connector changed in between, the token no longer matches and a fresh
        preview is required. Never returns raw payloads."""
        from twin.sense.connectors import (
            CAP_SYNC,
            authorize_connector,
            build_credential_store,
            sync_connector,
            sync_fingerprint,
        )
        access = _connector_access()
        auth = authorize_connector(ws.store, access, CAP_SYNC,
                                   connector_id=connector_id)
        if not auth.allowed:
            return _connector_denied(auth)
        try:
            fingerprint = sync_fingerprint(
                ws.store, connector_id, principal_id=access.principal_id,
            )
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        if not confirm:
            return json.dumps({
                "requires_confirmation": True,
                "action": "connector_sync",
                "connector_id": connector_id,
                "tool_id": access.tool_id,
                "confirm_token": fingerprint,
            })
        if confirm_token != fingerprint:
            return json.dumps({
                "error": "stale_preview",
                "reason": "connector state changed since the preview — "
                          "request a new preview and confirm_token",
            })
        creds = build_credential_store(ws.cfg.home)
        try:
            result = sync_connector(ws.store, creds, connector_id)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps({
            "health": result.health.value,
            "percepts": result.percepts,
            "streams": [
                {"stream": s.stream, "committed": s.committed,
                 "skipped": s.skipped,
                 "normalized": s.normalized, "quarantined": s.quarantined,
                 "percepts": s.percepts, "failed": s.failed}
                for s in result.streams
            ],
        }, ensure_ascii=False)

    return mcp


def main(home: Optional[str] = None) -> None:
    create_server(home).run()


if __name__ == "__main__":
    main()
