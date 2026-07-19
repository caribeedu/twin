"""v0.6 Phase 10 — §93 completion criteria evidence matrix.

Attests that Phases 1–9 satisfy the Final Review scenario. Cells are
evidence-based (test node id and/or eval id); ``pass`` without a pointer is
demoted to ``not_tested``. ``ok`` fails closed on ``fail`` / ``not_tested``.
"""

from __future__ import annotations

from typing import Any, Optional

STATUSES = frozenset({
    "pass",
    "fail",
    "not_tested",
    "partial",
    "not_applicable",
})

# §93 Critérios de conclusão — one row per criterion.
CRITERIA: list[dict[str, Any]] = [
    {
        "id": 1,
        "summary": "register professional GitHub account",
        "status": "pass",
        "evidence": (
            "tests/test_github_connector.py::test_list_repositories_setup_helper"
        ),
        "eval": "evals/connectors/cases/ops_health_metrics.json",
        "note": "register_source_account + setup plan + repository discovery (offline mock)",
    },
    {
        "id": 2,
        "summary": "classify ownership and choose vault",
        "status": "pass",
        "evidence": (
            "tests/test_connectors.py::test_org_vault_isolated_and_declared;"
            "tests/test_connector_ops_phase9.py::test_setup_plan_never_ingests"
        ),
        "eval": None,
        "note": "employer → org vault; reclassification preview-first",
    },
    {
        "id": 3,
        "summary": "preview shows repositories and backfill estimate",
        "status": "pass",
        "evidence": (
            "tests/test_github_connector.py::"
            "test_backfill_preview_reports_scope_and_never_ingests"
        ),
        "eval": "evals/connectors/cases/ops_health_metrics.json",
        "note": "preview never ingests",
    },
    {
        "id": 4,
        "summary": "incremental ingest of issues/PRs/reviews/commits",
        "status": "pass",
        "evidence": (
            "tests/test_github_connector.py::"
            "test_full_object_graph_with_lineage_and_trust"
        ),
        "eval": "evals/connectors/cases/github_pr_lifecycle.json",
        "note": None,
    },
    {
        "id": 5,
        "summary": "checkpoint advances only after batch commit",
        "status": "pass",
        "evidence": (
            "tests/test_connectors.py::test_checkpoint_advances_only_after_commit"
        ),
        "eval": "evals/connectors/cases/checkpoint_failure.json",
        "note": None,
    },
    {
        "id": 6,
        "summary": "replay same page does not duplicate artifacts/Percepts",
        "status": "pass",
        "evidence": "tests/test_connectors.py::test_second_sync_is_idempotent",
        "eval": "evals/connectors/cases/idempotency_replay.json",
        "note": None,
    },
    {
        "id": 7,
        "summary": "Slack thread related to PR is correlated",
        "status": "pass",
        "evidence": (
            "tests/test_correlation_phase7.py::"
            "test_episode_correlates_slack_mention_of_pr"
        ),
        "eval": "evals/connectors/cases/cross_source_work_episode.json",
        "note": "synthetic ConnectorRecords; live Slack+GitHub sync not required",
    },
    {
        "id": 8,
        "summary": "GitHub email notification is not independent evidence",
        "status": "pass",
        "evidence": (
            "tests/test_gmail_connector.py::test_github_notification_is_derived;"
            "tests/test_correlation_phase7.py::"
            "test_independence_group_shared_for_notification"
        ),
        "eval": "evals/connectors/cases/gmail_thread_lineage.json",
        "note": "derived + shared independence_group",
    },
    {
        "id": 9,
        "summary": "later meeting revises decision and supersedes prior memory",
        "status": "pass",
        "evidence": (
            "tests/test_v06_final_review.py::"
            "test_meeting_revises_decision_via_supersede"
        ),
        "eval": "evals/connectors/cases/v06_completion_scenario.json",
        "note": (
            "explicit supersede after meeting candidate; connectors never "
            "auto-confirm (criterion 17)"
        ),
    },
    {
        "id": 10,
        "summary": "source ownership remains across lineage",
        "status": "pass",
        "evidence": (
            "tests/test_github_connector.py::"
            "test_full_object_graph_with_lineage_and_trust"
        ),
        "eval": "evals/connectors/cases/github_pr_lifecycle.json",
        "note": None,
    },
    {
        "id": 11,
        "summary": "professional context pack uses authorized memory",
        "status": "pass",
        "evidence": (
            "tests/test_v06_final_review.py::"
            "test_professional_pack_includes_authorized_work_memory"
        ),
        "eval": None,
        "note": "developer + vault_work allow path",
    },
    {
        "id": 12,
        "summary": "personal persona does not receive employer content",
        "status": "pass",
        "evidence": (
            "tests/test_privacy.py::test_vault_persona_enforced;"
            "tests/test_privacy.py::test_context_pack_applies_privacy"
        ),
        "eval": None,
        "note": None,
    },
    {
        "id": 13,
        "summary": (
            "deleting a message removes its evidence without deleting "
            "corroborated memory"
        ),
        "status": "pass",
        "evidence": (
            "tests/test_privacy.py::test_artifact_delete_preserves_partial_memory;"
            "tests/test_connectors.py::test_tombstone_builds_lineage_impact_event"
        ),
        "eval": "evals/connectors/cases/source_deletion.json",
        "note": (
            "connector emits pending ConnectorDeletionEvent; privacy deletion "
            "recalculates multi-evidence memory"
        ),
    },
    {
        "id": 14,
        "summary": "revoked credential stops new syncs",
        "status": "pass",
        "evidence": (
            "tests/test_connectors.py::test_revoke_removes_secret_and_stops_sync"
        ),
        "eval": None,
        "note": None,
    },
    {
        "id": 15,
        "summary": "native adapter observes session and uses same core",
        "status": "pass",
        "evidence": "tests/test_native_host_phase8.py",
        "eval": "evals/native/cases/host_session_proactive_pack.json",
        "note": None,
    },
    {
        "id": 16,
        "summary": "MCP remains available simultaneously",
        "status": "pass",
        "evidence": "tests/test_mcp.py",
        "eval": "evals/native/cases/host_session_proactive_pack.json",
        "note": "native eval opens parallel MCP/CLI session alongside host binding",
    },
    {
        "id": 17,
        "summary": "no source auto-creates confirmed Memory or Judgment",
        "status": "pass",
        "evidence": (
            "tests/test_connectors.py::"
            "test_no_confirmed_memory_or_judgment_written;"
            "tests/test_native_host_phase8.py::test_no_confirmed_memory_delta"
        ),
        "eval": "evals/connectors/cases/github_pr_lifecycle.json",
        "note": None,
    },
]


