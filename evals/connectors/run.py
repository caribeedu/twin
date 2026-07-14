"""Tiny offline runner for connector eval cases (Phase 1 skeleton).

Runs each JSON case in ``cases/`` against the FakeConnector on an isolated
in-memory store. No network, no production DB.

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


def _run_case(case: dict) -> tuple[bool, str]:
    store = SqliteStore(":memory:")
    with tempfile.TemporaryDirectory(prefix="twin-conn-eval-") as tmp:
        creds = build_credential_store(Path(tmp))
        acc = register_source_account(
            store,
            connector_type=case.get("connector_type", "fake"),
            source_owner=case["source_owner"],
            org_key=case.get("org_key"),
        )
        inst = add_connector_instance(
            store, creds, account_id=acc.id, secret="eval-token",
            configuration={"fixtures": case["fixtures"]},
        )
        first = sync_connector(store, creds, inst.id)
        exp = case["expected"]

        records = store.list_connector_records(inst.id)
        percepts = store.list_percepts()
        if len(records) != exp["records"]:
            return False, f"records {len(records)} != {exp['records']}"
        if first.percepts != exp["percepts"]:
            return False, f"percepts {first.percepts} != {exp['percepts']}"

        if "record" in exp:
            rec = records[0]
            for key, want in exp["record"].items():
                got = getattr(rec, key)
                if got != want:
                    return False, f"record.{key} {got!r} != {want!r}"
        if "percept_metadata" in exp:
            meta = percepts[0].metadata
            for key, want in exp["percept_metadata"].items():
                if meta.get(key) != want:
                    return False, f"percept.metadata.{key} {meta.get(key)!r} != {want!r}"

        for _ in range(case.get("replays", 1) - 1):
            again = sync_connector(store, creds, inst.id)
            if "second_pass_new_percepts" in exp and again.percepts != exp["second_pass_new_percepts"]:
                return False, f"replay percepts {again.percepts} != {exp['second_pass_new_percepts']}"

        if exp.get("checkpoint_advances"):
            if store.get_connector_checkpoint(inst.id, "issues") is None:
                return False, "checkpoint did not advance"
    return True, "ok"


def main() -> int:
    cases = sorted(_CASES.glob("*.json"))
    passed = 0
    for path in cases:
        case = json.loads(path.read_text(encoding="utf-8"))
        ok, detail = _run_case(case)
        passed += int(ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {case['id']}: {detail}")
    print(f"\n{passed}/{len(cases)} connector eval cases passed")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
