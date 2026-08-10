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
from twin.sense.sensory.percept import Percept
from ..embeddings import cosine, from_blob
from ..models import (
    CognitiveSession, DetectionSignal, Entity, Evidence, MemoryItem, MemoryStatus,
    PerceptInterpretation, Project, Relation,
)

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

    # -- interpretation state  --------------------------------------

    @abstractmethod
    def record_interpretation(self, state: PerceptInterpretation) -> None:
        """Upsert the interpretation record for a Percept (keyed by
        percept_id). Increments nothing itself — callers set ``attempts``."""

    @abstractmethod
    def get_interpretation(self, percept_id: str) -> Optional[PerceptInterpretation]: ...

    @abstractmethod
    def list_interpretations(
        self, status: Optional[str] = None, limit: int = 200,
    ) -> list[PerceptInterpretation]: ...

    @abstractmethod
    def percepts_pending_interpretation(
        self, *, max_attempts: int, limit: int = 500,
    ) -> list[Percept]:
        """Percepts that still need interpreting: never interpreted, or left
        non-terminal and due for retry. A service outage (``deferred``) is
        always eligible and never consumes the attempt budget; a
        reachable-but-failing interpreter (``error``) is bounded by
        ``max_attempts`` and ``next_attempt_at`` backoff. Terminal and
        settled states (interpreted/empty/quarantined/heuristic_detection) are
        excluded."""

    # -- detection signals  --------------------------

    @abstractmethod
    def insert_detection_signal(self, signal: DetectionSignal) -> str:
        """Persist a conservative lexical detection hint (never a memory)."""

    @abstractmethod
    def list_detection_signals(
        self, percept_id: Optional[str] = None, limit: int = 500,
    ) -> list[DetectionSignal]: ...

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
        project_id: Optional[str] = None,
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

    # -- projects -----------------------------------------------------------------

    @abstractmethod
    def insert_project(self, project: Project) -> str: ...

    @abstractmethod
    def update_project(self, project: Project) -> None: ...

    @abstractmethod
    def get_project(self, project_id: str) -> Optional[Project]: ...

    @abstractmethod
    def list_projects(self, status: Optional[str] = None) -> list[Project]: ...

    def find_project(self, signal: str) -> Optional[Project]:
        """Resolve a project from a name, alias or repository signal
        (e.g. the basename of the current working directory)."""
        needle = signal.strip().lower()
        if not needle:
            return None
        for project in self.list_projects():
            if project.name.lower() == needle:
                return project
            if any(a.lower() == needle for a in project.aliases):
                return project
            for repo in project.repos:
                repo_l = repo.lower()
                if repo_l == needle or repo_l.rstrip("/").split("/")[-1] == needle:
                    return project
        return None

    # -- cognitive sessions ----------------------------------------------------------
    #
    # Artifacts and feedback are append-only rows in their own tables, never
    # a JSON array rewritten from an in-memory copy — concurrent observers
    # cannot lose each other's writes. update_session only writes the
    # session's scalar fields.

    @abstractmethod
    def insert_session(self, session: CognitiveSession) -> str: ...

    @abstractmethod
    def update_session(self, session: CognitiveSession) -> None:
        """Persist the session's scalar fields (status, ended_at,
        consolidation state, created/supplied ids…). Does NOT write
        artifacts or feedback — use the append methods for those."""

    @abstractmethod
    def get_session(self, session_id: str) -> Optional[CognitiveSession]: ...

    @abstractmethod
    def list_sessions(self, status: Optional[str] = None,
                      project_id: Optional[str] = None,
                      limit: int = 200) -> list[CognitiveSession]: ...

    @abstractmethod
    def append_session_artifact(self, session_id: str, artifact: dict) -> None:
        """Atomically append one artifact to an ACTIVE session and bump
        last_activity_at. Raises ValueError if the session does not exist
        or is not active."""

    @abstractmethod
    def append_session_feedback(self, session_id: str, feedback: dict) -> None:
        """Atomically append one feedback entry (allowed on any existing
        session — completed sessions still receive verdicts) and bump
        last_activity_at. Raises ValueError if the session does not exist."""

    @abstractmethod
    def transition_session(self, session_id: str, from_status: str,
                           to_status: str, ended_at: Optional[str] = None) -> bool:
        """Compare-and-set status change. Returns False when the session was
        not in ``from_status`` (someone else transitioned it first)."""

    # -- metrics ------------------------------------------------------------------

    @abstractmethod
    def count_evidence(self) -> int: ...

    @abstractmethod
    def count_firewall_blocks(self) -> int: ...

    @abstractmethod
    def close(self) -> None: ...

    # -- transactions  ------------------------------------

    def transaction(self):
        """Context manager: all writes in the block commit together or roll back.

        Nested calls reuse the outer transaction. Stores that auto-commit each
        write must suppress mid-block commits while the depth is > 0.

        Thread-safe: the store's lock (when present) is held for the whole
        block, so two threads sharing one connection serialize whole
        transactions instead of interleaving BEGIN/COMMIT.
        """
        from contextlib import contextmanager

        @contextmanager
        def _tx():
            lock = getattr(self, "_lock", None)
            if lock is not None:
                lock.acquire()
            try:
                depth = getattr(self, "_tx_depth", 0)
                self._tx_depth = depth + 1
                started = depth == 0
                try:
                    if started:
                        self._begin_transaction()
                    yield self
                    if started:
                        self._commit_transaction()
                except Exception:
                    if started:
                        self._rollback_transaction()
                    raise
                finally:
                    self._tx_depth = depth
            finally:
                if lock is not None:
                    lock.release()

        return _tx()

    def _begin_transaction(self) -> None:
        pass

    def _commit_transaction(self) -> None:
        pass

    def _rollback_transaction(self) -> None:
        pass

    def _maybe_commit(self) -> None:
        """Commit unless inside an open ``transaction()`` block."""
        if getattr(self, "_tx_depth", 0) == 0:
            self._commit_transaction()

    @staticmethod
    def sanitize_fts_terms(query: str) -> list[str]:
        return [t for t in "".join(c if c.isalnum() else " " for c in query).split() if len(t) > 1]
