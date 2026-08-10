"""Stance as public name for Judgment (alias layer)."""

from __future__ import annotations

from typing import Any

from twin.cognize.models import Stance, StanceStatus
from twin.cognize.stance_engine.models import JudgmentItem, JudgmentStability, JudgmentStatus


def judgment_to_stance(item: JudgmentItem, *, vault_id: str = "") -> Stance:
    status_map = {
        JudgmentStatus.candidate: StanceStatus.pending,
        JudgmentStatus.active: StanceStatus.active,
        JudgmentStatus.rejected: StanceStatus.deprecated,
        JudgmentStatus.superseded: StanceStatus.deprecated,
        JudgmentStatus.deprecated: StanceStatus.deprecated,
    }
    st = status_map.get(item.status, StanceStatus.pending)
    return Stance(
        id=item.id,
        vault_id=vault_id,
        kind=item.kind.value if hasattr(item.kind, "value") else str(item.kind),
        statement=item.statement,
        status=st,
        strength=float(item.strength or 0.5),
        domain=item.domain or "",
        persona=item.persona or "",
        constitutional=item.stability is JudgmentStability.constitutional,
        created_at=item.created_at or "",
        updated_at=item.updated_at or "",
        metadata={"judgment_id": item.id},
    )


def list_stances(store: Any, *, vault_id: str = "") -> list[Stance]:
    if not hasattr(store, "list_judgment_items"):
        return []
    items = store.list_judgment_items()
    return [judgment_to_stance(i, vault_id=vault_id) for i in items]
