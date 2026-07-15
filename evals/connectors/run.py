"""Tiny offline runner for connector eval cases (Phase 1).

Runs each JSON case in ``cases/`` against the FakeConnector on an isolated
in-memory store. No network, no production DB.

Case ``scenario`` selects the harness:

    normalization        sync once, assert records/percepts/lineage
    replay               sync N times, assert idempotency
    partial_batch        one item fails → NO percepts visible, checkpoint still;
                         retry succeeds → everything lands together
    revision_collision   same external revision, different content → DLQ,
                         original evidence preserved
    checkpoint_failure   fault-injected finalize → batch not committed AND
                         checkpoint unchanged (never one without the other)
    quarantine           malicious content → quarantined, zero percepts
    source_deletion      tombstone → deletion event with prior lineage,
                         no new percepts

    python -m evals.connectors.run
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from twin.connectors import (
    add_connector_instance,
    build_credential_store,
    register_source_account,
    sync_connector,
)
from twin.memory.store.sqlite import SqliteStore

_CASES = Path(__file__).resolve().parent / "cases"


def _setup(case: dict, tmp: str):
    store = SqliteStore(":memory:")
    creds = build_credential_store(Path(tmp))
    acc = register_source_account(
        store,
        connector_type=case.get("connector_type", "fake"),
        source_owner=case["source_owner"],
        org_key=case.get("org_key"),
        owner_principal_id="principal_eval",
    )
    inst = add_connector_instance(
        store, creds, account_id=acc.id, secret="eval-token",
        configuration={"fixtures": case["fixtures"],
                       **case.get("configuration", {})},
    )
    return store, creds, acc, inst


def _check_expected(case, store, inst, acc, result) -> tuple[bool, str]:
    exp = case["expected"]
    records = store.list_connector_records(inst.id)
    percepts = store.list_percepts()
    if "records" in exp and len(records) != exp["records"]:
        return False, f"records {len(records)} != {exp['records']}"
    if "percepts" in exp and result.percepts != exp["percepts"]:
        return False, f"percepts {result.percepts} != {exp['percepts']}"
    if "record" in exp:
        rec = records[0]
        for key, want in exp["record"].items():
            got = getattr(rec, key)
            got = getattr(got, "value", got)
            if got != want:
                return False, f"record.{key} {got!r} != {want!r}"
    if "percept_metadata" in exp:
        meta = percepts[0].metadata
        for key, want in exp["percept_metadata"].items():
            if meta.get(key) != want:
                return False, f"percept.metadata.{key} {meta.get(key)!r} != {want!r}"
    if exp.get("checkpoint_advances"):
        if store.get_connector_checkpoint(inst.id, "issues") is None:
            return False, "checkpoint did not advance"
    if "dead_letters" in exp:
        dead = store.list_connector_dead_letters(inst.id)
        if len(dead) != exp["dead_letters"]:
            return False, f"dead letters {len(dead)} != {exp['dead_letters']}"
    if "deletion_events" in exp:
        events = store.list_connector_deletion_events(inst.id)
        if len(events) != exp["deletion_events"]:
            return False, f"deletion events {len(events)} != {exp['deletion_events']}"
    if "quarantined" in exp:
        quarantined = sum(1 for r in records if r.quarantined)
        if quarantined != exp["quarantined"]:
            return False, f"quarantined {quarantined} != {exp['quarantined']}"
    return True, "ok"


def _run_simple(case: dict) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="twin-conn-eval-") as tmp:
        store, creds, acc, inst = _setup(case, tmp)
        result = sync_connector(store, creds, inst.id)
        ok, detail = _check_expected(case, store, inst, acc, result)
        if not ok:
            return ok, detail
        exp = case["expected"]
        for _ in range(case.get("replays", 1) - 1):
            again = sync_connector(store, creds, inst.id)
            if "second_pass_new_percepts" in exp and \
                    again.percepts != exp["second_pass_new_percepts"]:
                return False, f"replay percepts {again.percepts} != " \
                              f"{exp['second_pass_new_percepts']}"
    return True, "ok"


def _run_partial_batch(case: dict) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="twin-conn-eval-") as tmp:
        store, creds, acc, inst = _setup(case, tmp)
        first = sync_connector(store, creds, inst.id)
        if first.percepts != 0:
            return False, "partial batch exposed percepts before commit"
        if store.list_percepts():
            return False, "percepts visible from uncommitted batch"
        if store.get_connector_checkpoint(inst.id, "issues") is not None:
            return False, "checkpoint advanced on partial failure"
        # heal the failing item and retry: everything lands together
        store.update_connector_instance(
            inst.id, configuration={"fixtures": case["fixtures"]})
        second = sync_connector(store, creds, inst.id)
        exp = case["expected"]
        if second.percepts != exp["percepts_after_retry"]:
            return False, f"retry percepts {second.percepts} != " \
                          f"{exp['percepts_after_retry']}"
        if store.get_connector_checkpoint(inst.id, "issues") is None:
            return False, "checkpoint did not advance after healthy retry"
    return True, "ok"


def _run_revision_collision(case: dict) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="twin-conn-eval-") as tmp:
        store, creds, acc, inst = _setup(case, tmp)
        sync_connector(store, creds, inst.id)
        original = store.list_connector_records(inst.id)[0].content
        # same revision, different content
        store.update_connector_instance(
            inst.id, configuration={"fixtures": case["collision_fixtures"]})
        second = sync_connector(store, creds, inst.id)
        dead = store.list_connector_dead_letters(inst.id)
        if not any(d.failure_class.value == "revision_collision" for d in dead):
            return False, "collision did not dead-letter"
        if store.list_connector_records(inst.id)[0].content != original:
            return False, "original evidence was overwritten"
        if any(s.committed for s in second.streams if s.stream == "issues"):
            return False, "collision batch was committed"
    return True, "ok"


def _run_checkpoint_failure(case: dict) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="twin-conn-eval-") as tmp:
        store, creds, acc, inst = _setup(case, tmp)
        original_cas = store.cas_connector_checkpoint

        def failing_cas(checkpoint, expected_version):
            return False  # simulate a concurrent advance

        store.cas_connector_checkpoint = failing_cas
        result = sync_connector(store, creds, inst.id)
        store.cas_connector_checkpoint = original_cas
        if any(s.committed for s in result.streams):
            return False, "batch claimed committed without checkpoint"
        if store.get_connector_checkpoint(inst.id, "issues") is not None:
            return False, "checkpoint advanced despite CAS failure"
        if store.list_percepts():
            return False, "percepts visible from aborted batch"
        # retry with a healthy store completes everything together
        retry = sync_connector(store, creds, inst.id)
        if retry.percepts != case["expected"]["percepts_after_retry"]:
            return False, "retry did not deliver the batch"
    return True, "ok"


def _run_source_deletion(case: dict) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="twin-conn-eval-") as tmp:
        store, creds, acc, inst = _setup(case, tmp)
        sync_connector(store, creds, inst.id)
        percepts_before = len(store.list_percepts())
        store.update_connector_instance(
            inst.id, configuration={"fixtures": case["deletion_fixtures"]})
        sync_connector(store, creds, inst.id)
        events = store.list_connector_deletion_events(inst.id)
        exp = case["expected"]
        if len(events) != exp["deletion_events"]:
            return False, f"deletion events {len(events)} != {exp['deletion_events']}"
        event = events[0]
        if len(event.prior_record_ids) != exp["prior_records"]:
            return False, f"prior records {len(event.prior_record_ids)}"
        if len(event.affected_percept_ids) != exp["affected_percepts"]:
            return False, f"affected percepts {len(event.affected_percept_ids)}"
        if len(store.list_percepts()) != percepts_before:
            return False, "deletion created or removed percepts by itself"
    return True, "ok"


_SCENARIOS = {
    "normalization": _run_simple,
    "replay": _run_simple,
    "quarantine": _run_simple,
    "partial_batch": _run_partial_batch,
    "revision_collision": _run_revision_collision,
    "checkpoint_failure": _run_checkpoint_failure,
    "source_deletion": _run_source_deletion,
}


def main() -> int:
    cases = sorted(_CASES.glob("*.json"))
    passed = 0
    for path in cases:
        case = json.loads(path.read_text(encoding="utf-8"))
        runner = _SCENARIOS.get(case.get("scenario", "normalization"), _run_simple)
        try:
            ok, detail = runner(case)
        except Exception as exc:  # an eval crash is a failure, not an abort
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        passed += int(ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {case['id']}: {detail}")
    print(f"\n{passed}/{len(cases)} connector eval cases passed")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
