"""MCP server (stdio) — exposes the memory layer to Cursor, Claude Desktop,
Claude Code and any other MCP client.

Run:  twin mcp          (or: python -m twin.interfaces.mcp_server)

Client config example (Claude Desktop / Cursor):
    {
      "mcpServers": {
        "twin": { "command": "twin", "args": ["mcp"] }
      }
    }
"""

from __future__ import annotations

import json
from typing import Any, Optional

from ..cognition.context_pack import build_context_pack
from ..cognition.observer import observe
from ..cognition.sessions import (
    complete_session,
    observe_session,
    record_feedback,
    start_session,
)
from ..judgment.profile import load_profile
from ..memory.search import search
from ..workspace import Workspace


def _memory_to_dict(mem) -> dict[str, Any]:
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
            "Personal memory layer for the user. Call memory_safe_context_pack "
            "at the start of technical tasks to load the user's relevant context "
            "(decisions, preferences, projects) without re-asking. All results "
            "are already filtered by the user's privacy Domain Firewall."
        ),
    )

    @mcp.tool()
    def memory_search(
        query: str,
        domain: str = "technical",
        type: Optional[str] = None,
        limit: int = 10,
    ) -> str:
        """Hybrid search (text + semantic + graph) over the user's memories.
        `domain` is the domain of YOUR current task (work, technical,
        personal_preferences, assistant_preferences) and controls privacy
        filtering. Optional `type` filters by memory type (decision, task,
        preference, belief, fact, event, procedure, constraint)."""
        result = search(ws.store, ws.embedder, query, target_domain=domain,
                        firewall=ws.firewall, type_=type, limit=limit)
        return json.dumps({
            "hits": [
                {**_memory_to_dict(h.memory), "score": h.score, "why": h.why}
                for h in result.hits
            ],
            "blocked": [{"memory_id": b.memory_id, "reason": b.rule} for b in result.blocked],
        }, ensure_ascii=False)

    @mcp.tool()
    def memory_get(memory_id: str) -> str:
        """Fetch one memory by id, including its evidence quotes and percepts."""
        mem = ws.store.get_memory(memory_id)
        if mem is None:
            return json.dumps({"error": "not found"})
        evidence = [{"quote": e.quote, "percept_id": e.percept_id}
                    for e in ws.store.get_evidence(memory_id)]
        return json.dumps({**_memory_to_dict(mem), "evidence": evidence}, ensure_ascii=False)

    @mcp.tool()
    def memory_related(entity: str) -> str:
        """Entities and memories connected to a given entity name in the
        knowledge graph (projects, people, systems, tools)."""
        ent = ws.store.get_entity_by_name(entity)
        if ent is None:
            return json.dumps({"error": f"entity '{entity}' not found"})
        memories = ws.store.memories_for_entity(ent.id)
        relations = ws.store.relations_for(ent.id)
        return json.dumps({
            "entity": {"id": ent.id, "name": ent.name, "type": ent.entity_type},
            "memories": [_memory_to_dict(m) for m in memories[:20]],
            "relations": [
                {"subject": r.subject_id, "predicate": r.predicate, "object": r.object_id}
                for r in relations[:50]
            ],
        }, ensure_ascii=False)

    @mcp.tool()
    def memory_project_context(project_name: str) -> str:
        """Everything known about a project: memories linked to it plus the
        most recent decisions."""
        ent = ws.store.get_entity_by_name(project_name)
        memories = ws.store.memories_for_entity(ent.id) if ent else []
        result = search(ws.store, ws.embedder, project_name, target_domain="technical",
                        firewall=ws.firewall, limit=10)
        by_id = {m.id: m for m in memories}
        for h in result.hits:
            by_id.setdefault(h.memory.id, h.memory)
        items = sorted(by_id.values(), key=lambda m: m.created_at, reverse=True)
        return json.dumps({
            "project": project_name,
            "memories": [_memory_to_dict(m) for m in items[:25]],
        }, ensure_ascii=False)

    @mcp.tool()
    def memory_recent_decisions(project_name: Optional[str] = None, limit: int = 10) -> str:
        """Most recent technical/work decisions, optionally scoped to a project."""
        decisions = ws.store.list_memories(type_="decision", limit=100)
        if project_name:
            needle = project_name.lower()
            decisions = [
                d for d in decisions
                if needle in d.title.lower() or needle in d.summary.lower()
                or any(needle == e.lower() for e in d.entities)
            ]
        return json.dumps(
            [_memory_to_dict(d) for d in decisions[:limit]], ensure_ascii=False
        )

    @mcp.tool()
    def memory_user_preferences(context: str = "") -> str:
        """The user's stable preferences (technical + communication),
        optionally ranked by relevance to `context`."""
        prefs = ws.store.list_memories(type_="preference", limit=100)
        if context:
            ranked = search(ws.store, ws.embedder, context, target_domain="assistant_preferences",
                            firewall=ws.firewall, type_="preference", limit=20)
            ids_ranked = [h.memory.id for h in ranked.hits]
            prefs.sort(key=lambda p: ids_ranked.index(p.id) if p.id in ids_ranked else 999)
        return json.dumps([_memory_to_dict(p) for p in prefs[:20]], ensure_ascii=False)

    @mcp.tool()
    def memory_judgment_profile() -> str:
        """Active judgment items (DB) plus YAML bootstrap. Prefer judgment_applicable
        for scoped injection into a task."""
        payload = dict(load_profile(ws.cfg.judgment_path))
        if hasattr(ws.store, "list_judgment_items"):
            payload["items"] = [
                i.model_dump(mode="json")
                for i in ws.store.list_judgment_items(status="active")
            ]
        return json.dumps(payload, ensure_ascii=False)

    def _resolve_project_id(project: Optional[str]) -> Optional[str]:
        if not project:
            return None
        found = ws.store.get_project(project) or ws.store.find_project(project)
        return found.id if found else None

    @mcp.tool()
    def memory_safe_context_pack(
        query: str,
        target_domain: str = "technical",
        max_tokens: int = 1200,
        include_judgment: bool = True,
        include_candidates: bool = False,
        task_profile: str = "general",
        project: Optional[str] = None,
        client: Optional[str] = None,
        client_token: Optional[str] = None,
        persona: str = "individual",
        purpose: str = "memory_retrieval",
        audience: str = "self",
    ) -> str:
        """Returns a compact, privacy-filtered context pack (judgment profile
        + relevant memories, organized in sections: decisions, constraints,
        tasks, preferences, facts, evidence) to ground your work in the
        user's real context. For a full unit of work prefer session_start,
        which wraps this pack in a trackable session.
        Only human-confirmed memories are included unless you explicitly set
        include_candidates=true — never treat candidates as established fact.
        `query` should describe the task you are about to do; `task_profile`
        (general, coding, architecture, debugging, writing, planning, review,
        meeting_prep) reorders sections for that kind of task; `project` is
        an optional project name/alias to boost project-linked memories.
        Identity: pass registered `client` + `client_token` (credential).
        Omitting them activates restricted mode — MCP never inherits local-cli."""
        from ..privacy.identity import resolve_access
        access = resolve_access(
            ws.store, surface="mcp", client=client,
            persona=persona, purpose=purpose, audience=audience,
            project_id=_resolve_project_id(project),
            requested_domains=[target_domain],
            api_token=client_token,
        )
        pack = build_context_pack(
            ws.store, ws.cfg, ws.embedder, query,
            target_domain=target_domain, max_tokens=max_tokens,
            include_judgment=include_judgment,
            include_candidates=include_candidates,
            task_profile=task_profile,
            project_id=_resolve_project_id(project),
            firewall=ws.firewall,
            access=access,
        )
        return json.dumps({
            "context_pack": pack.context_pack,
            "sources": pack.sources,
            "confidence": pack.confidence,
            "blocked": pack.blocked,
            "task_profile": pack.task_profile,
            "project_id": pack.project_id,
            "privacy_decision_id": pack.privacy_decision_id,
            "privacy_meta": pack.privacy_meta,
            "evidence_included": pack.evidence_included,
            "evidence_omitted_due_to_budget": pack.evidence_omitted_due_to_budget,
        }, ensure_ascii=False)

    # -- Cognitive session lifecycle --------------------------------------

    def _session_dict(session) -> dict[str, Any]:
        data = session.model_dump()
        data["status"] = session.status.value
        return data

    @mcp.tool()
    def session_start(
        query: str,
        client: str = "mcp",
        client_token: Optional[str] = None,
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
        it is never silently replaced by an inferred one."""
        try:
            started = start_session(
                ws.store, ws.cfg, ws.embedder, query,
                client=client, cwd=cwd, domain=domain, project=project,
                task_profile=task_profile, max_tokens=max_tokens,
                api_token=client_token,
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
            "created_memory_ids": session.created_memory_ids,
        }, ensure_ascii=False)

    @mcp.tool()
    def session_feedback(
        session_id: str,
        verdict: str,
        memory_id: Optional[str] = None,
        note: str = "",
        scope: Optional[str] = None,
    ) -> str:
        """Record how useful the supplied context actually was. `verdict` is
        one of: useful, partially_useful, irrelevant, incorrect,
        missing_context (the user had to re-explain something twin should
        have known), privacy_overblock, privacy_underblock. `scope` says what
        the verdict is about (session | pack | memory; defaults to memory
        when memory_id is given, session otherwise). A memory_id must be one
        of the memories this session supplied or created. This feeds twin's
        product metrics."""
        try:
            session = record_feedback(ws.store, session_id, verdict,
                                      memory_id=memory_id, note=note, scope=scope)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps({
            "session_id": session.id,
            "feedback_count": len(session.feedback),
        }, ensure_ascii=False)

    @mcp.tool()
    def native_bindings(host_type: Optional[str] = None, limit: int = 50) -> str:
        """List HostSessionBindings from the Phase 8 native adapter.

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
    def memory_observe(current_text: str, target_domain: Optional[str] = None) -> str:
        """Memory Observer: pass the user's current message/task and receive
        memories that look relevant (suggested_context) plus what was withheld
        by the privacy firewall (blocked_context, ids only)."""
        suggestion = observe(ws.store, ws.cfg, ws.embedder, current_text, target_domain)
        return json.dumps({
            "inferred_domain": suggestion.inferred_domain,
            "suggested_context": suggestion.suggested_context,
            "blocked_context": suggestion.blocked_context,
        }, ensure_ascii=False)

    # -- v0.3 quality / review (read tools + gated mutations) -----------------

    @mcp.tool()
    def memory_quality(memory_id: str) -> str:
        """Analyze a memory for duplicates, conflicts, merge/split suggestions
        and review priority."""
        from ..cognition.quality import analyze_memory
        report = analyze_memory(ws.store, ws.embedder, memory_id)
        return json.dumps(report.model_dump(mode="json"), ensure_ascii=False)

    @mcp.tool()
    def memory_neighbors(memory_id: str) -> str:
        """Find semantically/entity-related neighbor memories for side-by-side review."""
        from ..cognition.quality import discover_neighbors
        mem = ws.store.get_memory(memory_id)
        if mem is None:
            return json.dumps({"error": "not found"})
        neighbors = discover_neighbors(ws.store, ws.embedder, mem)
        return json.dumps([
            {"memory": _memory_to_dict(n), "similarity": sim, "reason": reason}
            for n, sim, reason in neighbors
        ], ensure_ascii=False)

    @mcp.tool()
    def memory_provenance(memory_id: str) -> str:
        """Navigable lineage: memory → evidence → percept → artifact."""
        from ..memory.provenance import memory_provenance as prov
        return json.dumps(prov(ws.store, memory_id), ensure_ascii=False, default=str)

    @mcp.tool()
    def review_queue(limit: int = 20, conflicts_only: bool = False) -> str:
        """Priority-ordered review queue (risk × impact, not FIFO)."""
        from ..cognition.quality import review_queue as rq
        queue = rq(ws.store, conflicts_only=conflicts_only, limit=limit)
        return json.dumps([_memory_to_dict(m) for m in queue], ensure_ascii=False)

    @mcp.tool()
    def review_batch_get(batch_id: str) -> str:
        """Get a review batch and its progress."""
        from ..memory.batches import get_batch
        batch = get_batch(ws.store, batch_id)
        if batch is None:
            return json.dumps({"error": "not found"})
        return json.dumps(batch.model_dump(), ensure_ascii=False)

    @mcp.tool()
    def review_suggest_action(memory_id: str) -> str:
        """Suggest a curation action without applying it (safe for external clients)."""
        from ..cognition.quality import analyze_memory
        report = analyze_memory(ws.store, ws.embedder, memory_id, persist=False)
        return json.dumps({
            "memory_id": memory_id,
            "suggested_action": report.suggested_action.value,
            "requires_human_review": report.requires_human_review,
            "quality_flags": report.quality_flags,
            "review_priority": report.review_priority,
            "issues": [i.model_dump(mode="json") for i in report.issues],
        }, ensure_ascii=False)

    @mcp.tool()
    def memory_confirm(memory_id: str, confirm: bool = False) -> str:
        """Confirm a candidate memory. Requires confirm=true."""
        if not confirm:
            return json.dumps({"error": "pass confirm=true to apply"})
        from ..memory.models import MemoryStatus
        ws.store.set_status(memory_id, MemoryStatus.confirmed)
        return json.dumps(_memory_to_dict(ws.store.get_memory(memory_id)), ensure_ascii=False)

    @mcp.tool()
    def memory_reject(memory_id: str, confirm: bool = False) -> str:
        """Reject a candidate memory. Requires confirm=true."""
        if not confirm:
            return json.dumps({"error": "pass confirm=true to apply"})
        from ..memory.models import MemoryStatus
        ws.store.set_status(memory_id, MemoryStatus.rejected)
        return json.dumps(_memory_to_dict(ws.store.get_memory(memory_id)), ensure_ascii=False)

    @mcp.tool()
    def memory_archive(memory_id: str, confirm: bool = False) -> str:
        """Archive a memory (removed from default retrieval). Requires confirm=true."""
        if not confirm:
            return json.dumps({"error": "pass confirm=true to apply"})
        from ..memory.lifecycle import archive_memory
        result = archive_memory(ws.store, memory_id)
        return json.dumps({"action": result.action, "operation_id": result.operation_id})

    @mcp.tool()
    def memory_merge(memory_ids: list[str], confirm: bool = False,
                     title: Optional[str] = None, summary: Optional[str] = None,
                     confirm_cross_scope_merge: bool = False,
                     output_type: Optional[str] = None,
                     output_domain: Optional[str] = None,
                     output_persona: Optional[str] = None,
                     output_project_id: Optional[str] = None) -> str:
        """Merge memories into one. Requires confirm=true.

        Mixed type/domain/persona/project requires the matching output_* field;
        confirm_cross_scope_merge only authorizes the attempt.
        """
        if not confirm:
            return json.dumps({"error": "pass confirm=true to apply", "preview": memory_ids})
        from ..memory.lifecycle import merge_memories
        kwargs: dict = {
            "title": title, "summary": summary, "embedder": ws.embedder,
            "confirm_cross_scope_merge": confirm_cross_scope_merge,
            "output_type": output_type, "output_domain": output_domain,
            "output_persona": output_persona,
        }
        if output_project_id is not None:
            kwargs["output_project_id"] = output_project_id
        try:
            result = merge_memories(ws.store, memory_ids, **kwargs)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps({"merged_id": result.extras.get("merged_id"),
                           "operation_id": result.operation_id})

    @mcp.tool()
    def memory_split(memory_id: str, parts: list[str], confirm: bool = False) -> str:
        """Split a compound memory. parts are titles/summaries. Requires confirm=true."""
        if not confirm:
            return json.dumps({"error": "pass confirm=true to apply", "parts": parts})
        from ..memory.lifecycle import split_memory
        result = split_memory(
            ws.store, memory_id,
            [{"title": p, "summary": p} for p in parts],
            embedder=ws.embedder,
        )
        return json.dumps({"children": result.extras.get("children"),
                           "operation_id": result.operation_id})

    # -- v0.4 judgment (read tools + gated mutations) ----------------------

    @mcp.tool()
    def judgment_applicable(domain: str = "technical", task_profile: str = "general",
                            project: Optional[str] = None, query: str = "") -> str:
        """Return only judgment items applicable to this domain/task — not the full profile."""
        from ..judgment.application import applicable_pack
        pack = applicable_pack(
            ws.store, domain=domain, task_profile=task_profile,
            project_id=_resolve_project_id(project), query=query,
        )
        return json.dumps(pack, ensure_ascii=False)

    @mcp.tool()
    def judgment_simulate(query: str, domain: str = "technical",
                          task_profile: str = "architecture",
                          project: Optional[str] = None) -> str:
        """Explain how active judgment would influence a recommendation (no side effects)."""
        from ..judgment.simulate import simulate
        return json.dumps(simulate(
            ws.store, query, domain=domain, task_profile=task_profile,
            project_id=_resolve_project_id(project),
        ), ensure_ascii=False, default=str)

    @mcp.tool()
    def judgment_proposals(status: str = "pending") -> str:
        """List judgment proposals awaiting human review."""
        return json.dumps(
            [p.model_dump(mode="json") for p in ws.store.list_judgment_proposals(status=status)],
            ensure_ascii=False,
        )

    @mcp.tool()
    def judgment_proposal_preview(proposal_id: str) -> str:
        """Preview a proposal and obtain a state-aware preview_token for approval."""
        from ..judgment.proposals import preview_proposal
        try:
            return json.dumps(preview_proposal(ws.store, proposal_id), ensure_ascii=False)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

    @mcp.tool()
    def judgment_proposal_approve(proposal_id: str, preview_token: str,
                                  confirm: bool = False,
                                  confirm_constitutional: bool = False) -> str:
        """Approve a judgment proposal (creates a new version). Requires confirm=true."""
        if not confirm:
            return json.dumps({"error": "pass confirm=true to apply"})
        from ..judgment.proposals import approve_proposal
        try:
            return json.dumps(approve_proposal(
                ws.store, proposal_id, preview_token=preview_token,
                confirm_constitutional=confirm_constitutional,
            ), ensure_ascii=False)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

    @mcp.tool()
    def judgment_proposal_reject(proposal_id: str, confirm: bool = False,
                                 reason: str = "") -> str:
        if not confirm:
            return json.dumps({"error": "pass confirm=true to apply"})
        from ..judgment.proposals import reject_proposal
        try:
            p = reject_proposal(ws.store, proposal_id, reason=reason)
            return json.dumps(p.model_dump(mode="json"), ensure_ascii=False)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

    @mcp.tool()
    def judgment_conflicts(status: str = "open") -> str:
        return json.dumps(
            [c.model_dump(mode="json") for c in ws.store.list_judgment_conflicts(status=status)],
            ensure_ascii=False,
        )

    @mcp.tool()
    def judgment_version() -> str:
        v = ws.store.get_active_judgment_version()
        return json.dumps(v.model_dump(mode="json") if v else None, ensure_ascii=False)

    @mcp.tool()
    def privacy_evaluate(
        memory_ids: Optional[list[str]] = None,
        client: Optional[str] = None,
        client_token: Optional[str] = None,
        persona: str = "individual",
        purpose: str = "memory_retrieval",
        audience: str = "self",
    ) -> str:
        """Evaluate privacy policies for memories under a resolved client identity.
        Omitting `client`/`client_token` activates restricted mode (never local-cli)."""
        from ..privacy.engine import evaluate_access
        from ..privacy.identity import resolve_access
        from ..privacy.yaml_io import bootstrap_policy_set
        bootstrap_policy_set(ws.store, policies_path=ws.cfg.policies_path)
        access = resolve_access(
            ws.store, surface="mcp", client=client,
            persona=persona, purpose=purpose, audience=audience,
            api_token=client_token,
        )
        memories = []
        for mid in memory_ids or []:
            m = ws.store.get_memory(mid)
            if m:
                memories.append(m)
        if not memories:
            memories = ws.store.list_memories(status="confirmed", limit=20)
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
    def privacy_validate_output(text: str, client: Optional[str] = None,
                                client_token: Optional[str] = None) -> str:
        """Scan generated/exported text before release."""
        from ..privacy.engine import validate_output
        from ..privacy.identity import resolve_access
        access = resolve_access(
            ws.store, surface="mcp", client=client, api_token=client_token,
        )
        return json.dumps(validate_output(text, access=access, store=ws.store), ensure_ascii=False)

    # -- connectors (v0.6) — admin/read only; never exposes raw payloads ---
    #
    # Every tool resolves the caller's identity and checks a connector:*
    # capability. read_context_pack never implies connector:read, and
    # connector:read never implies connector:sync.

    def _connector_access(client: Optional[str], client_token: Optional[str]):
        from ..privacy.identity import resolve_access
        return resolve_access(
            ws.store, surface="mcp", client=client, api_token=client_token,
        )

    def _connector_denied(auth) -> str:
        return json.dumps({"error": "not_authorized", "reason": auth.reason})

    @mcp.tool()
    def connector_list(client: Optional[str] = None,
                       client_token: Optional[str] = None) -> str:
        """List connector instances (type, status, ownership) this client is
        allowed to see. Requires capability connector:read. No secrets."""
        from ..connectors import CAP_READ, authorize_connector, connector_health
        from ..connectors import visible_connectors
        access = _connector_access(client, client_token)
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
    def connector_status(connector_id: str, client: Optional[str] = None,
                         client_token: Optional[str] = None) -> str:
        """Health, last batch, checkpoints and dead-letter depth for a
        connector. Requires capability connector:read on that connector."""
        from ..connectors import CAP_READ, authorize_connector, connector_health
        access = _connector_access(client, client_token)
        auth = authorize_connector(ws.store, access, CAP_READ,
                                   connector_id=connector_id)
        if not auth.allowed:
            return _connector_denied(auth)
        return json.dumps(connector_health(ws.store, connector_id), ensure_ascii=False)

    @mcp.tool()
    def connector_health_all(client: Optional[str] = None,
                             client_token: Optional[str] = None) -> str:
        """Aggregate health across the connectors this client may read.
        Requires capability connector:read."""
        from ..connectors import CAP_READ, authorize_connector, connector_health
        from ..connectors import visible_connectors
        access = _connector_access(client, client_token)
        auth = authorize_connector(ws.store, access, CAP_READ)
        if not auth.allowed:
            return _connector_denied(auth)
        return json.dumps(
            [connector_health(ws.store, i.id)
             for i in visible_connectors(ws.store, access)],
            ensure_ascii=False,
        )

    @mcp.tool()
    def connector_dead_letters(connector_id: str, client: Optional[str] = None,
                               client_token: Optional[str] = None) -> str:
        """Open dead letters for a connector (sanitized errors only).
        Requires capability connector:read (or connector:read:errors)."""
        from ..connectors import CAP_READ_ERRORS, authorize_connector
        access = _connector_access(client, client_token)
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
    def connector_backfill_preview(connector_id: str,
                                   client: Optional[str] = None,
                                   client_token: Optional[str] = None) -> str:
        """What a backfill WOULD ingest for a connector — per-stream scope,
        vault, ingestion policy and provider-side volume estimates. Read
        only: previewing never starts ingestion. Requires capability
        connector:backfill on that connector."""
        from ..connectors import (
            CAP_BACKFILL,
            authorize_connector,
            backfill_preview,
            build_credential_store,
        )
        access = _connector_access(client, client_token)
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
        client: Optional[str] = None,
        client_token: Optional[str] = None,
    ) -> str:
        """Trigger one sync pass (mutating). Requires capability
        connector:sync on the connector's vault.

        Two-step: call without confirm to receive a preview with a
        `confirm_token` (a fingerprint of the connector's exact state —
        account, vault, configuration, checkpoints, adapter version and your
        identity). Then call again with confirm=true and that token; if the
        connector changed in between, the token no longer matches and a fresh
        preview is required. Never returns raw payloads."""
        from ..connectors import (
            CAP_SYNC,
            authorize_connector,
            build_credential_store,
            sync_connector,
            sync_fingerprint,
        )
        access = _connector_access(client, client_token)
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
