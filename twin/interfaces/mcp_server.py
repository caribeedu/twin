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
        """The user's judgment profile: principles, decision criteria and
        communication style. Use this to act consistently with how the user
        thinks, not just what they know."""
        return json.dumps(load_profile(ws.cfg.judgment_path), ensure_ascii=False)

    @mcp.tool()
    def memory_safe_context_pack(
        query: str,
        target_domain: str = "technical",
        max_tokens: int = 1200,
        include_judgment: bool = True,
        include_candidates: bool = False,
    ) -> str:
        """MAIN TOOL — call this at the start of a task. Returns a compact,
        privacy-filtered context pack (judgment profile + relevant memories,
        organized in sections: decisions, constraints, tasks, preferences,
        facts, evidence) to ground your work in the user's real context.
        Only human-confirmed memories are included unless you explicitly set
        include_candidates=true — never treat candidates as established fact.
        `query` should describe the task you are about to do."""
        pack = build_context_pack(
            ws.store, ws.cfg, ws.embedder, query,
            target_domain=target_domain, max_tokens=max_tokens,
            include_judgment=include_judgment,
            include_candidates=include_candidates, firewall=ws.firewall,
        )
        return json.dumps({
            "context_pack": pack.context_pack,
            "sources": pack.sources,
            "confidence": pack.confidence,
            "blocked": pack.blocked,
        }, ensure_ascii=False)

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

    return mcp


def main(home: Optional[str] = None) -> None:
    create_server(home).run()


if __name__ == "__main__":
    main()
