"""Late Cognize stages 10–12: Stance drafts, consolidation judgment, Fade.

Prefer chat LLM when available. CI may inject overrides via
``set_late_stage_override``. Without LLM and without override, Stage 11/12
halt (no heuristic meaning). Stage 10 may enqueue a pending twin-influenced
draft after Narrative commit (never auto-approves).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from twin.cognize.fade import recommend_accessibility
from twin.cognize.gate import require_chat_llm
from twin.judgment.proposals import propose_from_narrative

_LATE_OVERRIDES: dict[str, Callable[..., Any]] = {}


def set_late_stage_override(stage: str, fn: Optional[Callable[..., Any]]) -> None:
    if fn is None:
        _LATE_OVERRIDES.pop(stage, None)
    else:
        _LATE_OVERRIDES[stage] = fn


def clear_late_stage_overrides() -> None:
    _LATE_OVERRIDES.clear()


def _gate(cfg: Any):
    import os

    reachable = None
    try:
        from twin.cognition.llm import llm_available

        reachable = llm_available(cfg)
    except Exception:
        reachable = False
    return require_chat_llm(
        extractor=getattr(cfg, "extractor", ""),
        chat_provider=getattr(cfg, "normalized_llm_provider", "") or "",
        chat_reachable=reachable,
        allow_echo_cognition=os.environ.get("TWIN_ALLOW_ECHO_COGNITION", "") == "1",
    )


def draft_stance_after_commit(
    store: Any,
    narrative_id: str,
    *,
    cfg: Any = None,
    domain: Optional[str] = None,
) -> Optional[Any]:
    """Stage 10 — pending Stance draft. Override or LLM when available."""
    if "stance_draft" in _LATE_OVERRIDES:
        return _LATE_OVERRIDES["stance_draft"](store, narrative_id, domain=domain)
    if cfg is not None:
        gate = _gate(cfg)
        if not gate.halted:
            try:
                from twin.cognition.llm import get_chat_client

                llm = get_chat_client(cfg)
                nar = store.get_narrative(narrative_id)
                if nar is not None and llm is not None:
                    data = llm.complete_json(
                        system=(
                            "Draft a durable evaluative Stance from a Narrative. "
                            "Do NOT treat Stance as factual Narrative. "
                            "Return JSON {statement, rationale}."
                        ),
                        user=f"Narrative account:\n{nar.account}",
                    )
                    stmt = str(data.get("statement") or nar.account)[:500]
                    return propose_from_narrative(
                        store, narrative_id, domain=domain, statement=stmt,
                    )
            except Exception:
                pass
    return propose_from_narrative(store, narrative_id, domain=domain)


def run_consolidation_judgment(
    store: Any,
    cfg: Any,
    *,
    vault_id: str = "default",
    max_drafts: int = 20,
    max_tokens: int = 50_000,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Stage 11 — LLM argues generalize vs episodic; humans still gate."""
    if "consolidation_judgment" in _LATE_OVERRIDES:
        return _LATE_OVERRIDES["consolidation_judgment"](
            store, cfg, vault_id=vault_id, max_drafts=max_drafts, dry_run=dry_run,
        )
    gate = _gate(cfg)
    if gate.halted:
        return {
            "ok": False,
            "halted": True,
            "halt_reason": gate.halt_reason.value if gate.halt_reason else None,
            "detail": gate.detail,
            "drafts": [],
        }
    # Token budget is a hard cap on draft count proxy when LLM path unavailable
    # for structured judgment; still never auto-commits Narratives/Stances.
    drafts: list[dict[str, Any]] = []
    budget = max_tokens
    try:
        from twin.cognition.llm import get_chat_client

        llm = get_chat_client(cfg)
        if llm is None:
            return {
                "ok": False,
                "halted": True,
                "detail": "chat client unavailable",
                "drafts": [],
            }
        narratives = store.list_narratives(vault_id) if hasattr(store, "list_narratives") else []
        for nar in narratives[:max_drafts]:
            if budget <= 0:
                break
            if dry_run:
                drafts.append({"narrative_id": nar.id, "dry_run": True})
                continue
            data = llm.complete_json(
                system=(
                    "Decide whether this Narrative should generalize into a Stance "
                    "draft or stay episodic. Never confirm durability. "
                    "Return JSON {action: promote|keep_episodic|skip, statement?, rationale}."
                ),
                user=f"Account:\n{nar.account}\nDomain:{nar.domain}",
            )
            used = max(200, len(nar.account or "") // 4)
            budget -= used
            if data.get("action") == "promote" and data.get("statement"):
                p = propose_from_narrative(
                    store, nar.id, domain=nar.domain or None,
                    statement=str(data["statement"])[:500],
                )
                if p is not None:
                    drafts.append({"narrative_id": nar.id, "proposal_id": p.id})
            else:
                drafts.append({
                    "narrative_id": nar.id,
                    "action": data.get("action") or "keep_episodic",
                    "rationale": data.get("rationale") or "",
                })
    except Exception as exc:
        return {"ok": False, "halted": True, "detail": str(exc), "drafts": drafts}
    return {"ok": True, "halted": False, "drafts": drafts, "tokens_remaining": budget}


def run_fade_judgment(
    store: Any,
    cfg: Any,
    *,
    vault_id: str = "default",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Stage 12 — LLM accessibility recommendations; never delete Narratives."""
    if "fade_judgment" in _LATE_OVERRIDES:
        return _LATE_OVERRIDES["fade_judgment"](
            store, cfg, vault_id=vault_id, dry_run=dry_run,
        )
    gate = _gate(cfg)
    if gate.halted:
        # Deterministic Trace-based recommendations are allowed as *review queue*
        # hints only when LLM halted — labeled heuristic.
        recs = recommend_accessibility(store, vault_id=vault_id, dry_run=dry_run)
        for r in recs:
            r["engine"] = "heuristic_trace"
        return {
            "ok": True,
            "halted": True,
            "detail": gate.detail,
            "recommendations": recs,
        }
    try:
        from twin.cognition.llm import get_chat_client

        llm = get_chat_client(cfg)
        if llm is None:
            recs = recommend_accessibility(store, vault_id=vault_id, dry_run=dry_run)
            return {"ok": True, "halted": True, "recommendations": recs}
        # Prefer LLM labels, fall back to trace heuristic for empties
        base = recommend_accessibility(store, vault_id=vault_id, dry_run=True)
        out = []
        for rec in base[:30]:
            nar = store.get_narrative(rec["narrative_id"])
            if nar is None:
                continue
            data = llm.complete_json(
                system=(
                    "Recommend Narrative accessibility: remarkable|ordinary|fading. "
                    "Never delete. Return JSON {recommended, reason}."
                ),
                user=(
                    f"account={nar.account}\ntrace_hits={rec.get('trace_hits')}\n"
                    f"stance_linked={rec.get('stance_linked')}"
                ),
            )
            label = str(data.get("recommended") or rec["recommended"])
            reason = str(data.get("reason") or rec["reason"])
            item = {
                **rec,
                "recommended": label,
                "reason": reason,
                "engine": "llm",
            }
            out.append(item)
            if not dry_run:
                meta = dict(nar.metadata or {})
                meta["accessibility_recommendation"] = item
                store.upsert_narrative(nar.model_copy(update={"metadata": meta}))
        return {"ok": True, "halted": False, "recommendations": out}
    except Exception as exc:
        recs = recommend_accessibility(store, vault_id=vault_id, dry_run=dry_run)
        return {"ok": False, "detail": str(exc), "recommendations": recs}
