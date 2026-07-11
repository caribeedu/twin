"""Local HTTP API + minimal review UI.

Run:  twin serve   →  http://127.0.0.1:8765

The UI is intentionally tiny (server-rendered HTML, no build step): review
candidate memories, approve/reject, fix domain/sensitivity, inspect evidence,
export JSON. Everything else happens through the JSON API or MCP.
"""

from __future__ import annotations

import html
from typing import Any, Optional

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from ..cognition import extract_pending
from ..cognition.context_pack import build_context_pack
from ..cognition.observer import observe
from ..config import ALL_DOMAINS
from ..judgment.profile import load_profile
from ..memory.models import MemoryStatus
from ..memory.search import search
from ..workspace import Workspace


class IngestRequest(BaseModel):
    paths: list[str]


class ObserveRequest(BaseModel):
    current_text: str
    target_domain: Optional[str] = None


class PackRequest(BaseModel):
    query: str
    target_domain: str = "technical"
    max_tokens: int = 1200
    include_judgment: bool = True
    include_candidates: bool = False  # confirmed-only by default (§27.1)


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

    @app.post("/api/context_pack")
    def api_pack(req: PackRequest):
        pack = build_context_pack(ws.store, ws.cfg, ws.embedder, req.query,
                                  target_domain=req.target_domain,
                                  max_tokens=req.max_tokens,
                                  include_judgment=req.include_judgment,
                                  include_candidates=req.include_candidates,
                                  firewall=ws.firewall)
        return pack.__dict__

    @app.post("/api/memories/{memory_id}/promote")
    def api_promote(memory_id: str):
        from ..judgment.profile import promote_memory

        mem = ws.store.get_memory(memory_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        try:
            section = promote_memory(ws.cfg.judgment_path, mem)
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

    @app.get("/api/judgment")
    def api_judgment():
        return load_profile(ws.cfg.judgment_path)

    @app.get("/api/export")
    def api_export():
        """Full JSON export (vendor-independence guarantee)."""
        memories = ws.store.list_memories(limit=100000)
        return JSONResponse({
            "memories": [
                {**_mem_dict(m), "evidence": [e.model_dump() for e in ws.store.get_evidence(m.id)]}
                for m in memories
            ],
            "entities": [e.model_dump() for e in ws.store.list_entities()],
            "judgment": load_profile(ws.cfg.judgment_path),
        })

    # -- Minimal review UI -------------------------------------------------

    _PAGE = """<!doctype html><html><head><meta charset="utf-8">
    <title>twin — review</title>
    <style>
      body {{ font-family: -apple-system, system-ui, sans-serif; margin: 2rem auto; max-width: 60rem; color: #1a1a1a; }}
      .mem {{ border: 1px solid #ddd; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }}
      .mem h3 {{ margin: 0 0 .3rem; font-size: 1rem; }}
      .meta {{ color: #666; font-size: .82rem; margin-bottom: .5rem; }}
      .reason {{ color: #b45309; font-size: .85rem; }}
      blockquote {{ border-left: 3px solid #ccc; margin: .5rem 0; padding: .2rem .8rem; color: #444; font-size: .88rem; }}
      form {{ display: inline-block; margin-right: .5rem; }}
      button {{ padding: .35rem .9rem; border-radius: 6px; border: 1px solid #bbb; cursor: pointer; background: #fff; }}
      button.ok {{ background: #16a34a; color: #fff; border-color: #16a34a; }}
      button.no {{ background: #dc2626; color: #fff; border-color: #dc2626; }}
      select {{ padding: .3rem; }}
      nav a {{ margin-right: 1rem; }}
    </style></head><body>
    <h1>twin — memory review</h1>
    <nav><a href="/">review queue</a><a href="/all">all memories</a><a href="/api/export">export JSON</a></nav>
    {body}
    </body></html>"""

    def _render_memory(mem, evidence, review_mode: bool) -> str:
        domain_opts = "".join(
            f'<option value="{d}" {"selected" if d == mem.domain else ""}>{d}</option>'
            for d in ALL_DOMAINS
        )
        sens_opts = "".join(
            f'<option value="{s}" {"selected" if s == mem.sensitivity.value else ""}>{s}</option>'
            for s in ["public", "internal", "private", "restricted"]
        )
        quotes = "".join(f"<blockquote>{html.escape(e.quote)}</blockquote>" for e in evidence[:3])
        reason = (
            f'<div class="reason">⚠ {html.escape(mem.review_reason or "")}</div>'
            if mem.needs_review else ""
        )
        actions = f"""
        <form method="post" action="/review/{mem.id}">
          domain <select name="domain">{domain_opts}</select>
          sensitivity <select name="sensitivity">{sens_opts}</select>
          <button class="ok" name="action" value="approve">approve</button>
          <button class="no" name="action" value="reject">reject</button>
          <button name="action" value="update">save edits</button>
        </form>""" if review_mode else f"<div class='meta'>status: {mem.status.value}</div>"
        return f"""
        <div class="mem">
          <h3>{html.escape(mem.title)}</h3>
          <div class="meta">{mem.type.value} · {mem.domain} · {mem.sensitivity.value}
            · confidence {mem.confidence:.2f} · {mem.created_at[:16]}
            · entities: {html.escape(", ".join(mem.entities) or "—")}</div>
          {reason}
          <p>{html.escape(mem.summary)}</p>
          {quotes}
          {actions}
        </div>"""

    @app.get("/", response_class=HTMLResponse)
    def ui_review_queue():
        pending = [
            m for m in ws.store.list_memories(status="candidate")
            if m.needs_review
        ] or ws.store.list_memories(status="candidate")
        body = "".join(
            _render_memory(m, ws.store.get_evidence(m.id), review_mode=True) for m in pending
        ) or "<p>Nothing to review 🎉</p>"
        return _PAGE.format(body=f"<h2>{len(pending)} pending</h2>{body}")

    @app.get("/all", response_class=HTMLResponse)
    def ui_all():
        memories = ws.store.list_memories(limit=500)
        body = "".join(
            _render_memory(m, ws.store.get_evidence(m.id), review_mode=False) for m in memories
        ) or "<p>No memories yet. Ingest and extract first.</p>"
        return _PAGE.format(body=body)

    @app.post("/review/{memory_id}")
    def ui_review(memory_id: str, action: str = Form(...), domain: str = Form(None),
                  sensitivity: str = Form(None)):
        api_review(memory_id, action=action, domain=domain, sensitivity=sensitivity)
        return RedirectResponse("/", status_code=303)

    return app


def main(home: Optional[str] = None, host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(create_app(home), host=host, port=port)