def _cell(
    status: str,
    *,
    evidence: Optional[str] = None,
    eval_id: Optional[str] = None,
    note: str = "",
) -> dict[str, Any]:
    if status not in STATUSES:
        status = "not_tested"
        note = (note + "; invalid status demoted").strip("; ")
    if status == "pass" and not evidence and not eval_id:
        return {
            "status": "not_tested",
            "evidence": None,
            "eval": None,
            "note": "pass claimed without evidence pointer",
        }
    return {
        "status": status,
        "evidence": evidence,
        "eval": eval_id,
        "note": note or None,
    }


def completion_matrix() -> dict[str, Any]:
    """Return the §93 Final Review matrix for v0.6 Phase 10."""
    rows: list[dict[str, Any]] = []
    failed: list[int] = []
    partial: list[int] = []
    for raw in CRITERIA:
        cell = _cell(
            raw["status"],
            evidence=raw.get("evidence"),
            eval_id=raw.get("eval"),
            note=raw.get("note") or "",
        )
        row = {
            "id": raw["id"],
            "summary": raw["summary"],
            **cell,
        }
        rows.append(row)
        if cell["status"] in ("fail", "not_tested"):
            failed.append(raw["id"])
        elif cell["status"] == "partial":
            partial.append(raw["id"])
    return {
        "version": "v0.6",
        "phase": 10,
        "section": "93",
        "title": "Critérios de conclusão",
        "criteria": rows,
        "failed": failed,
        "partial": partial,
        "ok": not failed and not partial,
        "count": len(rows),
        "out_of_scope": {
            "section": "94",
            "items": [
                "send email",
                "post to Slack",
                "merge PR",
                "auto-create issues",
                "autonomous actions",
                "personal WhatsApp / social",
                "health or relationship ingestion",
                "full desktop observation",
                "OS-level automation",
                "voice always-on",
                "Effector Intent execution",
                "auto-create Judgment",
                "multiuser collaboration platform",
                "enterprise admin console",
            ],
        },
        "thesis": {
            "section": "95",
            "text": (
                "v0.6 dá ao Twin sentidos profissionais contínuos, mas mantém "
                "percepção, memória, julgamento e autorização centralizados no "
                "mesmo cérebro."
            ),
        },
    }


def check_criterion(criterion_id: int) -> dict[str, Any]:
    matrix = completion_matrix()
    for row in matrix["criteria"]:
        if row["id"] == criterion_id:
            return row
    raise ValueError(f"unknown criterion id {criterion_id}")
