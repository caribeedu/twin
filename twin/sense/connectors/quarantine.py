"""Injection screening for connector content — thin wrap over privacy quarantine.

Ingested content is data, never instruction. A quarantined record produces no
Percept and never reaches extraction.
"""

from __future__ import annotations

from typing import Optional

from twin.privacy.models import QuarantineRecord
from twin.privacy.quarantine import quarantine_content
from .models import ConnectorRecord


def screen_record(store, record: ConnectorRecord) -> Optional[QuarantineRecord]:
    """Return a QuarantineRecord if the normalized content looks malicious."""
    return quarantine_content(
        store,
        record.content or "",
        reason="connector_prompt_injection",
    )
