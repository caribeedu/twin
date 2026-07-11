"""Explicit memory lifecycle transitions (README §27.9).

Opinions change and decisions get replaced — the graph must say so
explicitly instead of letting stale memories compete with current ones.

- ``supersede``: the new memory replaces the old one. The old memory is
  deprecated, its temporal validity is closed at the point the new one
  starts, and a ``supersedes`` edge records the succession.
- ``contradict``: two memories conflict and a human must arbitrate. Both
  are flagged for review and a ``contradicts`` edge links them; the older
  one is marked ``contradicted`` so the firewall stops serving it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import ids
from ..clock import now_iso
from .models import MemoryStatus, Relation
from .store.base import MemoryStore


@dataclass
class LifecycleResult:
    action: str
    subject_id: str
    object_id: str
    relation_id: str


def supersede(store: MemoryStore, new_id: str, old_id: str) -> LifecycleResult:
    """``new_id`` supersedes ``old_id``."""
    new_mem = store.get_memory(new_id)
    old_mem = store.get_memory(old_id)
    if new_mem is None or old_mem is None:
        raise ValueError("both memories must exist")
    if new_id == old_id:
        raise ValueError("a memory cannot supersede itself")
    cutoff = new_mem.valid_from or now_iso()[:10]
    relation_id = store.insert_relation(Relation(
        id=ids.relation_id(),
        subject_id=new_id, predicate="supersedes", object_id=old_id,
        memory_id=new_id, valid_from=cutoff,
    ))
    store.update_memory(
        old_id,
        status=MemoryStatus.deprecated.value,
        valid_until=cutoff,
        needs_review=False,
        review_reason=None,
    )
    return LifecycleResult("supersede", new_id, old_id, relation_id)


def contradict(store: MemoryStore, memory_id: str, contradicted_id: str) -> LifecycleResult:
    """``memory_id`` contradicts ``contradicted_id`` — both go to review."""
    mem = store.get_memory(memory_id)
    other = store.get_memory(contradicted_id)
    if mem is None or other is None:
        raise ValueError("both memories must exist")
    if memory_id == contradicted_id:
        raise ValueError("a memory cannot contradict itself")
    relation_id = store.insert_relation(Relation(
        id=ids.relation_id(),
        subject_id=memory_id, predicate="contradicts", object_id=contradicted_id,
        memory_id=memory_id,
    ))
    store.update_memory(
        contradicted_id,
        status=MemoryStatus.contradicted.value,
        needs_review=True,
        review_reason=f"contradicted by {memory_id}",
    )
    store.update_memory(
        memory_id,
        needs_review=True,
        review_reason=f"contradicts {contradicted_id} — confirm which holds",
    )
    return LifecycleResult("contradict", memory_id, contradicted_id, relation_id)
