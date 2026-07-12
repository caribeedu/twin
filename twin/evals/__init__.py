"""Evaluation framework for extraction and retrieval regressions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .. import ids
from ..cognition.extractors import heuristic as heuristic_extractor
from ..cognition.pipeline import extract_percept
from ..clock import now_iso
from ..config import Config
from ..memory.embeddings import Embedder
from ..memory.search import search
from ..memory.store.base import MemoryStore
from ..sensory.percept import Percept


@dataclass
class EvalCaseResult:
    case_id: str
    passed: bool
    metrics: dict[str, Any] = field(default_factory=dict)
    detail: str = ""


@dataclass
class EvalRun:
    id: str
    kind: str
    at: str
    cases: list[EvalCaseResult] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


def _load_cases(directory: Path) -> list[dict[str, Any]]:
    cases = []
    if not directory.exists():
        return cases
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text())
        data.setdefault("id", path.stem)
        cases.append(data)
    return cases


def run_extraction_eval(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    dataset_dir: Path,
) -> EvalRun:
    cases = _load_cases(dataset_dir)
    results: list[EvalCaseResult] = []
    precision_scores: list[float] = []
    recall_scores: list[float] = []

    for case in cases:
        inp = case["input"]
        expected = case["expected"]
        percept = Percept(
            id=ids.new_id("pct"),
            percept_type=inp.get("percept_type", "document"),
            source_sensor=inp.get("source_sensor", "document"),
            content=inp["percept"] if isinstance(inp.get("percept"), str) else inp.get("content", ""),
            source_trust=inp.get("source_trust", 0.9),
        )
        # isolate: extract without polluting shared store heavily — still uses store for dedupe
        report = extract_percept(store, cfg, embedder, percept)
        inserted = [store.get_memory(mid) for mid in report.inserted]
        inserted = [m for m in inserted if m]

        expected_mems = expected.get("memories", [])
        must_not = expected.get("must_not_extract", [])

        # type / domain accuracy against expected claims
        matched = 0
        for exp in expected_mems:
            for mem in inserted:
                type_ok = not exp.get("type") or mem.type.value == exp["type"]
                domain_ok = not exp.get("domain") or mem.domain == exp["domain"]
                claim = (exp.get("canonical_claim") or "").lower()
                text = f"{mem.title} {mem.summary}".lower()
                claim_ok = not claim or claim in text or any(
                    w in text for w in claim.split() if len(w) > 3
                )
                if type_ok and domain_ok and claim_ok:
                    matched += 1
                    break

        forbidden_hits = sum(
            1 for mem in inserted
            for bad in must_not
            if bad.lower() in f"{mem.title} {mem.summary}".lower()
        )

        precision = matched / len(inserted) if inserted else (1.0 if not expected_mems else 0.0)
        recall = matched / len(expected_mems) if expected_mems else 1.0
        precision_scores.append(precision)
        recall_scores.append(recall)
        passed = recall >= 0.5 and forbidden_hits == 0 and (
            precision >= 0.3 or not inserted
        )
        results.append(EvalCaseResult(
            case_id=case["id"],
            passed=passed,
            metrics={
                "precision": round(precision, 3),
                "recall": round(recall, 3),
                "inserted": len(inserted),
                "expected": len(expected_mems),
                "forbidden_hits": forbidden_hits,
                "duplicates": report.duplicates,
            },
        ))

    n = len(results) or 1
    run = EvalRun(
        id=ids.eval_run_id(),
        kind="extraction",
        at=now_iso(),
        cases=results,
        summary={
            "cases": len(results),
            "passed": sum(1 for r in results if r.passed),
            "avg_precision": round(sum(precision_scores) / n, 3) if precision_scores else None,
            "avg_recall": round(sum(recall_scores) / n, 3) if recall_scores else None,
        },
    )
    return run


def run_retrieval_eval(
    store: MemoryStore,
    embedder: Embedder,
    dataset_dir: Path,
    *,
    firewall=None,
    k: int = 5,
) -> EvalRun:
    cases = _load_cases(dataset_dir)
    results: list[EvalCaseResult] = []
    precisions: list[float] = []
    recalls: list[float] = []
    mrrs: list[float] = []

    for case in cases:
        query = case["query"]
        expected_ids = set(case.get("expected_memory_ids", []))
        forbidden = set(case.get("forbidden_memory_ids", []))
        project = case.get("project")
        result = search(
            store, embedder, query,
            target_domain=case.get("domain", "technical"),
            firewall=firewall,
            limit=k,
        )
        hit_ids = [h.memory.id for h in result.hits]
        # bump retrieval counts
        for hid in hit_ids:
            if hasattr(store, "bump_retrieval"):
                store.bump_retrieval(hid)

        relevant_hits = [hid for hid in hit_ids if hid in expected_ids]
        forbidden_hits = [hid for hid in hit_ids if hid in forbidden]
        precision = len(relevant_hits) / len(hit_ids) if hit_ids else 0.0
        recall = len(relevant_hits) / len(expected_ids) if expected_ids else 1.0
        mrr = 0.0
        for i, hid in enumerate(hit_ids):
            if hid in expected_ids:
                mrr = 1.0 / (i + 1)
                break
        precisions.append(precision)
        recalls.append(recall)
        mrrs.append(mrr)
        results.append(EvalCaseResult(
            case_id=case.get("id", query[:40]),
            passed=recall >= 0.5 and not forbidden_hits,
            metrics={
                "precision_at_k": round(precision, 3),
                "recall_at_k": round(recall, 3),
                "mrr": round(mrr, 3),
                "forbidden_retrieval_rate": round(len(forbidden_hits) / max(len(hit_ids), 1), 3),
                "hit_ids": hit_ids,
                "project": project,
            },
        ))

    n = len(results) or 1
    return EvalRun(
        id=ids.eval_run_id(),
        kind="retrieval",
        at=now_iso(),
        cases=results,
        summary={
            "cases": len(results),
            "passed": sum(1 for r in results if r.passed),
            "avg_precision_at_k": round(sum(precisions) / n, 3) if precisions else None,
            "avg_recall_at_k": round(sum(recalls) / n, 3) if recalls else None,
            "mrr": round(sum(mrrs) / n, 3) if mrrs else None,
        },
    )


def compare_runs(a: EvalRun, b: EvalRun) -> dict[str, Any]:
    return {
        "a": {"id": a.id, "kind": a.kind, "summary": a.summary},
        "b": {"id": b.id, "kind": b.kind, "summary": b.summary},
        "delta": {
            k: round((b.summary.get(k) or 0) - (a.summary.get(k) or 0), 3)
            for k in set(a.summary) | set(b.summary)
            if isinstance(a.summary.get(k), (int, float)) or isinstance(b.summary.get(k), (int, float))
        },
    }


def default_eval_root() -> Path:
    return Path(__file__).resolve().parents[2] / "evals"
