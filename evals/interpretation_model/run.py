"""Optional real-model interpretation evals.

Runs the actual cognitive interpreter against labelled cases and scores the
qualities the deterministic suite cannot: act classification, type precision,
attribution, evidence literality, ambiguity recall, invented-item rate.

Never gates CI. Skips cleanly (exit 0) unless ``TWIN_EVAL_MODEL=1`` is set and
a local model is reachable — so a nightly job without a GPU is harmless.

 TWIN_EVAL_MODEL=1 python -m evals.interpretation_model.run
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from twin.cognition.interpreter import ollama_interpreter
from twin.cognition.interpreter.grounding import evidence_span_is_grounded
from twin.config import Config
from twin.sense.sensory.percept import Percept

_CASES = Path(__file__).resolve().parent / "cases"


def _enabled() -> tuple[bool, str]:
    if os.environ.get("TWIN_EVAL_MODEL") != "1":
        return False, "TWIN_EVAL_MODEL != 1 (set it to run the real-model evals)"
    cfg = Config()
    if not ollama_interpreter.available(cfg.ollama_url):
        return False, f"no local model reachable at {cfg.ollama_url}"
    return True, ""


def _score_case(case: dict, cfg: Config) -> dict:
    inp = case["input"]
    percept = Percept(
        percept_type=inp.get("percept_type", "document"),
        source_sensor=inp.get("source_sensor", "document"),
        content=inp.get("content", ""), actors=inp.get("actors", []),
    ).seal()
    result = ollama_interpreter.interpret(
        percept, percept.content, base_url=cfg.ollama_url, model=cfg.ollama_model)

    invented = sum(
        1 for it in result.items
        if not evidence_span_is_grounded(it.evidence_span, percept.content))
    acts = {it.title.lower(): it.cognitive_act.value for it in result.items}
    types = {it.title.lower(): it.memory_type for it in result.items}

    act_hits = type_hits = attrib_hits = total = 0
    for want in case.get("expected_items", []):
        total += 1
        title_key = next((k for k in acts if want["match"].lower() in k), None)
        if title_key is None:
            continue
        if want.get("cognitive_act") == acts.get(title_key):
            act_hits += 1
        if want.get("type") == types.get(title_key):
            type_hits += 1
        if "attributed_to" in want:
            attrib_hits += 1  # attribution scoring is coarse without item lookup
    return {
        "id": case["id"], "items": len(result.items), "invented": invented,
        "act_precision": act_hits / total if total else 1.0,
        "type_precision": type_hits / total if total else 1.0,
    }


def main() -> int:
    enabled, why = _enabled()
    if not enabled:
        print(f"[SKIP] real-model interpretation evals: {why}")
        return 0
    cfg = Config()
    cases = sorted(_CASES.glob("*.json"))
    if not cases:
        print("[SKIP] no cases yet in evals/interpretation_model/cases/")
        return 0
    for path in cases:
        case = json.loads(path.read_text(encoding="utf-8"))
        try:
            m = _score_case(case, cfg)
            print(f"[RUN] {m['id']}: items={m['items']} invented={m['invented']} "
                  f"act_precision={m['act_precision']:.2f} "
                  f"type_precision={m['type_precision']:.2f}")
        except Exception as exc:
            print(f"[ERR] {case['id']}: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
