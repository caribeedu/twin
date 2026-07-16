"""Shared professional-mail cognitive layer (v0.6 Phase 4).

Provider adapters live in ``twin.connectors.gmail`` and
``twin.connectors.outlook``; this package owns MIME normalization,
classification, trust calibration and BackfillJob partition planning.
"""

from .backfill import mark_partition, next_runnable_partition, plan_year_month_partitions
from .classification import classify_message, is_memory_relevant

__all__ = [
    "classify_message",
    "is_memory_relevant",
    "mark_partition",
    "next_runnable_partition",
    "plan_year_month_partitions",
]
