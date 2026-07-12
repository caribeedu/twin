"""Apply scoped judgment with explicit precedence — constraints first."""

from __future__ import annotations

from typing import Any, Optional

from .. import ids
from ..clock import now_iso
from ..memory.store.base import MemoryStore
from .models import (
    KIND_PRECEDENCE,
    AppliedJudgmentEffect,
    AppliedRevisionRef,
    ExceptionEffect,
    JudgmentContext,
    JudgmentItem,
    JudgmentKind,
    JudgmentTrace,
)
from .versions import active_items, make_snapshot


def _dim_matches(required: list[str], actual: Optional[str], *, required_when_set: bool) -> bool:
    if not required:
        return True
    if required_when_set and not actual:
        return False
    return actual in required if actual else False


def scope_matches(item: JudgmentItem, ctx: JudgmentContext) -> bool:
    scope = item.scope
    # domain
    if scope.domains:
        if ctx.domain not in scope.domains:
            return False
    elif item.domain not in ("general", ctx.domain):
        return False
    # persona
    if scope.personas:
        if ctx.persona not in scope.personas:
            return False
    elif item.persona not in ("general", ctx.persona):
        return False
    if scope.task_profiles and ctx.task_profile not in scope.task_profiles:
        return False
    if scope.projects:
        if not ctx.project_id or ctx.project_id not in scope.projects:
            return False
    if scope.audiences:
        if not ctx.audience or ctx.audience not in scope.audiences:
            return False
    if scope.clients:
        if not ctx.client or ctx.client not in scope.clients:
            return False
    if scope.project_stages:
        if not ctx.project_stage or ctx.project_stage not in scope.project_stages:
            return False
    if scope.conditions:
        # all declared conditions must appear in context.conditions
        if not set(scope.conditions).issubset(set(ctx.conditions or [])):
            return False
    return True


