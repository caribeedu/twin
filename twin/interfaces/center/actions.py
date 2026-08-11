"""Shared Command Center actions — call the same functions as CLI handlers."""

from __future__ import annotations

from typing import Any, Optional

from twin.workspace import Workspace


def cognize_status(ws: Workspace) -> dict[str, Any]:
    import os

    from twin.cognize.gate import require_chat_llm

    gate = require_chat_llm(
        extractor=ws.cfg.extractor,
        chat_provider=ws.cfg.normalized_llm_provider,
        allow_echo_cognition=os.environ.get("TWIN_ALLOW_ECHO_COGNITION", "") == "1",
    )
    last = ws.store.last_cognize_run() if hasattr(ws.store, "last_cognize_run") else None
    refs = (
        ws.store.list_open_reflections("default")
        if hasattr(ws.store, "list_open_reflections")
        else []
    )
    return {
        "halted": gate.halted,
        "halt_reason": gate.halt_reason.value if gate.halt_reason else None,
        "detail": gate.detail,
        "open_reflections": len(refs),
        "reflection_previews": [
            {"id": r.id, "text": (r.text or "")[:120]} for r in refs[:8]
        ],
        "last_run": last,
    }


def cognize_runs_page(
    ws: Workspace,
    *,
    page: int = 0,
    page_size: int = 5,
    vault: str = "default",
) -> dict[str, Any]:
    page = max(0, int(page))
    page_size = max(1, min(int(page_size), 50))
    total = 0
    runs: list[dict[str, Any]] = []
    if hasattr(ws.store, "count_cognize_runs"):
        total = int(ws.store.count_cognize_runs(vault) or 0)
    if hasattr(ws.store, "list_cognize_runs"):
        runs = ws.store.list_cognize_runs(
            vault, limit=page_size, offset=page * page_size,
        )
    elif hasattr(ws.store, "last_cognize_run") and page == 0:
        last = ws.store.last_cognize_run(vault)
        runs = [last] if last else []
        total = len(runs)
    pages = max(1, (total + page_size - 1) // page_size) if total else 1
    if page >= pages:
        page = pages - 1
    return {
        "runs": runs,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": pages,
        "has_prev": page > 0,
        "has_next": page + 1 < pages and total > 0,
    }


def cognize_run(ws: Workspace, *, until: str = "evidence_audit", limit: int = 20) -> dict[str, Any]:
    from argparse import Namespace

    from twin.interfaces.commands import cognize_cmd

    args = Namespace(until=until, limit=limit, vault="default", percept_id=None, dry_run=False)
    return cognize_cmd.cognize_run(ws, args)


def narrative_list(ws: Workspace, vault: str = "default") -> list[dict[str, Any]]:
    if not hasattr(ws.store, "list_narratives"):
        return []
    rows = []
    for nar in ws.store.list_narratives(vault)[:40]:
        eps = (
            ws.store.get_epistemic_state(nar.epistemic_state_id)
            if nar.epistemic_state_id
            else None
        )
        rows.append({
            "id": nar.id,
            "account": nar.account,
            "status": nar.status.value if hasattr(nar.status, "value") else str(nar.status),
            "epistemic": eps.status.value if eps else "unknown",
            "stale_reason": eps.stale_reason if eps else "",
            "grain": nar.grain.value if nar.grain else "",
            "domain": nar.domain,
        })
    return rows


def stance_overview(ws: Workspace) -> dict[str, Any]:
    from twin.cognize.stance import list_stances

    stances = [
        {"id": s.id, "statement": s.statement, "status": s.status.value}
        for s in list_stances(ws.store)[:40]
    ]
    proposals = []
    if hasattr(ws.store, "list_judgment_proposals"):
        for p in ws.store.list_judgment_proposals(status="pending", limit=20):
            proposals.append({
                "id": p.id,
                "reason": p.reason,
                "narrative_id": (p.metadata or {}).get("narrative_id"),
            })
    return {"stances": stances, "proposals": proposals}


def approve_stance_proposal(ws: Workspace, proposal_id: str) -> dict[str, Any]:
    from twin.cognize.stance_engine.proposals import approve_proposal, preview_proposal

    preview = preview_proposal(ws.store, proposal_id)
    token = preview.get("preview_token") if isinstance(preview, dict) else getattr(preview, "preview_token", None)
    if not token and isinstance(preview, dict):
        token = preview.get("token")
    out = approve_proposal(ws.store, proposal_id, preview_token=token or "")
    return {"ok": True, "result": out, "proposal_id": proposal_id}


def review_snapshot(ws: Workspace) -> dict[str, Any]:
    from twin.cognize.fade import list_accessibility_recommendations

    backlog = len(ws.store.list_claims(status="candidate", limit=500))
    refs = (
        ws.store.list_open_reflections("default")
        if hasattr(ws.store, "list_open_reflections")
        else []
    )
    fade = list_accessibility_recommendations(ws.store, "default")
    return {
        "backlog": backlog,
        "open_reflections": [
            {"id": r.id, "text": (r.text or "")[:160]} for r in refs[:12]
        ],
        "accessibility": fade[:12],
    }


def connector_resource_summary(connector_type: str, configuration: dict[str, Any]) -> str:
    """Human one-liner of selected Sense resources for a connector type."""
    cfg = configuration or {}
    ctype = (connector_type or "").lower()

    def _join(items: list[Any], *, empty: str = "(none selected)") -> str:
        vals = [str(x).strip() for x in items if str(x).strip()]
        return ", ".join(vals) if vals else empty

    if ctype == "github":
        return f"repos: {_join(list(cfg.get('repositories') or []))}"
    if ctype == "folder":
        roots = cfg.get("roots") or []
        paths: list[str] = []
        for root in roots:
            if isinstance(root, dict):
                paths.append(str(root.get("path") or root.get("root") or root))
            else:
                paths.append(str(root))
        return f"paths: {_join(paths)}"
    if ctype == "slack":
        channels = list(cfg.get("channels") or [])
        meta = cfg.get("channel_metadata") or {}
        labels = []
        for cid in channels:
            info = meta.get(cid) if isinstance(meta, dict) else None
            if isinstance(info, dict) and info.get("name"):
                labels.append(f"#{info['name']}")
            else:
                labels.append(str(cid))
        return f"channels: {_join(labels)}"
    if ctype == "gmail":
        return f"labels: {_join(list(cfg.get('labels') or []))}"
    if ctype == "calendar":
        return f"calendars: {_join(list(cfg.get('calendars') or []))}"
    if ctype == "outlook":
        return f"folders: {_join(list(cfg.get('folders') or []))}"
    if ctype == "fireflies":
        email = cfg.get("account_email") or ""
        return f"account: {email}" if email else "account: (default)"
    # Fallback: show any list-ish scope keys if present
    for key in ("repositories", "channels", "labels", "calendars", "folders", "roots", "paths"):
        if key in cfg and cfg[key]:
            return f"{key}: {_join(list(cfg[key]) if isinstance(cfg[key], list) else [cfg[key]])}"
    return "(no resources configured)"


def connector_rows(ws: Workspace) -> list[dict[str, Any]]:
    from twin.sense.connectors.health import connector_health

    rows = []
    if not hasattr(ws.store, "list_connector_instances"):
        return rows
    for inst in ws.store.list_connector_instances():
        hid = getattr(inst, "id", "")
        ctype = getattr(inst, "connector_type", getattr(inst, "type", ""))
        cfg = getattr(inst, "configuration", None) or {}
        health = {}
        try:
            health = connector_health(ws.store, hid)
        except Exception as exc:
            health = {"error": str(exc)}
        rows.append({
            "id": hid,
            "type": ctype,
            "health": health.get("status") or health.get("instance_status") or "",
            "resources": connector_resource_summary(ctype, cfg),
            "detail": health,
        })
    return rows


def connector_pause(ws: Workspace, connector_id: str) -> dict[str, Any]:
    from twin.sense.connectors.service import pause_connector

    inst = pause_connector(ws.store, connector_id)
    return {"ok": True, "id": inst.id, "status": getattr(inst, "status", "paused")}


def connector_resume(ws: Workspace, connector_id: str) -> dict[str, Any]:
    from twin.sense.connectors.service import resume_connector

    inst = resume_connector(ws.store, connector_id)
    return {"ok": True, "id": inst.id, "status": getattr(inst, "status", "active")}


def connector_test(ws: Workspace, connector_id: str) -> dict[str, Any]:
    from twin.sense.connectors.health import connector_health

    return {"ok": True, "id": connector_id, "health": connector_health(ws.store, connector_id)}


def jobs_snapshot(ws: Workspace, *, limit: int = 20) -> dict[str, Any]:
    depth = {}
    if hasattr(ws.store, "runtime_queue_depth"):
        depth = ws.store.runtime_queue_depth() or {}
    jobs = []
    lister = None
    if hasattr(ws.store, "list_runtime_jobs"):
        lister = ws.store.list_runtime_jobs
    elif hasattr(ws.store, "list_jobs"):
        lister = ws.store.list_jobs
    if lister:
        try:
            for job in lister(limit=limit):
                kind = getattr(job, "kind", "")
                if hasattr(kind, "value"):
                    kind = kind.value
                status = getattr(job, "status", getattr(job, "state", ""))
                if hasattr(status, "value"):
                    status = status.value
                progress = getattr(job, "progress", None) or (job.payload or {}).get("progress") if getattr(job, "payload", None) else None
                jobs.append({
                    "id": getattr(job, "id", ""),
                    "kind": kind,
                    "state": status,
                    "progress": progress,
                    "log_ref": getattr(job, "error", "") or (job.payload or {}).get("log_ref", "") if getattr(job, "payload", None) else "",
                })
        except TypeError:
            for job in lister()[:limit]:
                jobs.append({"id": getattr(job, "id", ""), "kind": str(getattr(job, "kind", "")), "state": str(getattr(job, "status", ""))})
    backfills = []
    if hasattr(ws.store, "list_backfill_jobs"):
        try:
            for bf in ws.store.list_backfill_jobs(limit=10):
                backfills.append({
                    "id": getattr(bf, "id", ""),
                    "state": getattr(bf, "status", ""),
                    "progress": getattr(bf, "progress", None) or getattr(bf, "cursor", None),
                })
        except Exception:
            pass
    return {"depth": depth, "jobs": jobs, "backfills": backfills}


def enqueue_job(ws: Workspace, kind: str) -> dict[str, Any]:
    from twin.interfaces.runtime.models import JobKind
    from twin.interfaces.runtime.queue import RuntimeQueue

    q = RuntimeQueue(ws.store)
    jk = JobKind(kind)
    job = q.enqueue(jk, payload={}, vault_id="default")
    return {"ok": True, "job_id": job.id, "kind": jk.value}


def doctor_summary(ws: Workspace) -> dict[str, Any]:
    from twin.interfaces.ops import OK, doctor

    checks = doctor(ws.cfg)
    ok = sum(1 for c in checks if c.status == OK)
    warn = [
        {"name": c.name, "detail": c.detail}
        for c in checks
        if c.status != OK
    ][:8]
    return {
        "home": str(ws.cfg.home),
        "checks_ok": ok,
        "checks_total": len(checks),
        "warnings": warn,
        "extractor": ws.cfg.extractor,
        "embedder": ws.cfg.embedder,
        "llm": getattr(ws.cfg, "normalized_llm_provider", ""),
    }
