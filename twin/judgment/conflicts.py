"""Detect judgment↔judgment and judgment↔behavior conflicts."""

from __future__ import annotations

import re
from typing import Optional

from .. import ids
from ..clock import now_iso
from ..memory.store.base import MemoryStore
from .models import (
    ConflictStatus,
    ConflictType,
    JudgmentConflict,
    JudgmentItem,
    JudgmentStatus,
)
from .versions import active_items


_OPPOSING = [
    (re.compile(r"simpli|local.?first|reversib", re.I),
     re.compile(r"microservice|distributed|premature.?optim|neo4j", re.I)),
    (re.compile(r"direct|direto|clareza", re.I),
     re.compile(r"diplomati|soft.?pedal|hedge", re.I)),
]


def detect_judgment_conflicts(store: MemoryStore) -> list[JudgmentConflict]:
    items = active_items(store)
    found: list[JudgmentConflict] = []
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if a.domain != b.domain and a.domain != "general" and b.domain != "general":
                continue
            # same scope clash on opposing language
            for left, right in _OPPOSING:
                if (left.search(a.statement) and right.search(b.statement)) or (
                    right.search(a.statement) and left.search(b.statement)
                ):
                    # if scopes differ enough, classify as scope_mismatch opportunity
                    scope_diff = (
                        set(a.scope.project_stages or []) != set(b.scope.project_stages or [])
                        or set(a.scope.task_profiles or []) != set(b.scope.task_profiles or [])
                    )
                    ctype = (
                        ConflictType.scope_mismatch if scope_diff
                        else ConflictType.judgment_vs_judgment
                    )
                    conf = JudgmentConflict(
                        id=ids.judgment_conflict_id(),
                        judgment_id=a.id,
                        other_judgment_id=b.id,
                        type=ctype,
                        confidence=0.7,
                        status=ConflictStatus.open,
                        suggested_resolution=(
                            "narrow scope" if scope_diff else "add precedence or exception"
                        ),
                        reason=f"Possible tension between «{a.statement}» and «{b.statement}»",
                        created_at=now_iso(),
                    )
                    store.insert_judgment_conflict(conf)
                    found.append(conf)
    return found


def detect_behavior_conflicts(
    store: MemoryStore,
    *,
    domain: str = "technical",
    min_exceptions: int = 3,
) -> list[JudgmentConflict]:
    """Open conflicts when confirmed decisions repeatedly oppose an active principle/heuristic."""
    items = [
        i for i in active_items(store)
        if i.domain == domain and i.kind.value in ("principle", "heuristic", "constraint")
    ]
    decisions = store.list_memories(type_="decision", status="confirmed", limit=1000)
    decisions = [m for m in decisions if m.domain == domain]
    found: list[JudgmentConflict] = []

    for item in items:
        # crude opposition: decisions mentioning reverse trade-off
        opposing_mems = []
        for m in decisions:
            text = f"{m.title} {m.summary}"
            if item.kind.value == "constraint":
                continue  # constraints vs behavior need explicit violation signals
            if re.search(r"simpli|reversib|local", item.statement, re.I) and re.search(
                r"microservice|kubernetes|neo4j|distributed", text, re.I
            ):
                # skip twin-influenced as independent evidence of drift
                if (m.payload or {}).get("judgment_influenced"):
                    continue
                opposing_mems.append(m.id)
        if len(opposing_mems) < min_exceptions:
            continue
        # enough opposition → drift proposal signal
        conf = JudgmentConflict(
            id=ids.judgment_conflict_id(),
            judgment_id=item.id,
            memory_ids=opposing_mems,
            type=ConflictType.drift,
            confidence=min(0.9, 0.5 + 0.05 * len(opposing_mems)),
            status=ConflictStatus.open,
            suggested_resolution="add_exception or supersede after review",
            reason=(
                f"{len(opposing_mems)} confirmed decisions may contradict "
                f"active judgment «{item.statement}»"
            ),
            created_at=now_iso(),
        )
        store.insert_judgment_conflict(conf)
        found.append(conf)
        store.update_judgment_item(
            item.id, status=JudgmentStatus.conflicted.value, updated_at=now_iso(),
        )
    return found


def resolve_conflict(
    store: MemoryStore,
    conflict_id: str,
    *,
    resolution: str,
    actor: str = "user",
) -> JudgmentConflict:
    conf = store.get_judgment_conflict(conflict_id)
    if conf is None:
        raise ValueError(f"conflict {conflict_id} not found")
    store.update_judgment_conflict(
        conflict_id,
        status=ConflictStatus.resolved.value,
        resolved_at=now_iso(),
        suggested_resolution=resolution,
        metadata={**(conf.metadata or {}), "resolved_by": actor},
    )
    # clear conflicted flag if no other open conflicts for that judgment
    open_for = [
        c for c in store.list_judgment_conflicts(status="open")
        if c.judgment_id == conf.judgment_id
    ]
    if not open_for:
        item = store.get_judgment_item(conf.judgment_id)
        if item and item.status == JudgmentStatus.conflicted:
            store.update_judgment_item(
                conf.judgment_id, status=JudgmentStatus.active.value, updated_at=now_iso(),
            )
    return store.get_judgment_conflict(conflict_id)  # type: ignore[return-value]
