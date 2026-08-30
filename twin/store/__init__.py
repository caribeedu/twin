"""Store — persistence, search, embeddings.

Product nouns remain Narrative / Stance / Evidence. This package is the
storage facade (``TwinStore`` contract + backends under ``twin.store.store``).
"""

from .models import (
    ClaimStatus, ClaimType, Entity, Evidence, Relation, Sensitivity,
    StoreClaim,
)
from .store import TwinStore, create_store

__all__ = [
    "Entity", "Evidence", "StoreClaim", "ClaimStatus", "ClaimType",
    "Relation", "Sensitivity", "TwinStore", "create_store",
]
