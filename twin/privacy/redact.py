"""Contextual redaction — transform ephemeral copies, never the canonical store."""

from __future__ import annotations

import re
from typing import Any, Optional

from .. import ids
from ..clock import now_iso
from .models import (
    PolicyEffect,
    RedactionOp,
    RedactionPlan,
    ResourceClassification,
    ResourceDecision,
)

_SALARY_RE = re.compile(
    r"(R\$\s*)?(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})?|\d+)",
    re.I,
)


def plan_redaction(
    classification: ResourceClassification,
    decision: ResourceDecision,
    *,
    effect: Optional[PolicyEffect] = None,
) -> RedactionPlan:
    effect = effect or decision.effect
    ops: list[RedactionOp] = []

    if effect in (PolicyEffect.redact, PolicyEffect.generalize, PolicyEffect.aggregate,
                  PolicyEffect.pseudonymize, PolicyEffect.require_grant):
        for path, field in classification.fields.items():
            if field.sensitivity.value in ("restricted", "highly_restricted", "confidential"):
                if effect == PolicyEffect.generalize or effect == PolicyEffect.aggregate:
                    ops.append(RedactionOp(
                        path=f"payload.{path}",
                        action="generalize",
                        value=_generalize_value(classification.payload.get(path)),
                    ))
                elif effect == PolicyEffect.pseudonymize:
                    ops.append(RedactionOp(
                        path=f"payload.{path}",
                        action="pseudonymize",
                        value=f"field_{abs(hash(path)) % 10000}",
                    ))
                else:
                    ops.append(RedactionOp(path=f"payload.{path}", action="remove"))
                    decision.redacted_fields.append(path)

        if "financial" in classification.labels or classification.domain == "finance":
            if not any(o.path.endswith("salary") for o in ops):
                ops.append(RedactionOp(
                    path="summary",
                    action="generalize",
                    value=_generalize_summary(classification.summary),
                ))
                decision.redacted_fields.append("summary")

        if classification.third_party or "third_party" in classification.labels:
            ops.append(RedactionOp(path="summary", action="mask", value="[third-party details removed]"))
            decision.redacted_fields.append("summary")

    if effect == PolicyEffect.deny:
        ops.append(RedactionOp(path="*", action="remove"))

    return RedactionPlan(
        id=ids.new_id("rplan"),
        resource_id=classification.resource_id,
        operations=ops,
        policy_ids=list(decision.matched_policy_ids),
        created_at=now_iso(),
    )


def apply_redaction_plan(
    classification: ResourceClassification,
    plan: RedactionPlan,
) -> dict[str, Any]:
    """Return an ephemeral view dict — never mutates the store."""
    view = {
        "id": classification.resource_id,
        "title": classification.title,
        "summary": classification.summary,
        "domain": classification.domain,
        "sensitivity": classification.sensitivity,
        "payload": dict(classification.payload),
        "redacted": True,
        "redaction_plan_id": plan.id,
    }
    for op in plan.operations:
        if op.path == "*":
            view["title"] = "[redacted]"
            view["summary"] = "[content removed by policy]"
            view["payload"] = {}
            continue
        if op.path == "summary":
            if op.action == "remove":
                view["summary"] = "[removed]"
            else:
                view["summary"] = op.value or "[redacted]"
            continue
        if op.path.startswith("payload."):
            key = op.path.split(".", 1)[1]
            if op.action == "remove":
                view["payload"].pop(key, None)
            else:
                view["payload"][key] = op.value
    return view


def _generalize_value(value: Any) -> str:
    if value is None:
        return "[generalized]"
    text = str(value)
    m = _SALARY_RE.search(text.replace(".", "").replace(" ", ""))
    if m:
        try:
            digits = re.sub(r"[^\d]", "", m.group(2) or m.group(0))
            n = int(digits[:6] or "0")
            if n > 1000:
                lo = (n // 5000) * 5
                return f"R$ {lo}k–{lo + 5}k"
        except ValueError:
            pass
    return "[generalized value]"


def _generalize_summary(summary: str) -> str:
    if not summary:
        return summary
    # Strip exact currency-like amounts
    return _SALARY_RE.sub("[amount]", summary)


def leakage_scan(text: str, *, forbidden_substrings: list[str] | None = None) -> list[str]:
    """Return leakage findings (patterns), never the sensitive content itself."""
    findings: list[str] = []
    lowered = text.lower()
    if re.search(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", text):
        findings.append("possible_cpf")
    if re.search(r"(api[_-]?key|password|secret)\s*[:=]", lowered):
        findings.append("possible_credential")
    if re.search(r"r\$\s*\d", lowered):
        findings.append("possible_exact_currency")
    for s in forbidden_substrings or []:
        if s and s in text:
            findings.append("forbidden_token")
    return findings