def select_applicable(
    store: MemoryStore,
    ctx: JudgmentContext,
    *,
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
        if not scope_matches(item, ctx):
            continue
        applicable.append(item)
    applicable.sort(key=lambda i: (KIND_PRECEDENCE.get(i.kind, 99), -i.strength))
    return applicable


def apply_exceptions(
    item: JudgmentItem,
    ctx: JudgmentContext,
) -> dict[str, Any]:
    """Apply matching exceptions. Returns effective state flags."""
    used: list[str] = []
    strength = item.strength
    disabled = False
    requires_confirmation = False
    replacement_revision_id: Optional[str] = None

    for exc in item.exceptions:
        if not _exception_matches(exc, ctx):
            continue
        used.append(exc.id)
        effect = exc.effect.value if hasattr(exc.effect, "value") else exc.effect
        if effect == ExceptionEffect.disable.value:
            disabled = True
        elif effect == ExceptionEffect.reduce_strength.value:
            strength = min(strength, float(exc.value))
        elif effect == ExceptionEffect.replace_with.value:
            replacement_revision_id = exc.replace_with_revision_id
            if not replacement_revision_id:
                requires_confirmation = True
        elif effect == ExceptionEffect.require_confirmation.value:
            requires_confirmation = True

    clone = item.model_copy(deep=True)
    clone.strength = 0.0 if disabled else strength
    return {
        "item": clone,
        "disabled": disabled,
        "requires_confirmation": requires_confirmation,
        "replacement_revision_id": replacement_revision_id,
        "exception_ids": used,
        "effective_strength": 0.0 if disabled else strength,
    }


def _exception_matches(exc, ctx: JudgmentContext) -> bool:
    match = exc.match or {}
    if match:
        for key, expected in match.items():
            actual = getattr(ctx, key, None)
            if isinstance(expected, list):
                if actual not in expected:
                    return False
            elif actual != expected and expected not in (ctx.conditions or []):
                return False
        return True
    cond = (exc.condition or "").strip().lower()
    if not cond:
        return False
    tokens = [t for t in cond.replace(",", " ").split() if len(t) > 3]
    if len(tokens) < 2:
        return False
    hay = " ".join([
        ctx.query.lower(),
        ctx.audience or "",
        ctx.client or "",
        ctx.project_stage or "",
        " ".join(ctx.conditions or []),
    ])
    hits = sum(1 for t in tokens if t in hay)
    return hits >= max(2, (len(tokens) + 1) // 2)


def applicable_pack(
    store: MemoryStore,
    ctx: Optional[JudgmentContext] = None,
    *,
    domain: str = "technical",
    persona: str = "individual",
    task_profile: str = "general",
    project_id: Optional[str] = None,
    audience: Optional[str] = None,
    client: Optional[str] = None,
    project_stage: Optional[str] = None,
    query: str = "",
    persist_snapshot: bool = True,
) -> dict[str, Any]:
    ctx = ctx or JudgmentContext(
        domain=domain, persona=persona, task_profile=task_profile,
        project_id=project_id, audience=audience, client=client,
        project_stage=project_stage, query=query,
    )
    raw = select_applicable(store, ctx)
    applied_items: list[JudgmentItem] = []
    applied_refs: list[AppliedRevisionRef] = []
    exceptions_used: list[str] = []
    requires_confirmation = False
    confirmation_reasons: list[str] = []

    for item in raw:
        result = apply_exceptions(item, ctx)
        exceptions_used.extend(result["exception_ids"])
        if result["requires_confirmation"]:
            requires_confirmation = True
            confirmation_reasons.append(item.statement)
        if result["disabled"]:
            # disabled items — including constraints — are excluded
            applied_refs.append(AppliedRevisionRef(
                judgment_id=item.id,
                revision_id=item.current_revision_id or "",
                effective_strength=0.0,
                disabled=True,
                requires_confirmation=result["requires_confirmation"],
                exception_ids=result["exception_ids"],
                payload=item.model_dump(mode="json"),
            ))
            continue
        if result["replacement_revision_id"]:
            repl = store.get_judgment_revision(result["replacement_revision_id"])
            if repl:
                from .revisions import item_from_revision
                item = item_from_revision(repl)
        adj: JudgmentItem = result["item"]
        applied_items.append(adj)
        applied_refs.append(AppliedRevisionRef(
            judgment_id=adj.id,
            revision_id=adj.current_revision_id or item.current_revision_id or "",
            effective_strength=float(result["effective_strength"]),
            disabled=False,
            requires_confirmation=result["requires_confirmation"],
            exception_ids=result["exception_ids"],
            replacement_revision_id=result["replacement_revision_id"],
            payload=adj.model_dump(mode="json"),
        ))

    def _section(kind: JudgmentKind) -> list[dict]:
        return [i.model_dump(mode="json") for i in applied_items if i.kind == kind]

    snapshot = make_snapshot(
        store, applied_refs,
        context=ctx.model_dump(),
        persist=persist_snapshot,
    )
    return {
        "applicable_judgments": [i.model_dump(mode="json") for i in applied_items],
        "hard_constraints": _section(JudgmentKind.constraint),
        "principles": _section(JudgmentKind.principle),
        "heuristics": _section(JudgmentKind.heuristic),
        "preferences": _section(JudgmentKind.preference),
        "beliefs": _section(JudgmentKind.belief),
        "values": _section(JudgmentKind.value),
        "exceptions_used": exceptions_used,
        "requires_confirmation": requires_confirmation,
        "confirmation_reasons": confirmation_reasons,
        "snapshot_id": snapshot.id if persist_snapshot else None,
        "snapshot": snapshot.model_dump(mode="json"),
        "applied_revisions": [a.model_dump(mode="json") for a in applied_refs],
        "context": ctx.model_dump(),
    }


def render_applicable(pack: dict[str, Any]) -> str:
    lines = ["## Judgment (applicable)"]

    def section(title: str, key: str) -> None:
        items = pack.get(key) or []
        if not items:
            return
        lines.append(f"### {title}")
        for it in items:
            lines.append(f"- {it.get('statement', '')}")
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
    if pack.get("requires_confirmation"):
        lines.append("### Requires confirmation")
        for reason in pack.get("confirmation_reasons") or []:
            lines.append(f"- {reason}")
        lines.append("")

    meta = pack.get("snapshot") or {}
    lines.append("### Judgment metadata")
    lines.append(f"- Snapshot: {pack.get('snapshot_id') or '(ephemeral)'}")
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
    persist: bool = True,
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
    if persist:
        store.insert_judgment_trace(trace)
    return trace
