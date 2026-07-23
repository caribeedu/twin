"""v0.9.9 / v1 — fail-closed cognitive OS completion matrix.

Cells require evidence pointers (tests and/or evals). ``pass`` without a
pointer demotes to ``not_tested``. ``ok`` is false on fail / not_tested /
partial / framework_only for required criteria.
"""

from __future__ import annotations

from typing import Any, Optional

STATUSES = frozenset({
    "pass",
    "fail",
    "not_tested",
    "partial",
    "not_applicable",
    "framework_only",
})

# Required cognitive OS bars for v1.0 readiness (thin but fail-closed).
CRITERIA: list[dict[str, Any]] = [
    {
        "id": "runtime.durable_queue",
        "summary": "durable job queue with exclusive claim + lease reclaim",
        "required": True,
        "status": "pass",
        "evidence": (
            "tests/runtime/test_runtime.py::test_claim_exclusive_between_workers;"
            "tests/runtime/test_runtime.py::test_expired_lease_reclaimed_by_other_worker"
        ),
        "eval": None,
    },
    {
        "id": "runtime.model_unavailable",
        "summary": "model unavailable never dead-letters",
        "required": True,
        "status": "pass",
        "evidence": "tests/runtime/test_runtime.py::test_model_unavailable_never_dead_letters",
        "eval": None,
    },
    {
        "id": "sessions.structured_closure",
        "summary": "session close never auto-confirms Memory/Judgment",
        "required": True,
        "status": "pass",
        "evidence": (
            "tests/cognition/test_session_lifecycle.py::"
            "test_structured_close_no_auto_confirm"
        ),
        "eval": None,
    },
    {
        "id": "memory.formation_confirm_needs_evidence",
        "summary": "confirm requires evidence; never auto-confirm",
        "required": True,
        "status": "pass",
        "evidence": (
            "tests/memory/test_formation.py::test_confirm_requires_evidence;"
            "tests/memory/test_formation.py::test_confirm_reject_restore_with_reason"
        ),
        "eval": None,
    },
    {
        "id": "connectors.production_ready_pair",
        "summary": "≥2 real production-ready adapters (Fake excluded)",
        "required": True,
        "status": "pass",
        "evidence": "tests/connectors/test_production_ready.py::test_production_ready_attests_two_real_adapters",
        "eval": None,
    },
    {
        "id": "sovereignty.backup_restore",
        "summary": "checksummed backup validate + sqlite restore round-trip",
        "required": True,
        "status": "pass",
        "evidence": "tests/sovereignty/test_backup.py::test_backup_validate_and_sqlite_restore",
        "eval": None,
    },
    {
        "id": "security.prompt_injection_screen",
        "summary": "ingested injection screened; pack excludes executable content",
        "required": True,
        "status": "pass",
        "evidence": (
            "tests/privacy/test_engine.py;"
            "tests/cognition/test_context_pack.py;"
            "tests/evals/test_security_adversarial.py::test_injection_does_not_become_instruction"
        ),
        "eval": None,
    },
    {
        "id": "security.cross_domain_deny",
        "summary": "cross-domain recall denied by default",
        "required": True,
        "status": "pass",
        "evidence": (
            "tests/cognition/test_context_pack.py::test_search_blocks_cross_domain;"
            "tests/evals/test_security_adversarial.py::test_cross_domain_recall_denied"
        ),
        "eval": None,
    },
    {
        "id": "golden.work_loop",
        "summary": "end-to-end work loop: percept→candidate→confirm→close→recall",
        "required": True,
        "status": "pass",
        "evidence": "tests/evals/test_golden_work_loop.py::test_golden_work_loop",
        "eval": "evals/v1/cases/golden_work_loop.json",
    },
    {
        "id": "explain.memory_chain",
        "summary": "confirmed memory has explainable evidence chain",
        "required": True,
        "status": "pass",
        "evidence": (
            "tests/evals/test_golden_work_loop.py::test_golden_work_loop;"
            "twin/memory/formation.py::explain_memory"
        ),
        "eval": None,
    },
    {
        "id": "metrics.reexplanation",
        "summary": "re-explanation reduction metric tracked",
        "required": False,
        "status": "partial",
        "evidence": "tests/memory/test_metrics.py",
        "eval": None,
        "note": "feedback signal exists; product KPI dashboard deferred",
    },
]


def _normalize_cell(raw: dict[str, Any]) -> dict[str, Any]:
    status = raw.get("status", "not_tested")
    if status not in STATUSES:
        status = "not_tested"
    evidence = raw.get("evidence")
    ev_eval = raw.get("eval")
    if status == "pass" and not evidence and not ev_eval:
        status = "not_tested"
        note = (raw.get("note") or "") + "; demoted: pass without evidence"
    else:
        note = raw.get("note") or ""
    return {
        "id": raw["id"],
        "summary": raw.get("summary", ""),
        "required": bool(raw.get("required", True)),
        "status": status,
        "evidence": evidence,
        "eval": ev_eval,
        "note": note.strip("; "),
    }


def v1_completion_matrix(
    *,
    criteria: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    rows = [_normalize_cell(c) for c in (criteria if criteria is not None else CRITERIA)]
    failed = [
        r["id"] for r in rows
        if r["required"] and r["status"] in ("fail", "not_tested", "partial", "framework_only")
    ]
    return {
        "matrix": "v1.0 cognitive OS",
        "criteria": rows,
        "failed": failed,
        "ok": not failed,
        "note": (
            "ok fails closed when any required criterion is fail, not_tested, "
            "partial, or framework_only. FakeConnector spine alone never "
            "satisfies connector criteria."
        ),
    }
