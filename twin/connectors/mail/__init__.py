"""Shared professional-mail cognitive layer (v0.6 Phase 4).

Provider adapters live in ``twin.connectors.gmail`` and
``twin.connectors.outlook``; this package owns MIME normalization,
classification, trust calibration and BackfillJob partition planning.
"""

from .backfill import (
    apply_partition_claim,
    mark_partition,
    next_runnable_partition,
    plan_year_month_partitions,
    release_partition_claim,
)
from .classification import classify_message, is_memory_relevant
from .streams import format_backfill_stream, parse_mail_stream

__all__ = [
    "apply_partition_claim",
    "classify_message",
    "format_backfill_stream",
    "is_memory_relevant",
    "mark_partition",
    "next_runnable_partition",
    "parse_mail_stream",
    "plan_year_month_partitions",
    "release_partition_claim",
]
