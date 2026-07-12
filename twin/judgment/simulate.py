"""Explainable judgment simulation and limited counterfactuals."""

from __future__ import annotations

import re
from typing import Any, Optional

from ..memory.store.base import MemoryStore
from .application import applicable_pack, record_trace
from .models import AppliedJudgmentEffect, JudgmentKind


_TRADEOFF_AXES = [
    ("operational simplicity", re.compile(r"simpli|operacion|manuten|maintenance", re.I)),
    ("reversibility", re.compile(r"reversib|undo|migrat", re.I)),
    ("infrastructure need", re.compile(r"infrastruct|neo4j|kubernetes|microservice", re.I)),
    ("lock-in / exportability", re.compile(r"lock.?in|export|open format|canonical", re.I)),
    ("privacy", re.compile(r"privac|pii|local.?first", re.I)),
]


def simulate(
    store: MemoryStore,
    query: str,
    *,
    domain: str = "technical",
    persona: str = "individual",
    task_profile: str = "architecture",
    project_id: Optional[str] = None,
    options: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Show how the active judgment profile would influence a recommendation."""
    options = options or _guess_options(query)
    pack = applicable_pack(
        store, domain=domain, persona=persona,
        task_profile=task_profile, project_id=project_id, query=query,
    )

    scores = {opt: 0.0 for opt in options}
    reasons: dict[str, list[str]] = {opt: [] for opt in options}
    blocked: list[str] = []
    applied_effects: list[AppliedJudgmentEffect] = []

    for item in pack.get("hard_constraints") or []:
        for opt in options:
            if _constraint_blocks(item["statement"], opt, query):
                blocked.append(opt)
                applied_effects.append(AppliedJudgmentEffect(
                    judgment_id=item["id"], effect="blocked_option",
                    option=opt, weight=1.0, reason=item["statement"],
                ))

    viable = [o for o in options if o not in blocked]
    for item in (pack.get("principles") or []) + (pack.get("heuristics") or []) + (
        pack.get("preferences") or []
    ):
        weight = float(item.get("strength", 0.5)) * float(item.get("confidence", 0.5))
        for opt in viable:
            delta = _lean_score(item["statement"], opt, query) * weight
            if abs(delta) < 0.05:
                continue
            scores[opt] += delta
            tip = "favors" if delta > 0 else "penalizes"
            reasons[opt].append(f"{tip}: {item['statement']}")
            applied_effects.append(AppliedJudgmentEffect(
                judgment_id=item["id"],
                effect="favored_option" if delta > 0 else "penalized_option",
                option=opt, weight=abs(delta), reason=item["statement"],
            ))

    ranking = sorted(viable, key=lambda o: scores.get(o, 0.0), reverse=True)
    recommendation = ranking[0] if ranking else None

    md = _render_markdown(
        query, pack, options, scores, blocked, ranking, recommendation, reasons,
    )
    trace = record_trace(
        store,
        query=query,
        snapshot_id=pack["snapshot_id"],
        applied=applied_effects,
        blocked_options=blocked,
        exceptions_used=pack.get("exceptions_used") or [],
        result={
            "recommendation": recommendation,
            "scores": scores,
            "ranking": ranking,
        },
    )
    return {
        "markdown": md,
        "recommendation": recommendation,
        "scores": scores,
        "blocked_options": blocked,
        "ranking": ranking,
        "snapshot_id": pack["snapshot_id"],
        "trace_id": trace.id,
        "pack": pack,
    }


def counterfactual(
    store: MemoryStore,
    query: str,
    judgment_id: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """What changes if one judgment item is absent?"""
    baseline = simulate(store, query, **kwargs)
    # temporarily filter the item from pack by re-simulating with metadata note
    pack = baseline["pack"]
    filtered = {
        k: [i for i in (v or []) if not (isinstance(i, dict) and i.get("id") == judgment_id)]
        if k in ("hard_constraints", "principles", "heuristics", "preferences",
                 "beliefs", "values", "applicable_judgments")
        else v
        for k, v in pack.items()
    }
    # lightweight re-score without the item
    options = list(baseline["scores"].keys()) or _guess_options(query)
    scores = {opt: 0.0 for opt in options}
    blocked = []
    for item in filtered.get("hard_constraints") or []:
        for opt in options:
            if _constraint_blocks(item["statement"], opt, query):
                blocked.append(opt)
    viable = [o for o in options if o not in blocked]
    for item in (filtered.get("principles") or []) + (filtered.get("heuristics") or []) + (
        filtered.get("preferences") or []
    ):
        weight = float(item.get("strength", 0.5)) * float(item.get("confidence", 0.5))
        for opt in viable:
            scores[opt] += _lean_score(item["statement"], opt, query) * weight
    ranking = sorted(viable, key=lambda o: scores.get(o, 0.0), reverse=True)
    return {
        "without_judgment_id": judgment_id,
        "baseline_recommendation": baseline["recommendation"],
        "counterfactual_recommendation": ranking[0] if ranking else None,
        "baseline_scores": baseline["scores"],
        "counterfactual_scores": scores,
        "changed": baseline["recommendation"] != (ranking[0] if ranking else None),
    }


def _guess_options(query: str) -> list[str]:
    # crude extraction of Proper nouns / known tech tokens
    known = ["PostgreSQL", "Neo4j", "SQLite", "MongoDB", "Kubernetes", "Docker",
             "FastAPI", "microservices", "modular monolith"]
    found = [k for k in known if re.search(re.escape(k), query, re.I)]
    return found or ["option_a", "option_b"]


def _constraint_blocks(statement: str, option: str, query: str) -> bool:
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


def _lean_score(statement: str, option: str, query: str) -> float:
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


def _render_markdown(query, pack, options, scores, blocked, ranking, recommendation, reasons) -> str:
    lines = [
        f"# Judgment simulation",
        "",
        f"**Query:** {query}",
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
    lines += [
        "",
        "## Judgment-influenced result",
        "",
        f"**{recommendation or 'no viable option'}**",
        "",
        f"Snapshot: `{pack.get('snapshot_id')}`",
    ]
    return "\n".join(lines)
