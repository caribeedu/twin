"""Evaluation framework for extraction and retrieval regressions.

Each case runs in an isolated temporary store — never the user's production DB.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .. import ids
from ..cognition.pipeline import extract_percept
from ..clock import now_iso
from ..config import Config
from ..memory.embeddings import Embedder, get_embedder
from ..memory.models import Evidence, MemoryItem, MemoryStatus
from ..memory.store.sqlite import SqliteStore
from ..cognition.context_pack import build_context_pack
from ..cognition.retrieval import retrieve
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
        if data.get("_placeholder"):
            continue
        data.setdefault("id", path.stem)
        cases.append(data)
    return cases


def _temp_store() -> tuple[SqliteStore, Path]:
    tmp = tempfile.mkdtemp(prefix="twin-eval-")
    path = Path(tmp) / "eval.db"
    return SqliteStore(path), path


def _claim_match(expected_claim: str, text: str) -> float:
    """Token F1 between expected claim and memory text (0..1)."""
    import re
    exp = set(re.findall(r"[a-z0-9_]{3,}", expected_claim.lower()))
    got = set(re.findall(r"[a-z0-9_]{3,}", text.lower()))
    if not exp:
        return 0.0
    if not got:
        return 0.0
    overlap = len(exp & got)
    precision = overlap / len(got)
    recall = overlap / len(exp)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def run_extraction_eval(
    store,  # ignored — kept for API compatibility; never written
    cfg: Config,
    embedder: Embedder,
    dataset_dir: Path,
) -> EvalRun:
    del store  # production store must not be touched
    cases = _load_cases(dataset_dir)
    results: list[EvalCaseResult] = []
    precision_scores: list[float] = []
    recall_scores: list[float] = []
    type_acc: list[float] = []
    domain_acc: list[float] = []

    for case in cases:
        iso_store, _ = _temp_store()
        try:
            eval_embedder = get_embedder("hash", 64)
            eval_cfg = Config(home=iso_store.path.parent)
            eval_cfg.extractor = "heuristic"
            eval_cfg.embedder = "hash"
            inp = case["input"]
            expected = case["expected"]
            percept = Percept(
                id=ids.new_id("pct"),
                percept_type=inp.get("percept_type", "document"),
                source_sensor=inp.get("source_sensor", "document"),
                content=inp["percept"] if isinstance(inp.get("percept"), str)
                else inp.get("content", ""),
                source_trust=inp.get("source_trust", 0.9),
            )
            iso_store.insert_percept(percept)
            report = extract_percept(iso_store, eval_cfg, eval_embedder, percept)
            inserted = [iso_store.get_memory(mid) for mid in report.inserted]
            inserted = [m for m in inserted if m]

            expected_mems = expected.get("memories", [])
            must_not = expected.get("must_not_extract", [])

            matched = 0
            type_hits = 0
            domain_hits = 0
            for exp in expected_mems:
                best = 0.0
                best_mem = None
                for mem in inserted:
                    claim = exp.get("canonical_claim") or ""
                    text = f"{mem.title} {mem.summary}"
                    score = _claim_match(claim, text) if claim else (
                        1.0 if exp.get("type") == mem.type.value else 0.0
                    )
                    if score > best:
                        best = score
                        best_mem = mem
                if best_mem and best >= 0.6:
                    matched += 1
                    if not exp.get("type") or best_mem.type.value == exp["type"]:
                        type_hits += 1
                    if not exp.get("domain") or best_mem.domain == exp["domain"]:
                        domain_hits += 1

            forbidden_hits = sum(
                1 for mem in inserted
                for bad in must_not
                if bad.lower() in f"{mem.title} {mem.summary}".lower()
            )

            precision = matched / len(inserted) if inserted else (1.0 if not expected_mems else 0.0)
            recall = matched / len(expected_mems) if expected_mems else 0.0
            # empty expected memories with no insertions is not a free pass
            if not expected_mems and not must_not:
                results.append(EvalCaseResult(
                    case_id=case["id"], passed=False, detail="invalid fixture: empty expected",
                    metrics={},
                ))
                continue

            precision_scores.append(precision)
            recall_scores.append(recall)
            if expected_mems:
                type_acc.append(type_hits / len(expected_mems))
                domain_acc.append(domain_hits / len(expected_mems))

            passed = (
                recall >= 0.7
                and (precision >= 0.5 or not inserted)
                and forbidden_hits == 0
            )
            results.append(EvalCaseResult(
                case_id=case["id"],
                passed=passed,
                metrics={
                    "precision": round(precision, 3),
                    "recall": round(recall, 3),
                    "type_accuracy": round(type_hits / max(len(expected_mems), 1), 3),
                    "domain_accuracy": round(domain_hits / max(len(expected_mems), 1), 3),
                    "claim_f1_matched": matched,
                    "inserted": len(inserted),
                    "expected": len(expected_mems),
                    "forbidden_hits": forbidden_hits,
                    "duplicates": report.duplicates,
                },
            ))
        finally:
            iso_store.close()

    n = len(results) or 1
    return EvalRun(
        id=ids.eval_run_id(),
        kind="extraction",
        at=now_iso(),
        cases=results,
        summary={
            "cases": len(results),
            "passed": sum(1 for r in results if r.passed),
            "avg_precision": round(sum(precision_scores) / max(len(precision_scores), 1), 3)
            if precision_scores else None,
            "avg_recall": round(sum(recall_scores) / max(len(recall_scores), 1), 3)
            if recall_scores else None,
            "type_accuracy": round(sum(type_acc) / max(len(type_acc), 1), 3) if type_acc else None,
            "domain_accuracy": round(sum(domain_acc) / max(len(domain_acc), 1), 3)
            if domain_acc else None,
            "status": "implemented",
        },
    )


def run_retrieval_eval(
    store,  # ignored
    embedder: Embedder,
    dataset_dir: Path,
    *,
    firewall=None,
    k: int = 5,
    cfg: Optional[Config] = None,
) -> EvalRun:
    del store
    cases = _load_cases(dataset_dir)
    results: list[EvalCaseResult] = []
    precisions: list[float] = []
    recalls: list[float] = []
    mrrs: list[float] = []

    for case in cases:
        expected_ids = list(case.get("expected_memory_ids") or [])
        seed = case.get("seed_memories") or []
        # require either explicit expected ids or seedable fixtures with claims
        if not expected_ids and not seed and not case.get("expected_claims"):
            results.append(EvalCaseResult(
                case_id=case.get("id", "unknown"),
                passed=False,
                detail="invalid fixture: empty expected_memory_ids without seed",
            ))
            continue

        iso_store, _ = _temp_store()
        try:
            eval_embedder = get_embedder("hash", 64)
            id_map: dict[str, str] = {}
            for raw in seed:
                mid = raw.get("id") or ids.memory_id()
                real_id = ids.memory_id() if mid.startswith("mem_fixture") or mid in id_map else mid
                if mid.startswith("mem_") and not mid.startswith("mem_01"):
                    # fixture alias
                    id_map[mid] = real_id
                else:
                    real_id = mid
                    id_map[mid] = mid
                mem = MemoryItem(
                    id=id_map[mid],
                    type=raw.get("type", "fact"),  # type: ignore[arg-type]
                    title=raw["title"],
                    summary=raw.get("summary", raw["title"]),
                    domain=raw.get("domain", "technical"),
                    confidence=float(raw.get("confidence", 0.9)),
                    status=raw.get("status", "confirmed"),  # type: ignore[arg-type]
                    project_id=raw.get("project_id"),
                    entities=raw.get("entities") or [],
                )
                iso_store.insert_memory(mem)
                iso_store.store_embedding(
                    mem.id, "memory", eval_embedder.name,
                    eval_embedder.embed(f"{mem.title}\n{mem.summary}"),
                )
                for quote in raw.get("evidence") or []:
                    pct = Percept(
                        id=ids.new_id("pct"), percept_type="document",
                        source_sensor="document", content=quote,
                    )
                    iso_store.insert_percept(pct)
                    iso_store.insert_evidence(Evidence(
                        id=ids.evidence_id(), memory_id=mem.id,
                        percept_id=pct.id, quote=quote,
                    ))

            # remap expected ids through fixture aliases
            resolved_expected = [id_map.get(e, e) for e in expected_ids]
            if case.get("expected_claims") and not resolved_expected:
                # resolve by claim text match against seeded memories
                for claim in case["expected_claims"]:
                    for m in iso_store.list_memories(limit=1000):
                        if _claim_match(claim, f"{m.title} {m.summary}") >= 0.6:
                            resolved_expected.append(m.id)
                resolved_expected = list(dict.fromkeys(resolved_expected))

            if not resolved_expected:
                results.append(EvalCaseResult(
                    case_id=case.get("id", "unknown"),
                    passed=False,
                    detail="invalid fixture: no resolvable expected memories",
                ))
                continue

            forbidden = {id_map.get(f, f) for f in case.get("forbidden_memory_ids", [])}
            query = case["query"]
            project_id = case.get("project_id")
            result = retrieve(
                iso_store, eval_embedder, query,
                target_domain=case.get("domain", "technical"),
                firewall=firewall,
                project_id=project_id,
                limit=k,
            )
            hit_ids = [h.memory.id for h in result.hits]
            # never bump production retrieval counts — isolated store only

            # inactive statuses must not appear
            inactive_hits = [
                hid for hid in hit_ids
                if (m := iso_store.get_memory(hid)) and m.status.value in (
                    "merged", "split", "archived", "unsupported", "stale",
                    "deleted", "rejected", "deprecated", "contradicted",
                )
            ]

            expected_set = set(resolved_expected)
            relevant_hits = [hid for hid in hit_ids if hid in expected_set]
            forbidden_hits = [hid for hid in hit_ids if hid in forbidden]
            precision = len(relevant_hits) / len(hit_ids) if hit_ids else 0.0
            recall = len(relevant_hits) / len(expected_set) if expected_set else 0.0
            mrr = 0.0
            for i, hid in enumerate(hit_ids):
                if hid in expected_set:
                    mrr = 1.0 / (i + 1)
                    break

            # optional pack section check
            section_ok = True
            expected_sections = case.get("expected_sections") or []
            if expected_sections and cfg is not None:
                pack = build_context_pack(
                    iso_store, cfg, eval_embedder, query,
                    target_domain=case.get("domain", "technical"),
                    project_id=project_id, firewall=firewall,
                )
                for sec in expected_sections:
                    if f"## {sec}" not in pack.context_pack and sec not in pack.context_pack:
                        section_ok = False

            # evidence coverage: hits should have evidence when required
            evidence_ok = True
            if case.get("require_evidence", True):
                for hid in relevant_hits:
                    if not iso_store.get_evidence(hid):
                        evidence_ok = False

            precisions.append(precision)
            recalls.append(recall)
            mrrs.append(mrr)
            passed = (
                recall >= 0.5
                and not forbidden_hits
                and not inactive_hits
                and section_ok
                and evidence_ok
            )
            results.append(EvalCaseResult(
                case_id=case.get("id", query[:40]),
                passed=passed,
                metrics={
                    "precision_at_k": round(precision, 3),
                    "recall_at_k": round(recall, 3),
                    "mrr": round(mrr, 3),
                    "forbidden_retrieval_rate": round(
                        len(forbidden_hits) / max(len(hit_ids), 1), 3
                    ),
                    "inactive_hits": inactive_hits,
                    "hit_ids": hit_ids,
                    "section_ok": section_ok,
                    "evidence_ok": evidence_ok,
                },
            ))
        finally:
            iso_store.close()

    n = max(len(results), 1)
    return EvalRun(
        id=ids.eval_run_id(),
        kind="retrieval",
        at=now_iso(),
        cases=results,
        summary={
            "cases": len(results),
            "passed": sum(1 for r in results if r.passed),
            "avg_precision_at_k": round(sum(precisions) / max(len(precisions), 1), 3)
            if precisions else None,
            "avg_recall_at_k": round(sum(recalls) / max(len(recalls), 1), 3)
            if recalls else None,
            "mrr": round(sum(mrrs) / max(len(mrrs), 1), 3) if mrrs else None,
            "status": "implemented",
        },
    )


def compare_runs(a: EvalRun, b: EvalRun) -> dict[str, Any]:
    return {
        "a": {"id": a.id, "kind": a.kind, "summary": a.summary},
        "b": {"id": b.id, "kind": b.kind, "summary": b.summary},
        "delta": {
            k: round((b.summary.get(k) or 0) - (a.summary.get(k) or 0), 3)
            for k in set(a.summary) | set(b.summary)
            if isinstance(a.summary.get(k), (int, float))
            or isinstance(b.summary.get(k), (int, float))
        },
    }


def default_eval_root() -> Path:
    return Path(__file__).resolve().parents[2] / "evals"
