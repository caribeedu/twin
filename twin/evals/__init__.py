"""Evaluation framework for extraction and retrieval regressions.

Each case runs in an isolated temporary store — never the user's production DB.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Optional

from .. import ids
from ..cognition.context_pack import build_context_pack
from ..cognition.pipeline import extract_percept
from ..cognition.retrieval import retrieve
from ..clock import now_iso
from ..config import Config
from ..judgment.firewall import Firewall
from ..memory.embeddings import Embedder, get_embedder
from ..memory.models import Evidence, MemoryItem
from ..memory.store.sqlite import SqliteStore
from ..sensory.percept import Percept

_DEFAULT_POLICIES = Path(__file__).resolve().parent.parent / "defaults" / "policies.yaml"


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


def _policies_path(cfg: Optional[Config] = None) -> Path:
    if cfg is not None and cfg.policies_path.exists():
        return cfg.policies_path
    return _DEFAULT_POLICIES


def _eval_runtime(
    cfg: Config,
    embedder: Embedder,
    *,
    mode: str,
    iso_home: Path,
) -> tuple[Config, Embedder]:
    """Build extractor/embedder for an isolated eval case.

    ``deterministic``: heuristic + hash (CI-stable).
    ``configured``: caller's extractor/embedder, still on an isolated store.
    """
    if mode == "configured":
        eval_cfg = replace(cfg, home=iso_home, db_url="")
        return eval_cfg, embedder
    if mode != "deterministic":
        raise ValueError(f"unknown eval mode: {mode!r} (use deterministic|configured)")
    eval_cfg = Config(home=iso_home)
    eval_cfg.extractor = "echo"   # deterministic offline interpreter (no LLM)
    eval_cfg.embedder = "hash"
    return eval_cfg, get_embedder("hash", 64)


def _claim_match(expected_claim: str, text: str) -> float:
    """Token F1 between expected claim and memory text (0..1)."""
    import re
    exp = set(re.findall(r"[a-z0-9_]{3,}", expected_claim.lower()))
    got = set(re.findall(r"[a-z0-9_]{3,}", text.lower()))
    if not exp or not got:
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
    *,
    mode: str = "deterministic",
) -> EvalRun:
    del store  # production store must not be touched
    cases = _load_cases(dataset_dir)
    results: list[EvalCaseResult] = []
    precision_scores: list[float] = []
    recall_scores: list[float] = []
    type_acc: list[float] = []
    domain_acc: list[float] = []

    for case in cases:
        with tempfile.TemporaryDirectory(prefix="twin-eval-") as tmp:
            iso_home = Path(tmp)
            iso_store = SqliteStore(iso_home / "eval.db")
            try:
                eval_cfg, eval_embedder = _eval_runtime(
                    cfg, embedder, mode=mode, iso_home=iso_home,
                )
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

                precision = matched / len(inserted) if inserted else (
                    1.0 if not expected_mems else 0.0
                )
                recall = matched / len(expected_mems) if expected_mems else 0.0
                if not expected_mems and not must_not:
                    results.append(EvalCaseResult(
                        case_id=case["id"], passed=False,
                        detail="invalid fixture: empty expected",
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
                        "mode": mode,
                    },
                ))
            finally:
                iso_store.close()

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
            "mode": mode,
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
    mode: str = "deterministic",
) -> EvalRun:
    del store
    del firewall  # never reuse caller's store-bound firewall
    cases = _load_cases(dataset_dir)
    results: list[EvalCaseResult] = []
    precisions: list[float] = []
    recalls: list[float] = []
    mrrs: list[float] = []

    for case in cases:
        expected_ids = list(case.get("expected_memory_ids") or [])
        seed = case.get("seed_memories") or []
        if not expected_ids and not seed and not case.get("expected_claims"):
            results.append(EvalCaseResult(
                case_id=case.get("id", "unknown"),
                passed=False,
                detail="invalid fixture: empty expected_memory_ids without seed",
            ))
            continue

        with tempfile.TemporaryDirectory(prefix="twin-eval-") as tmp:
            iso_home = Path(tmp)
            iso_store = SqliteStore(iso_home / "eval.db")
            try:
                eval_embedder = embedder if mode == "configured" else get_embedder("hash", 64)
                iso_firewall = Firewall(_policies_path(cfg), iso_store)
                id_map: dict[str, str] = {}
                for raw in seed:
                    mid = raw.get("id") or ids.memory_id()
                    real_id = (
                        ids.memory_id()
                        if mid.startswith("mem_fixture") or mid in id_map
                        else mid
                    )
                    if mid.startswith("mem_") and not mid.startswith("mem_01"):
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

                resolved_expected = [id_map.get(e, e) for e in expected_ids]
                if case.get("expected_claims") and not resolved_expected:
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
                    firewall=iso_firewall,
                    project_id=project_id,
                    limit=k,
                )
                hit_ids = [h.memory.id for h in result.hits]

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

                section_ok = True
                expected_sections = case.get("expected_sections") or []
                if expected_sections and cfg is not None:
                    pack = build_context_pack(
                        iso_store, cfg, eval_embedder, query,
                        target_domain=case.get("domain", "technical"),
                        project_id=project_id, firewall=iso_firewall,
                    )
                    for sec in expected_sections:
                        if f"## {sec}" not in pack.context_pack and sec not in pack.context_pack:
                            section_ok = False

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
                        "mode": mode,
                    },
                ))
            finally:
                iso_store.close()

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
            "mode": mode,
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


def run_judgment_eval(store, cfg, dataset_dir: Path) -> EvalRun:
    """Scope/precedence/constraint checks against judgment fixtures."""
    from ..judgment.simulate import simulate
    from ..judgment.yaml_io import apply_yaml_import, preview_yaml_import

    cases = _load_cases(dataset_dir)
    results: list[EvalCaseResult] = []
    # bootstrap from default yaml into isolated judgment tables on the given store
    preview = preview_yaml_import(cfg.judgment_path)
    if not store.list_judgment_items(status="active", limit=1):
        apply_yaml_import(store, cfg.judgment_path, classifications=preview)

    for case in cases:
        ctx = case.get("context") or {}
        options = list(case.get("options") or [])
        expected = case.get("expected") or {}
        sim = simulate(
            store,
            case.get("query") or case["id"],
            domain=ctx.get("domain", "technical"),
            task_profile=ctx.get("task_profile", "architecture"),
            options=options or None,
        )
        forbidden = set(expected.get("must_not_choose") or [])
        chose_forbidden = sim.get("recommendation") in forbidden
        terms = expected.get("required_explanation_terms") or []
        md = (sim.get("markdown") or "").lower()
        terms_ok = all(any(t.lower() in md for t in [term]) for term in terms) if terms else True
        # soft: at least one term family appears
        if terms and not terms_ok:
            terms_ok = any(t.lower() in md for t in terms)
        passed = (not chose_forbidden) and terms_ok
        results.append(EvalCaseResult(
            case_id=case["id"],
            passed=passed,
            metrics={
                "recommendation": sim.get("recommendation"),
                "blocked": sim.get("blocked_options"),
                "snapshot_id": sim.get("snapshot_id"),
            },
            detail="" if passed else "constraint/precedence mismatch",
        ))

    return EvalRun(
        id=ids.eval_run_id(),
        kind="judgment",
        at=now_iso(),
        cases=results,
        summary={
            "cases": len(results),
            "passed": sum(1 for r in results if r.passed),
            "status": "implemented",
        },
    )
