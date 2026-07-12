"""Explainable judgment simulation (demo/local heuristic evaluator).

Option scoring uses a small deterministic local heuristic for demos — not a
general recommendation engine. Callers should pass structured option scores
when available. Without judgment signal, the result abstains.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from ..memory.store.base import MemoryStore
from .application import applicable_pack, record_trace
from .models import AppliedJudgmentEffect, JudgmentContext


def evaluate(
    store: MemoryStore,
    query: str,
    *,
    domain: str = "technical",
    persona: str = "individual",
    task_profile: str = "architecture",
    project_id: Optional[str] = None,
    audience: Optional[str] = None,
    client: Optional[str] = None,
    project_stage: Optional[str] = None,
    options: Optional[list[str]] = None,
    option_scores: Optional[dict[str, dict[str, float]]] = None,
    persist: bool = False,
) -> dict[str, Any]:
    """Core evaluation. ``persist=False`` avoids snapshot/trace side effects."""
    options = options or _guess_options(query)
    ctx = JudgmentContext(
        domain=domain, persona=persona, task_profile=task_profile,
        project_id=project_id, audience=audience, client=client,
        project_stage=project_stage, query=query,
    )
    pack = applicable_pack(store, ctx, persist_snapshot=persist)

    if pack.get("requires_confirmation"):
        return {
            "markdown": _render_confirmation(query, pack),
            "recommendation": None,
            "outcome": "requires_confirmation",
            "scores": {o: 0.0 for o in options},
            "blocked_options": [],
            "ranking": [],
            "snapshot_id": pack.get("snapshot_id"),
            "trace_id": None,
            "pack": pack,
            "simulator": "demo/local heuristic",
        }

    scores = {opt: 0.0 for opt in options}
    reasons: dict[str, list[str]] = {opt: [] for opt in options}
    blocked: list[str] = []
    applied_effects: list[AppliedJudgmentEffect] = []

    for item in pack.get("hard_constraints") or []:
        for opt in options:
            if _constraint_blocks(item["statement"], opt):
                blocked.append(opt)
                applied_effects.append(AppliedJudgmentEffect(
                    judgment_id=item["id"],
                    revision_id=item.get("current_revision_id"),
                    effect="blocked_option", option=opt, weight=1.0,
                    reason=item["statement"],
                ))

    viable = [o for o in options if o not in blocked]
    for item in (pack.get("principles") or []) + (pack.get("heuristics") or []) + (
        pack.get("preferences") or []
    ):
        weight = float(item.get("strength", 0.5)) * float(item.get("confidence", 0.5))
        for opt in viable:
            if option_scores and item.get("tradeoff") and opt in option_scores:
                delta = option_scores[opt].get(item["tradeoff"], 0.0) * weight
            else:
                delta = _lean_score_demo(item["statement"], opt) * weight
            if abs(delta) < 0.05:
                continue
            scores[opt] += delta
            tip = "favors" if delta > 0 else "penalizes"
            reasons[opt].append(f"{tip}: {item['statement']}")
            applied_effects.append(AppliedJudgmentEffect(
                judgment_id=item["id"],
                revision_id=item.get("current_revision_id"),
                effect="favored_option" if delta > 0 else "penalized_option",
                option=opt, weight=abs(delta), reason=item["statement"],
            ))

    vals = list(scores.values()) if scores else [0.0]
    spread = (max(vals) - min(vals)) if vals else 0.0
    if not applied_effects or spread < 0.05:
        recommendation = None
        outcome = "insufficient_judgment_signal"
        ranking = []
    else:
        ranking = sorted(viable, key=lambda o: scores.get(o, 0.0), reverse=True)
        recommendation = ranking[0] if ranking else None
        outcome = "recommendation"

    md = _render_markdown(
        query, pack, options, scores, blocked, ranking, recommendation, reasons, outcome,
    )
    trace = None
    if persist:
        trace = record_trace(
            store,
            query=query,
            snapshot_id=pack.get("snapshot_id") or "",
            applied=applied_effects,
            blocked_options=blocked,
            exceptions_used=pack.get("exceptions_used") or [],
            result={
                "recommendation": recommendation,
                "scores": scores,
                "ranking": ranking,
                "outcome": outcome,
            },
            persist=True,
        )
    return {
        "markdown": md,
        "recommendation": recommendation,
        "outcome": outcome,
        "scores": scores,
        "blocked_options": blocked,
        "ranking": ranking,
        "snapshot_id": pack.get("snapshot_id"),
        "trace_id": trace.id if trace else None,
        "pack": pack,
        "simulator": "demo/local heuristic",
    }


def simulate(store: MemoryStore, query: str, **kwargs: Any) -> dict[str, Any]:
    """Persisting simulation for user-facing recommendations."""
    kwargs = dict(kwargs)
    kwargs["persist"] = True
    return evaluate(store, query, **kwargs)


def counterfactual(
    store: MemoryStore,
    query: str,
    judgment_id: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Compare with/without one judgment — no auxiliary snapshot/trace writes."""
    kwargs = dict(kwargs)
    kwargs["persist"] = False
    baseline = evaluate(store, query, **kwargs)
    pack = baseline["pack"]
    filtered_keys = (
        "hard_constraints", "principles", "heuristics", "preferences",
        "beliefs", "values", "applicable_judgments",
    )
    # Re-evaluate using filtered pack sections manually
    options = list(baseline["scores"].keys()) or _guess_options(query)
    scores = {opt: 0.0 for opt in options}
    blocked: list[str] = []
    applied = 0
    for item in pack.get("hard_constraints") or []:
        if item.get("id") == judgment_id:
            continue
        for opt in options:
            if _constraint_blocks(item["statement"], opt):
                blocked.append(opt)
                applied += 1
    viable = [o for o in options if o not in blocked]
    for key in ("principles", "heuristics", "preferences"):
        for item in pack.get(key) or []:
            if item.get("id") == judgment_id:
                continue
            weight = float(item.get("strength", 0.5)) * float(item.get("confidence", 0.5))
            for opt in viable:
                delta = _lean_score_demo(item["statement"], opt) * weight
                if abs(delta) >= 0.05:
                    scores[opt] += delta
                    applied += 1
    vals = list(scores.values()) if scores else [0.0]
    spread = max(vals) - min(vals) if vals else 0.0
    if applied == 0 or spread < 0.05:
        cf_rec = None
    else:
        ranking = sorted(viable, key=lambda o: scores.get(o, 0.0), reverse=True)
        cf_rec = ranking[0] if ranking else None
    return {
        "without_judgment_id": judgment_id,
        "baseline_recommendation": baseline["recommendation"],
        "counterfactual_recommendation": cf_rec,
        "baseline_scores": baseline["scores"],
        "counterfactual_scores": scores,
        "changed": baseline["recommendation"] != cf_rec,
        "baseline_outcome": baseline.get("outcome"),
    }


