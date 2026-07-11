"""MemoryStore — the storage contract every backend implements.

Backends: ``PostgresStore`` (primary; PostgreSQL + pgvector, scales beyond a
single file and supports server-side vector search) and ``SqliteStore``
(zero-config for dev/tests). Everything above this interface — cognition,
judgment, interfaces — is backend-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Optional

from ...clock import now_iso  # re-export for backends
from ...sensory.percept import Percept
from ..embeddings import cosine, from_blob
from ..models import Entity, Evidence, MemoryItem, MemoryStatus, Relation

__all__ = ["MemoryStore", "now_iso"]


class MemoryStore(ABC):
    # -- percepts ---------------------------------------------------------

    @abstractmethod
    def insert_percept(self, percept: Percept) -> Optional[str]:
        """Insert a percept; returns its id, or None if the same content was
        already stored (dedup by content hash)."""

    @abstractmethod
    def get_percept(self, percept_id: str) -> Optional[Percept]: ...

    @abstractmethod
    def list_percepts(self) -> list[Percept]: ...

    @abstractmethod
    def unprocessed_percepts(self) -> list[Percept]:
        """Percepts no memory/evidence has been derived from yet."""

    # -- memories ----------------------------------------------------------

    @abstractmethod
    def insert_memory(self, mem: MemoryItem) -> str: ...

    @abstractmethod
    def get_memory(self, memory_id: str) -> Optional[MemoryItem]: ...

    @abstractmethod
    def list_memories(
        self,
        status: Optional[str] = None,
        domain: Optional[str] = None,
        type_: Optional[str] = None,
        needs_review: Optional[bool] = None,
        limit: int = 200,
    ) -> list[MemoryItem]: ...

    @abstractmethod
    def update_memory(self, memory_id: str, **fields) -> None: ...

    def set_status(self, memory_id: str, status: MemoryStatus, clear_review: bool = True) -> None:
        self.update_memory(
            memory_id,
            status=status.value,
            **({"needs_review": False, "review_reason": None} if clear_review else {}),
        )

    # -- evidence ----------------------------------------------------------

    @abstractmethod
    def insert_evidence(self, ev: Evidence) -> str: ...

    @abstractmethod
    def get_evidence(self, memory_id: str) -> list[Evidence]: ...

    # -- entities & relations ----------------------------------------------

    @abstractmethod
    def upsert_entity(self, name: str, entity_type: str = "generic") -> Entity: ...

    @abstractmethod
    def get_entity_by_name(self, name: str) -> Optional[Entity]: ...

    @abstractmethod
    def list_entities(self) -> list[Entity]: ...

    @abstractmethod
    def insert_relation(self, rel: Relation) -> str: ...

    @abstractmethod
    def relations_for(self, node_id: str) -> list[Relation]: ...

    @abstractmethod
    def memories_for_entity(self, entity_id: str) -> list[MemoryItem]: ...

    # -- embeddings ----------------------------------------------------------

    @abstractmethod
    def store_embedding(self, ref_id: str, ref_type: str, model: str,
                        vector: list[float]) -> None: ...

    @abstractmethod
    def iter_embeddings(self, ref_type: str, model: str) -> Iterable[tuple[str, bytes]]:
        """Yield (ref_id, packed_vector) for embeddings of the given model."""

    def similar(self, query_vec: list[float], ref_type: str, model: str,
                min_sim: float = 0.05) -> dict[str, float]:
        """ref_id → cosine similarity. Default is client-side; backends with
        native vector search (pgvector) override this."""
        scores: dict[str, float] = {}
        for ref_id, blob in self.iter_embeddings(ref_type, model):
            sim = cosine(query_vec, from_blob(blob))
            if sim >= min_sim:
                scores[ref_id] = sim
        return scores

    # -- full-text search ----------------------------------------------------

    @abstractmethod
    def fts_search(self, query: str, limit: int = 50) -> dict[str, float]:
        """memory_id → relevance score (higher = better)."""

    # -- firewall audit log ----------------------------------------------------

    @abstractmethod
    def log_firewall(self, memory_id: str, target_domain: str, rule: str, action: str) -> None: ...

    # -- metrics ------------------------------------------------------------------

    @abstractmethod
    def count_evidence(self) -> int: ...

    @abstractmethod
    def count_firewall_blocks(self) -> int: ...

    @abstractmethod
    def close(self) -> None: ...

    @staticmethod
    def sanitize_fts_terms(query: str) -> list[str]:
        return [t for t in "".join(c if c.isalnum() else " " for c in query).split() if len(t) > 1]
