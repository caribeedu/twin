"""Cognize / narrative / stance / inject CLI handlers."""

from __future__ import annotations

from typing import Any


def cognize_run(ws, args) -> dict[str, Any]:
    from twin.cognize.orchestrator import CognizeStage, run_cognize

    until = getattr(args, "until", None)
    until_stage = CognizeStage(until) if until else None
    report = run_cognize(
        ws.store,
        ws.cfg,
        until=until_stage,
        dry_run=bool(getattr(args, "dry_run", False)),
        limit=int(getattr(args, "limit", 50) or 50),
        vault_id=getattr(args, "vault", None) or None,
    )
    return report.to_dict()


def cognize_status(ws, args) -> dict[str, Any]:
    import os

    from twin.cognize.gate import require_chat_llm
    from twin.llm import llm_available

    pending = []
    if hasattr(ws.store, "percepts_pending_cognize"):
        pending = ws.store.percepts_pending_cognize(limit=5_000)
    try:
        reachable = llm_available(ws.cfg)
    except Exception:
        reachable = False
    gate = require_chat_llm(
        extractor=ws.cfg.extractor,
        chat_provider=ws.cfg.normalized_llm_provider,
        chat_reachable=reachable,
        allow_echo_cognition=os.environ.get("TWIN_ALLOW_ECHO_COGNITION", "") == "1",
    )
    vault = getattr(args, "vault", None) or "default"
    open_refs = 0
    competing = 0
    if hasattr(ws.store, "list_open_reflections"):
        open_refs = len(ws.store.list_open_reflections(vault))
    if hasattr(ws.store, "list_competing_interpretations"):
        competing = len(ws.store.list_competing_interpretations(vault))
    last = None
    if hasattr(ws.store, "last_cognize_run"):
        last = ws.store.last_cognize_run(vault)
    return {
        "pending_percepts": len(pending),
        "open_reflections": open_refs,
        "competing_interpretations": competing,
        "llm_reachable": reachable,
        "gate_ok": gate.ok,
        "halt_reason": gate.halt_reason.value if gate.halt_reason else None,
        "detail": gate.detail,
        "extractor": ws.cfg.extractor,
        "model": ws.cfg.resolved_llm_model,
        "last_run": last,
    }


def cognize_review(ws, args) -> dict[str, Any]:
    vault = getattr(args, "vault", None) or "default"
    open_refs = []
    if hasattr(ws.store, "list_open_reflections"):
        open_refs = [
            r.model_dump(mode="json") for r in ws.store.list_open_reflections(vault)
        ]
    competing = []
    if hasattr(ws.store, "list_competing_interpretations"):
        competing = [
            i.model_dump(mode="json")
            for i in ws.store.list_competing_interpretations(vault)
        ]
    return {
        "ok": True,
        "vault_id": vault,
        "open_reflections": open_refs,
        "competing_interpretations": competing,
        "counts": {
            "open_reflections": len(open_refs),
            "competing_interpretations": len(competing),
        },
    }


def narrative_show(ws, args) -> dict[str, Any]:
    nar = ws.store.get_narrative(args.narrative_id)
    if nar is None:
        return {"ok": False, "error": "not_found"}
    eps = (
        ws.store.get_epistemic_state(nar.epistemic_state_id)
        if nar.epistemic_state_id
        else None
    )
    out = nar.model_dump(mode="json")
    out["epistemic"] = eps.model_dump(mode="json") if eps else None
    return {"ok": True, "narrative": out}


def narrative_search(ws, args) -> dict[str, Any]:
    vault = getattr(args, "vault", None) or "default"
    q = (getattr(args, "query", "") or "").lower()
    rows = []
    for nar in ws.store.list_narratives(vault):
        if q and q not in nar.account.lower() and q not in (nar.domain or "").lower():
            continue
        eps = (
            ws.store.get_epistemic_state(nar.epistemic_state_id)
            if nar.epistemic_state_id
            else None
        )
        rows.append(
            {
                "id": nar.id,
                "account": nar.account[:200],
                "domain": nar.domain,
                "epistemic_status": eps.status.value if eps else None,
            }
        )
    return {"ok": True, "count": len(rows), "narratives": rows}


