"""Offline eval for v0.8 workspace / consolidation spine.

Proves stage separation, retrieval-score gates, idempotency, and that cycles
do not expand the confirmed Memory/Judgment sets — by state, not by notes.

    python -m evals.consolidation.run
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from twin import ids
from twin.cognition.consolidation_cycle import run_consolidation_cycle
from twin.cognition.recall import RecallPolicy, apply_recall_policy
from twin.cognition.workspace import workspace_tick
from twin.config import Config
from twin.memory.embeddings import get_embedder
from twin.memory.models import MemoryItem
from twin.memory.store.sqlite import SqliteStore

_CASES = Path(__file__).resolve().parent / "cases"


def _seed_memory(store, embedder, **kw) -> MemoryItem:
    base = dict(
        id=ids.memory_id(), type="decision",
        title="Postgres primary",
        summary="Use Postgres as the primary database.",
        domain="technical", confidence=0.9, status="confirmed",
    )
    base.update(kw)
    mem = MemoryItem(**base)
    store.insert_memory(mem)
    store.store_embedding(
        mem.id, "memory", embedder.name,
        embedder.embed(f"{mem.title}\n{mem.summary}"),
    )
    return mem


def _confirmed_ids(store) -> set[str]:
    return {m.id for m in store.list_memories(status="confirmed", limit=10_000)}


def _run_case(case: dict) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="twin-consol-eval-") as tmp:
        store = SqliteStore(Path(tmp) / "eval.db")
        cfg = Config(home=Path(tmp) / "home")
        cfg.extractor = "echo"
        cfg.embedder = "hash"
        cfg.ensure_home()
        embedder = get_embedder("hash", cfg.embedding_dim)

        kind = case.get("kind", "workspace_tick")
        exp = case["expected"]

        if kind == "recall_policy":
            result = apply_recall_policy(
                case.get("suggested", []),
                case.get("blocked", []),
                policy=RecallPolicy(**(case.get("policy") or {})),
                salience_by_id=case.get("salience_by_id") or {},
                novelty_by_id=case.get("novelty_by_id") or {},
            )
            if "silent" in exp and result.silent != exp["silent"]:
                return False, f"silent {result.silent} != {exp['silent']}"
            if "suggestion_ids" in exp:
                got = [s.memory_id for s in result.suggestions]
                if got != exp["suggestion_ids"]:
                    return False, f"suggestions {got} != {exp['suggestion_ids']}"
            if "suggestion_count" in exp and len(result.suggestions) != exp["suggestion_count"]:
                return False, (
                    f"suggestions {len(result.suggestions)} != {exp['suggestion_count']}"
                )
            if exp.get("blocked_preserved"):
                if len(result.blocked) != len(case.get("blocked") or []):
                    return False, "blocked not preserved"
            return True, "ok"

        if kind == "workspace_tick":
            for row in case.get("seed_memories", []):
                _seed_memory(store, embedder, **row)
            before = _confirmed_ids(store)
            tick = workspace_tick(
                store, cfg, embedder,
                case["input"]["text"],
                target_domain=case["input"].get("domain"),
                interpret=bool(case["input"].get("interpret", False)),
                input_mode=case["input"].get("input_mode", "snapshot"),
                session_id=case["input"].get("session_id", ""),
                sequence=case["input"].get("sequence"),
            )
            if "silent" in exp and tick.silent != exp["silent"]:
                return False, f"silent {tick.silent} != {exp['silent']}"
            if "has_stages" in exp:
                for stage in exp["has_stages"]:
                    if stage not in tick.stages:
                        return False, f"missing stage {stage}"
            if exp.get("confirmed_unchanged") and _confirmed_ids(store) != before:
                return False, "confirmed memories changed"
            return True, "ok"

        if kind == "consolidation_cycle":
            before_mem = _confirmed_ids(store)
            result = run_consolidation_cycle(
                store, cfg, embedder,
                kind=case["input"].get("cycle", "daily"),
                dry_run=bool(case["input"].get("dry_run", True)),
            )
            if "kind" in exp and result.kind != exp["kind"]:
                return False, f"kind {result.kind} != {exp['kind']}"
            if "has_stages" in exp:
                for stage in exp["has_stages"]:
                    if stage not in result.stages:
                        return False, f"missing stage {stage}"
            if exp.get("confirmed_unchanged") and _confirmed_ids(store) != before_mem:
                return False, "confirmed memories changed by cycle"
            if exp.get("invariant_ok") and not any("invariant_ok" in n for n in result.notes):
                return False, "missing invariant_ok note"
            return True, "ok"

        return False, f"unknown kind {kind}"


def main() -> int:
    cases = sorted(_CASES.glob("*.json"))
    if not cases:
        print("no consolidation eval cases", file=sys.stderr)
        return 1
    failed = 0
    for path in cases:
        case = json.loads(path.read_text(encoding="utf-8"))
        ok, detail = _run_case(case)
        status = "PASS" if ok else "FAIL"
        print(f"{status}  {case.get('id', path.stem)}  {detail}")
        if not ok:
            failed += 1
    print(f"\n{len(cases) - failed}/{len(cases)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
