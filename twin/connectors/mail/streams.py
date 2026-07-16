"""Mail stream naming: continuous vs backfill namespaces (v0.6 Phase 4).

Continuous streams stay provider-native:

    label:{id}
    folder:{id}

Backfill uses a separate checkpoint/lease namespace so historical partitions
never regress continuous watermarks:

    backfill:{job_id}:{partition_key}:label:{id}
    backfill:{job_id}:{partition_key}:folder:{id}
"""

from __future__ import annotations

from typing import Any, Optional

from ..models import FailureClass
from ..protocol import ConnectorError


def format_backfill_stream(job_id: str, partition_key: str, base_stream: str) -> str:
    if not job_id or not partition_key or not base_stream:
        raise ValueError("job_id, partition_key and base_stream required")
    if base_stream.startswith("backfill:"):
        raise ValueError(f"base_stream already namespaced: {base_stream!r}")
    return f"backfill:{job_id}:{partition_key}:{base_stream}"


def parse_mail_stream(stream: str) -> dict[str, Any]:
    """Split a mail stream into mode metadata + provider base stream."""
    if stream.startswith("backfill:"):
        parts = stream.split(":", 3)
        if len(parts) != 4 or not parts[1] or not parts[2] or not parts[3]:
            raise ConnectorError(
                f"unknown backfill stream layout: {stream!r}",
                failure_class=FailureClass.schema_change,
            )
        return {
            "mode": "backfill",
            "job_id": parts[1],
            "partition_key": parts[2],
            "base_stream": parts[3],
        }
    return {
        "mode": "continuous",
        "job_id": None,
        "partition_key": None,
        "base_stream": stream,
    }


def parse_label_stream(base_stream: str) -> str:
    parts = base_stream.split(":", 1)
    if len(parts) != 2 or parts[0] != "label" or not parts[1]:
        raise ConnectorError(
            f"unknown gmail stream layout: {base_stream!r}",
            failure_class=FailureClass.schema_change,
        )
    return parts[1]


def parse_folder_stream(base_stream: str) -> str:
    parts = base_stream.split(":", 1)
    if len(parts) != 2 or parts[0] != "folder" or not parts[1]:
        raise ConnectorError(
            f"unknown outlook stream layout: {base_stream!r}",
            failure_class=FailureClass.schema_change,
        )
    return parts[1]


def continuous_base_streams(streams: list[str]) -> list[str]:
    """Strip backfill namespaces — used when creating jobs from plan_streams."""
    out: list[str] = []
    for s in streams:
        meta = parse_mail_stream(s)
        base = meta["base_stream"]
        if base not in out:
            out.append(base)
    return out


def is_backfill_stream(stream: str) -> bool:
    return stream.startswith("backfill:")