def _guess_options(query: str) -> list[str]:
    known = ["PostgreSQL", "Neo4j", "SQLite", "MongoDB", "Kubernetes", "Docker",
             "FastAPI", "microservices", "modular monolith"]
    found = [k for k in known if re.search(re.escape(k), query, re.I)]
    return found or ["option_a", "option_b"]


def _constraint_blocks(statement: str, option: str) -> bool:
    """Demo heuristic — not general knowledge."""
    s = statement.lower()
    o = option.lower()
    if "export" in s or "lock-in" in s:
        if any(x in o for x in ("proprietary", "custom graph")):
            return True
    if "infrastruct" in s or "measured need" in s or "necessidade" in s:
        if any(x in o for x in ("neo4j", "kubernetes", "custom graph")):
            return True
    if "pii" in s or "pessoais" in s:
        if "cloud" in o:
            return True
    return False


def _lean_score_demo(statement: str, option: str) -> float:
    """Demo/local heuristic only — prefer caller-supplied option_scores."""
    s = statement.lower()
    o = option.lower()
    score = 0.0
    if re.search(r"simpli|reversib|manuten|local", s):
        if any(x in o for x in ("postgres", "sqlite", "monolith", "fastapi")):
            score += 0.8
        if any(x in o for x in ("neo4j", "kubernetes", "microservice", "custom")):
            score -= 0.7
    if re.search(r"graph|traversal|relacion", s) and "neo4j" in o:
        score += 0.5
    return score


def _render_confirmation(query, pack) -> str:
    lines = [
        "# Judgment simulation",
        "",
        f"**Query:** {query}",
        "",
        "## Requires confirmation",
        "",
        "An applicable exception requires human confirmation before a recommendation.",
        "",
    ]
    for reason in pack.get("confirmation_reasons") or []:
        lines.append(f"- {reason}")
    return "\n".join(lines)


def _render_markdown(query, pack, options, scores, blocked, ranking, recommendation, reasons, outcome) -> str:
    lines = [
        "# Judgment simulation",
        "",
        f"**Query:** {query}",
        "",
        "_Evaluator: demo/local heuristic (not a general recommender)._",
        "",
        "## Applicable constraints",
        "",
    ]
    for it in pack.get("hard_constraints") or []:
        lines.append(f"- {it['statement']}")
    if not pack.get("hard_constraints"):
        lines.append("- (none)")
    lines += ["", "## Relevant principles", ""]
    for it in pack.get("principles") or []:
        lines.append(f"- {it['statement']}")
    if not pack.get("principles"):
        lines.append("- (none)")
    lines += ["", "## Heuristics", ""]
    for it in pack.get("heuristics") or []:
        lines.append(f"- {it['statement']}")
    lines += ["", "## Preferences", ""]
    for it in pack.get("preferences") or []:
        lines.append(f"- {it['statement']}")
    lines += ["", "## Trade-offs", "", "| Option | Score | Notes |", "|---|---:|---|"]
    for opt in options:
        note = "; ".join(reasons.get(opt, [])[:2]) or (
            "blocked" if opt in blocked else ""
        )
        lines.append(f"| {opt} | {scores.get(opt, 0):.2f} | {note} |")
    lines += ["", "## Judgment-influenced result", ""]
    if outcome == "insufficient_judgment_signal":
        lines.append(
            "The active judgment profile does not distinguish these options "
            "(insufficient signal — abstaining)."
        )
    else:
        lines.append(f"**{recommendation or 'no viable option'}**")
    lines += ["", f"Snapshot: `{pack.get('snapshot_id')}`"]
    return "\n".join(lines)
