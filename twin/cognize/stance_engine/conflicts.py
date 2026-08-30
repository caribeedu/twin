"""Detect judgment↔judgment and judgment↔behavior conflicts.

Detection never mutates judgment lifecycle status. Conflicts live only in
``judgment_conflicts`` until a human resolves them via an explicit operation.
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional

from twin import ids
from twin.clock import now_iso
from twin.store.store.base import TwinStore
from .models import ConflictStatus, ConflictType, JudgmentConflict
from .versions import active_items


_OPPOSING = [
    (re.compile(r"simpli|local.?first|reversib", re.I),
     re.compile(r"microservice|distributed|premature.?optim|neo4j", re.I)),
    (re.compile(r"direct|direto|clareza", re.I),
     re.compile(r"diplomati|soft.?pedal|hedge", re.I)),
]

ANALYZER = "conflict-v1"


def detect_judgment_conflicts(store: TwinStore) -> list[JudgmentConflict]:
    items = active_items(store)
    found: list[JudgmentConflict] = []
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if a.domain != b.domain and a.domain != "general" and b.domain != "general":
                continue
            for left, right in _OPPOSING:
                if (left.search(a.statement) and right.search(b.statement)) or (
                    right.search(a.statement) and left.search(b.statement)
                ):
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
                        analyzer_version=ANALYZER,
                        evidence_fingerprint=f"{a.id}:{b.id}:{ctype.value}",
                    )
                    store.insert_judgment_conflict(conf)
                    found.append(conf)
    return found


def detect_behavior_conflicts(
    store: TwinStore,
    *,
    domain: str = "technical",
    min_exceptions: int = 3,
) -> list[JudgmentConflict]:
    """Open review conflicts when decisions repeatedly oppose active judgment.

    Does **not** change judgment status — only records a conflict for humans.
    """
    items = [
        i for i in active_items(store)
        if i.domain == domain and i.kind.value in ("principle", "heuristic", "constraint")
    ]
    decisions = store.list_claims(type_="decision", status="confirmed", limit=1000)
    decisions = [m for m in decisions if m.domain == domain]
    found: list[JudgmentConflict] = []

    for item in items:
        opposing_mems = []
        for m in decisions:
            text = f"{m.title} {m.summary}"
            if item.kind.value == "constraint":
                continue
            if re.search(r"simpli|reversib|local", item.statement, re.I) and re.search(
                r"microservice|kubernetes|neo4j|distributed", text, re.I
            ):
                if (m.payload or {}).get("judgment_influenced"):
                    continue
                opposing_mems.append(m.id)
        if len(opposing_mems) < min_exceptions:
            continue
        fp = hashlib.sha256(",".join(sorted(opposing_mems)).encode()).hexdigest()[:16]
        conf = JudgmentConflict(
            id=ids.judgment_conflict_id(),
            judgment_id=item.id,
            claim_ids=opposing_mems,
            type=ConflictType.drift,
            confidence=min(0.9, 0.5 + 0.05 * len(opposing_mems)),
            status=ConflictStatus.open,
            suggested_resolution="add_exception or supersede after review",
            reason=(
                f"{len(opposing_mems)} confirmed decisions may contradict "
                f"active judgment «{item.statement}»"
            ),
            created_at=now_iso(),
            analyzer_version=ANALYZER,
            evidence_fingerprint=fp,
        )
        store.insert_judgment_conflict(conf)
        found.append(conf)
        # IMPORTANT: do not flip item.status — judgment stays active until human acts
    return found


def resolve_conflict(
    store: TwinStore,
    conflict_id: str,
    *,
    resolution: str,
    actor: str = "user",
    dismiss: bool = False,
    resolution_operation_id: Optional[str] = None,
    proposal_id: Optional[str] = None,
) -> JudgmentConflict:
    conf = store.get_judgment_conflict(conflict_id)
    if conf is None:
        raise ValueError(f"conflict {conflict_id} not found")
    if dismiss:
        status = ConflictStatus.dismissed.value
    else:
        if not resolution_operation_id and not proposal_id and resolution not in (
            "dismiss", "dismissed", "keep_both",
        ):
            raise ValueError(
                "resolve via operation requires resolution_operation_id or proposal_id; "
                "or pass dismiss=True / resolution='dismiss'"
            )
        status = ConflictStatus.resolved.value
        if resolution in ("dismiss", "dismissed"):
            status = ConflictStatus.dismissed.value
    store.update_judgment_conflict(
        conflict_id,
        status=status,
        resolved_at=now_iso(),
        suggested_resolution=resolution,
        resolution_operation_id=resolution_operation_id,
        proposal_id=proposal_id,
        metadata={**(conf.metadata or {}), "resolved_by": actor},
    )
    return store.get_judgment_conflict(conflict_id)  # type: ignore[return-value]