def narrative_commit_preview(ws, args) -> dict[str, Any]:
    from twin.cognize.commit import preview_commit_token

    evidence = list(getattr(args, "evidence", None) or [])
    if getattr(args, "evidence_id", None):
        evidence.append(args.evidence_id)
    token = preview_commit_token(
        account=getattr(args, "account", None) or "",
        evidence_ids=evidence,
        vault_id=getattr(args, "vault", None) or "default",
        interpretation_ids=list(getattr(args, "interpretation", None) or []),
        dissent_interpretation_ids=list(getattr(args, "dissent", None) or []),
        domain=getattr(args, "domain", None) or "",
    )
    return {
        "ok": True,
        "preview_token": token,
        "account": getattr(args, "account", None) or "",
        "evidence_ids": evidence,
        "vault_id": getattr(args, "vault", None) or "default",
    }


def narrative_commit(ws, args) -> dict[str, Any]:
    from twin.cognize.commit import CommitError, commit_narrative

    evidence = list(getattr(args, "evidence", None) or [])
    if getattr(args, "evidence_id", None):
        evidence.append(args.evidence_id)
    try:
        nar = commit_narrative(
            ws.store,
            account=args.account,
            vault_id=getattr(args, "vault", None) or "default",
            evidence_ids=evidence,
            committed_by=getattr(args, "actor", None) or "user",
            interpretation_ids=list(getattr(args, "interpretation", None) or []),
            dissent_interpretation_ids=list(getattr(args, "dissent", None) or []),
            domain=getattr(args, "domain", None) or "",
            supersedes_narrative_id=getattr(args, "supersedes", None) or None,
            preview_token=getattr(args, "token", None) or None,
            require_preview_token=bool(getattr(args, "require_token", False)),
        )
    except CommitError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "narrative_id": nar.id,
        "epistemic_state_id": nar.epistemic_state_id,
        "preview_token": (nar.metadata or {}).get("preview_token"),
    }


def narrative_backfill(ws, args) -> dict[str, Any]:
    from twin.cognize.migrate import backfill_from_memories

    return backfill_from_memories(
        ws.store,
        vault_id=getattr(args, "vault", None) or "default",
        dry_run=not bool(getattr(args, "apply", False)),
        limit=int(getattr(args, "limit", 10_000) or 10_000),
    )


def stance_list(ws, args) -> dict[str, Any]:
    from twin.cognize.stance import list_stances

    rows = [s.model_dump(mode="json") for s in list_stances(ws.store)]
    return {"ok": True, "count": len(rows), "stances": rows}


def inject_pack(ws, args) -> dict[str, Any]:
    from twin.inject.context_pack import build_context_pack

    pack = build_context_pack(
        ws.store,
        ws.cfg,
        ws.embedder,
        query=args.query,
        target_domain=getattr(args, "domain", None) or "technical",
        max_tokens=int(getattr(args, "max_tokens", 1200) or 1200),
    )
    return pack.to_dict()


def narrative_accessibility(ws, args) -> dict[str, Any]:
    from twin.cognize.fade import (
        list_accessibility_recommendations,
        recommend_accessibility,
    )

    vault = getattr(args, "vault", None) or "default"
    if getattr(args, "apply", False):
        recs = recommend_accessibility(ws.store, vault_id=vault, dry_run=False)
    else:
        recs = list_accessibility_recommendations(ws.store, vault_id=vault)
        if not recs:
            recs = recommend_accessibility(ws.store, vault_id=vault, dry_run=True)
    return {"ok": True, "count": len(recs), "recommendations": recs}


def research_revisions(ws, args) -> dict[str, Any]:
    from twin.cognize.research import list_revision_research_rows

    rows = list_revision_research_rows(
        ws.store,
        getattr(args, "vault", None) or "",
        limit=int(getattr(args, "limit", 200) or 200),
    )
    return {"ok": True, "count": len(rows), "revisions": rows}
