"""Apply scoped judgment with explicit precedence — constraints first."""

from __future__ import annotations

from typing import Any, Optional

from ..memory.store.base import MemoryStore
from .models import (
    KIND_PRECEDENCE,
    AppliedJudgmentEffect,
    JudgmentItem,
    JudgmentKind,
    JudgmentStatus,
    JudgmentTrace,
)
from .. import ids
from ..clock import now_iso
from .versions import active_items, make_snapshot


def _scope_matches(
    item: JudgmentItem,
    *,
    domain: str,
    persona: str,
    task_profile: str,
    project_id: Optional[str],
) -> bool:
    scope = item.scope
    if scope.domains:
        if domain not in scope.domains:
            return False
    elif item.domain not in ("general", domain):
        return False
    if scope.personas and persona not in scope.personas:
        return False
    if scope.task_profiles and task_profile not in scope.task_profiles:
        return False
    if scope.projects and project_id and project_id not in scope.projects:
        return False
    return True


def select_applicable(
    store: MemoryStore,
    *,
    domain: str = "technical",
    persona: str = "individual",
    task_profile: str = "general",
    project_id: Optional[str] = None,
    as_of: Optional[str] = None,
) -> list[JudgmentItem]:
    items = active_items(store)
    applicable: list[JudgmentItem] = []
    for item in items:
        if as_of:
            if item.valid_from and item.valid_from > as_of:
                continue
            if item.valid_until and item.valid_until < as_of:
                continue
        if not _scope_matches(
            item, domain=domain, persona=persona,
            task_profile=task_profile, project_id=project_id,
        ):
            continue
        applicable.append(item)
    applicable.sort(key=lambda i: (KIND_PRECEDENCE.get(i.kind, 99), -i.strength))
    return applicable


def apply_exceptions(
    item: JudgmentItem,
    *,
    context_text: str = "",
) -> tuple[JudgmentItem, list[str]]:
    """Return a copy with strength adjusted by matching exceptions."""
    used: list[str] = []
    strength = item.strength
    disabled = False
    for exc in item.exceptions:
        cond = (exc.condition or "").lower()
        if cond and cond not in context_text.lower() and not any(
            tok in context_text.lower() for tok in cond.split() if len(tok) > 3
        ):
            # soft match: if condition keywords appear
            continue
        if not cond:
            continue
        used.append(exc.id)
        if exc.effect.value == "disable":
            disabled = True
        elif exc.effect.value == "reduce_strength":
            strength = min(strength, float(exc.value))
    if disabled:
        strength = 0.0
    clone = item.model_copy(deep=True)
    clone.strength = strength
    return clone, used


def applicable_pack(
    store: MemoryStore,
    *,
    domain: str = "technical",
    persona: str = "individual",
    task_profile: str = "general",
    project_id: Optional[str] = None,
    query: str = "",
) -> dict[str, Any]:
    raw = select_applicable(
        store, domain=domain, persona=persona,
        task_profile=task_profile, project_id=project_id,
    )
    applied: list[JudgmentItem] = []
    exceptions_used: list[str] = []
    for item in raw:
        adj, used = apply_exceptions(item, context_text=query)
        if adj.strength <= 0 and item.kind != JudgmentKind.constraint:
            exceptions_used.extend(used)
            continue
        exceptions_used.extend(used)
        applied.append(adj)

    constraints = [i for i in applied if i.kind == JudgmentKind.constraint]
    principles = [i for i in applied if i.kind == JudgmentKind.principle]
    heuristics = [i for i in applied if i.kind == JudgmentKind.heuristic]
    preferences = [i for i in applied if i.kind == JudgmentKind.preference]
    beliefs = [i for i in applied if i.kind == JudgmentKind.belief]
    values = [i for i in applied if i.kind == JudgmentKind.value]

    snapshot = make_snapshot(
        store, applied,
        target_domain=domain, persona=persona,
        task_profile=task_profile, project_id=project_id,
    )
    return {
        "applicable_judgments": [i.model_dump(mode="json") for i in applied],
        "hard_constraints": [i.model_dump(mode="json") for i in constraints],
        "principles": [i.model_dump(mode="json") for i in principles],
        "heuristics": [i.model_dump(mode="json") for i in heuristics],
        "preferences": [i.model_dump(mode="json") for i in preferences],
        "beliefs": [i.model_dump(mode="json") for i in beliefs],
        "values": [i.model_dump(mode="json") for i in values],
        "exceptions_used": exceptions_used,
        "snapshot_id": snapshot.id,
        "snapshot": snapshot.model_dump(mode="json"),
    }


def render_applicable(pack: dict[str, Any]) -> str:
    """Structured context-pack judgment section."""
    lines = ["## Judgment (applicable)"]

    def section(title: str, key: str) -> None:
        items = pack.get(key) or []
        if not items:
            return
        lines.append(f"### {title}")
        for it in items:
            stmt = it.get("statement", "")
            lines.append(f"- {stmt}")
        lines.append("")

    section("Hard constraints", "hard_constraints")
    section("Principles", "principles")
    section("Heuristics", "heuristics")
    section("Preferences", "preferences")
    section("Beliefs", "beliefs")
    if pack.get("values"):
        lines.append("### Values (explanatory — not direct commands)")
        for it in pack["values"]:
            lines.append(f"- {it.get('statement', '')}")
        lines.append("")

    meta = pack.get("snapshot") or {}
    lines.append("### Judgment metadata")
    lines.append(f"- Snapshot: {pack.get('snapshot_id', '')}")
    lines.append(f"- Domain: {meta.get('target_domain', '')}")
    lines.append(f"- Persona: {meta.get('persona', '')}")
    lines.append(f"- Task profile: {meta.get('task_profile', '')}")
    return "\n".join(lines).strip()


def record_trace(
    store: MemoryStore,
    *,
    query: str,
    snapshot_id: str,
    applied: list[AppliedJudgmentEffect],
    blocked_options: Optional[list[str]] = None,
    exceptions_used: Optional[list[str]] = None,
    result: Optional[dict[str, Any]] = None,
) -> JudgmentTrace:
    trace = JudgmentTrace(
        id=ids.judgment_trace_id(),
        query=query,
        snapshot_id=snapshot_id,
        applied_items=applied,
        blocked_options=blocked_options or [],
        exceptions_used=exceptions_used or [],
        result=result or {},
        created_at=now_iso(),
    )
    store.insert_judgment_trace(trace)
    return trace
