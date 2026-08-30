"""GitHub stream naming: continuous vs backfill namespaces.

Continuous streams:

    repo:{owner}/{name}:{family}

Backfill (Phase 4 job partitions) uses a separate checkpoint/lease namespace
so historical windows never regress continuous watermarks:

    backfill:{job_id}:{partition_key}:repo:{owner}/{name}:{family}

The ``backfill:…`` prefix is a connector-runtime convention (see
``run_backfill_partition``); this module only understands GitHub's base
layout after the prefix is stripped.
"""

from __future__ import annotations

from typing import Any

from ..models import FailureClass
from ..protocol import ConnectorError

FAMILIES = frozenset({"issues", "pulls", "commits", "releases"})


def parse_github_stream(stream: str) -> dict[str, Any]:
    """Split a GitHub stream into mode metadata + ``repo`` / ``family``.

    Raises ``ConnectorError`` on unknown layouts.
    """
    mode = "continuous"
    job_id: str | None = None
    partition_key: str | None = None
    base = stream
    if stream.startswith("backfill:"):
        # Maxsplit 3 so the base stream (which itself contains ':') stays intact.
        parts = stream.split(":", 3)
        if len(parts) != 4 or not parts[1] or not parts[2] or not parts[3]:
            raise ConnectorError(
                f"unknown github backfill stream layout: {stream!r}",
                failure_class=FailureClass.schema_change,
            )
        mode = "backfill"
        job_id, partition_key, base = parts[1], parts[2], parts[3]

    pieces = base.split(":")
    if len(pieces) != 3 or pieces[0] != "repo" or pieces[2] not in FAMILIES:
        raise ConnectorError(
            f"unknown github stream layout: {stream!r}",
            failure_class=FailureClass.schema_change,
        )
    return {
        "mode": mode,
        "job_id": job_id,
        "partition_key": partition_key,
        "base_stream": base,
        "repo": pieces[1],
        "family": pieces[2],
    }
