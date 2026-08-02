"""Backfill partition planning + earliest-month discovery helpers."""
from __future__ import annotations

from datetime import date

from twin.connectors.mail.backfill import (
    base_stream_resolved,
    discover_earliest_month,
    incomplete_base_streams,
    record_stream_results,
)


TODAY = date(2026, 7, 31)


# -- stream-attempt cap (single failing source must not wedge partition) -----------


def _progress_with(streams=None, attempts=None, claim_token=1):
    part = {"partition_key": "2016-09", "claim_token": claim_token}
    if streams is not None:
        part["streams"] = dict(streams)
    if attempts is not None:
        part["stream_attempts"] = dict(attempts)
    return {"partitions": [part]}


def _part(progress):
    return progress["partitions"][0]


def test_failing_stream_terminalizes_after_cap():
    """A stream that never commits gives up after N attempts instead of
    looping forever as ``failed``."""
    progress = _progress_with()
    for i in range(1, 4):
        progress = record_stream_results(
            progress, "2016-09", [("channel:BAD", False, False)],
            claim_token=1, max_attempts=3,
        )
        expected = "failed_terminal" if i >= 3 else "failed"
        assert _part(progress)["streams"]["channel:BAD"] == expected
        assert _part(progress)["stream_attempts"]["channel:BAD"] == i


def test_commit_resets_failure_counter():
    """A stream making progress (a commit) resets its failure count so genuine
    pagination is never terminalized."""
    progress = _progress_with()
    progress = record_stream_results(
        progress, "2016-09", [("channel:OK", False, False)],
        claim_token=1, max_attempts=3,
    )
    assert _part(progress)["stream_attempts"]["channel:OK"] == 1
    progress = record_stream_results(
        progress, "2016-09", [("channel:OK", True, False)],
        claim_token=1, max_attempts=3,
    )
    assert _part(progress)["streams"]["channel:OK"] == "continuation_pending"
    assert "channel:OK" not in _part(progress)["stream_attempts"]


def test_completed_stream_never_regresses_on_empty_result():
    progress = _progress_with(streams={"channel:DONE": "completed"})
    progress = record_stream_results(
        progress, "2016-09", [("channel:DONE", False, False)],
        claim_token=1, max_attempts=3,
    )
    assert _part(progress)["streams"]["channel:DONE"] == "completed"
    assert "channel:DONE" not in _part(progress).get("stream_attempts", {})


def test_incomplete_base_streams_skips_resolved():
    part = {"streams": {
        "channel:DONE": "completed",
        "channel:BAD": "failed_terminal",
        "channel:PENDING": "failed",
    }}
    bases = ["channel:DONE", "channel:BAD", "channel:PENDING"]
    assert incomplete_base_streams(part, bases) == ["channel:PENDING"]


def test_base_stream_resolved_states():
    part = {"streams": {"a": "completed", "b": "failed_terminal", "c": "failed"}}
    assert base_stream_resolved(part, "a") is True
    assert base_stream_resolved(part, "b") is True
    assert base_stream_resolved(part, "c") is False
    assert base_stream_resolved(part, "missing") is False


def _oldest(month_first_day: date):
    """Predicate factory: content whose oldest item is the given month."""
    return lambda d: d > month_first_day


def test_discover_returns_oldest_content_month():
    floor = discover_earliest_month(_oldest(date(2023, 11, 1)), today=TODAY)
    assert floor == "2023-11-01"


def test_discover_boundary_current_month():
    # oldest content is the current month
    floor = discover_earliest_month(_oldest(date(2026, 7, 1)), today=TODAY)
    assert floor == "2026-07-01"


def test_discover_no_content_returns_none():
    assert discover_earliest_month(lambda d: False, today=TODAY) is None


def test_discover_clamps_beyond_search_window():
    # content everywhere → clamp to the max look-back floor, never earlier
    floor = discover_earliest_month(lambda d: True, today=TODAY, max_years_back=40)
    assert floor == "1986-07-01"


def test_discover_probe_count_is_logarithmic():
    calls = {"n": 0}

    def probe(d):
        calls["n"] += 1
        return d > date(2010, 4, 1)

    floor = discover_earliest_month(probe, today=TODAY)
    assert floor == "2010-04-01"
    # ~log2(40*12) ≈ 9 for the search, plus 2 boundary probes — never linear
    assert calls["n"] < 20
