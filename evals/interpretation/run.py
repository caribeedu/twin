"""Offline eval runner for the cognitive interpreter.

Each case drives the real pipeline (``extract_percept``) with a *scripted*
interpreter injected via ``set_interpreter_override`` — deterministic, no LLM,
no network — so CI verifies the governance the interpreter's output flows
through: semantic classification, speaker attribution, evidence grounding and
the proposal-versus-decision distinction. The interpreter itself (an LLM) is
out of scope here; what we prove is that whatever it says is catalogued
correctly and safely.

 python -m evals.interpretation.run
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from twin.cognition import set_interpreter_override
from twin.cognition.interpreter.schema import (
    InterpretationResult,
    InterpretationStatus,
    InterpretedItem,
)
from twin.cognition.pipeline import extract_percept
from twin.config import Config
from twin.memory.embeddings import get_embedder
from twin.memory.store.sqlite import SqliteStore
from twin.sensory.percept import Percept

_CASES = Path(__file__).resolve().parent / "cases"


def _scripted(case: dict):
    """An interpreter that always returns the case's canned items."""
    status = InterpretationStatus(case.get("status", "interpreted"))

    def _fn(percept, text, cfg):
        items = [InterpretedItem(**it) for it in case.get("interpreter_output", [])]
        return InterpretationResult(
            items=items,
            status=status if items else InterpretationStatus.empty,
            interpreter="scripted", model="scripted",
            prompt_version="eval", schema_version="1",
            unresolved_references=list(case.get("unresolved_references", [])),
        )
    return _fn


def _run_case(case: dict) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="twin-interp-eval-") as tmp:
        store = SqliteStore(Path(tmp) / "eval.db")
        cfg = Config(home=Path(tmp) / "home")
        cfg.extractor = "auto"      # interpreting mode; override supplies the model
        cfg.embedder = "hash"
        cfg.ensure_home()
        embedder = get_embedder("hash", cfg.embedding_dim)
        inp = case["input"]
        percept = Percept(
            percept_type=inp.get("percept_type", "document"),
            source_sensor=inp.get("source_sensor", "document"),
            content=inp.get("content", ""),
            actors=inp.get("actors", []),
            source_trust=inp.get("source_trust", 0.9),
        ).seal()
        store.insert_percept(percept)

        set_interpreter_override(_scripted(case))
        try:
            report = extract_percept(store, cfg, embedder, percept)
        finally:
            set_interpreter_override(None)

        memories = [store.get_memory(mid) for mid in report.inserted]
        memories = [m for m in memories if m]
        exp = case["expected"]

        if "status" in exp and report.interpretation_status != exp["status"]:
            return False, (f"status {report.interpretation_status!r} != "
                           f"{exp['status']!r}")
        if "catalogued" in exp and len(memories) != exp["catalogued"]:
            return False, f"catalogued {len(memories)} != {exp['catalogued']}"
        if "deferred" in exp and report.deferred != exp["deferred"]:
            return False, f"deferred {report.deferred} != {exp['deferred']}"

        by_type: dict[str, list] = {}
        for m in memories:
            by_type.setdefault(m.type.value, []).append(m)

        for want in exp.get("memories", []):
            match = None
            for m in memories:
                if want.get("type") and m.type.value != want["type"]:
                    continue
                if want.get("title_contains") and \
                        want["title_contains"].lower() not in m.title.lower():
                    continue
                if want.get("summary_contains") and \
                        want["summary_contains"].lower() not in m.summary.lower():
                    continue
                match = m
                break
            if match is None:
                return False, f"no memory matched {want}"
            if "needs_review" in want and match.needs_review != want["needs_review"]:
                return False, (f"{want.get('title_contains', want.get('type'))}: "
                               f"needs_review {match.needs_review} != {want['needs_review']}")
            reason = match.review_reason or ""
            if "review_reason_contains" in want and \
                    want["review_reason_contains"] not in reason:
                return False, (f"review_reason {reason!r} lacks "
                               f"{want['review_reason_contains']!r}")
            if "review_reason_excludes" in want and \
                    want["review_reason_excludes"] in reason:
                return False, (f"review_reason {reason!r} unexpectedly contains "
                               f"{want['review_reason_excludes']!r}")
            if "cognitive_act" in want and \
                    match.payload.get("cognitive_act") != want["cognitive_act"]:
                return False, (f"cognitive_act {match.payload.get('cognitive_act')!r}"
                               f" != {want['cognitive_act']!r}")
            if "attributed_to" in want and \
                    match.payload.get("attributed_to") != want["attributed_to"]:
                return False, (f"attributed_to {match.payload.get('attributed_to')!r}"
                               f" != {want['attributed_to']!r}")
            if want.get("rejected_alternative") and \
                    not match.payload.get("rejected_alternative"):
                return False, "expected payload.rejected_alternative"
            if want.get("evidence_grounded"):
                quotes = [e.quote for e in store.get_evidence(match.id)]
                if not quotes or not any(q.strip() for q in quotes):
                    return False, "expected grounded evidence span"

        for bad in exp.get("must_not_catalogue", []):
            for m in memories:
                if bad.lower() in f"{m.title} {m.summary}".lower():
                    return False, f"catalogued forbidden item: {bad!r}"

    return True, "ok"


def main() -> int:
    cases = sorted(_CASES.glob("*.json"))
    passed = 0
    for path in cases:
        case = json.loads(path.read_text(encoding="utf-8"))
        try:
            ok, detail = _run_case(case)
        except Exception as exc:  # a crash is a failure, not an abort
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        passed += int(ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {case['id']}: {detail}")
    print(f"\n{passed}/{len(cases)} interpretation eval cases passed")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
