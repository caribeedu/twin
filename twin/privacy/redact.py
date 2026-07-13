"""Contextual redaction — transform ephemeral copies, never the canonical store."""

from __future__ import annotations

import hashlib
import hmac
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
    r"(R\$\s*)?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\d+(?:,\d{2})?)",
    re.I,
)

# Stable local HMAC key material for pseudonyms (vault-scoped in production).
_PSEUDONYM_KEY = b"twin-privacy-pseudonym-v1"


def plan_redaction(
    classification: ResourceClassification,
    decision: ResourceDecision,
    *,
    effect: Optional[PolicyEffect] = None,
) -> RedactionPlan:
    effect = effect or decision.effect
    ops: list[RedactionOp] = []

    # Treat aggregate as generalize at single-resource level (set-level aggregate not in v0.5)
    if effect == PolicyEffect.aggregate:
        effect = PolicyEffect.generalize

    if effect in (
        PolicyEffect.redact, PolicyEffect.generalize,
        PolicyEffect.pseudonymize, PolicyEffect.require_grant,
    ):
        # Always scrub title + summary when transforming
        if effect == PolicyEffect.generalize:
            ops.append(RedactionOp(
                path="title", action="generalize",
                value=_generalize_text(classification.title),
            ))
            ops.append(RedactionOp(
                path="summary", action="generalize",
                value=_generalize_text(classification.summary),
            ))
            decision.redacted_fields.extend(["title", "summary"])
        elif effect == PolicyEffect.pseudonymize:
            ops.append(RedactionOp(
                path="title", action="pseudonymize",
                value=_pseudonym("title", classification.title, classification),
            ))
            ops.append(RedactionOp(
                path="summary", action="pseudonymize",
                value=_pseudonym("summary", classification.summary, classification),
            ))
            decision.redacted_fields.extend(["title", "summary"])
        else:
            ops.append(RedactionOp(path="title", action="mask", value="[redacted]"))
            ops.append(RedactionOp(path="summary", action="mask", value="[content redacted by policy]"))
            decision.redacted_fields.extend(["title", "summary"])

        for path, field in classification.fields.items():
            if field.sensitivity.value in ("restricted", "highly_restricted", "confidential"):
                if effect == PolicyEffect.generalize:
                    ops.append(RedactionOp(
                        path=f"payload.{path}",
                        action="generalize",
                        value=_generalize_value(classification.payload.get(path)),
                    ))
                elif effect == PolicyEffect.pseudonymize:
                    ops.append(RedactionOp(
                        path=f"payload.{path}",
                        action="pseudonymize",
                        value=_pseudonym(path, str(classification.payload.get(path)), classification),
                    ))
                else:
                    ops.append(RedactionOp(path=f"payload.{path}", action="remove"))
                decision.redacted_fields.append(path)

        if classification.third_party or "third_party" in classification.labels:
            ops.append(RedactionOp(path="summary", action="mask", value="[third-party details removed]"))
            if "summary" not in decision.redacted_fields:
                decision.redacted_fields.append("summary")

    if effect == PolicyEffect.deny:
        ops.append(RedactionOp(path="*", action="remove"))

    # Dedupe redacted_fields
    decision.redacted_fields = sorted(set(decision.redacted_fields))

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
    """Return an ephemeral authorized view — never mutates the store."""
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
        if op.path in ("title", "summary"):
            if op.action == "remove":
                view[op.path] = "[removed]"
            else:
                view[op.path] = op.value or "[redacted]"
            continue
        if op.path.startswith("payload."):
            key = op.path.split(".", 1)[1]
            if op.action == "remove":
                view["payload"].pop(key, None)
            else:
                view["payload"][key] = op.value
    return view


def _pseudonym(field: str, value: str, classification: ResourceClassification) -> str:
    subject = (classification.subjects[0] if classification.subjects else classification.resource_id)
    msg = f"{classification.vault_id}:{subject}:{field}:{value or ''}".encode()
    digest = hmac.new(_PSEUDONYM_KEY, msg, hashlib.sha256).hexdigest()[:12]
    return f"p_{digest}"


def _generalize_value(value: Any) -> str:
    if value is None:
        return "[generalized]"
    if isinstance(value, (int, float)):
        n = float(value)
        if n >= 1000:
            lo = int(n // 5000) * 5
            return f"approx R$ {lo}k–{lo + 5}k"
        return "[generalized amount]"
    return _generalize_text(str(value))


def _generalize_text(text: str) -> str:
    if not text:
        return text
    # Replace currency-like spans with a range marker (not a fabricated exact)
    def _repl(m: re.Match[str]) -> str:
        raw = re.sub(r"[^\d]", "", m.group(2) or "")
        if not raw:
            return "[amount]"
        try:
            # Brazilian: 32.400,50 → digits without decimal cents for banding
            if "," in (m.group(0) or ""):
                whole = raw[:-2] if len(raw) > 2 else raw
            else:
                whole = raw
            n = int(whole or "0")
            if n >= 1000:
                lo = (n // 5000) * 5
                return f"[approx R$ {lo}k–{lo + 5}k]"
        except ValueError:
            pass
        return "[amount]"
    return _SALARY_RE.sub(_repl, text)


def leakage_scan(text: str, *, forbidden_substrings: list[str] | None = None) -> list[str]:
    """Return leakage findings (pattern names), never the sensitive content itself."""
    findings: list[str] = []
    lowered = (text or "").lower()
    if re.search(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", text or ""):
        findings.append("possible_cpf")
    if re.search(r"(api[_-]?key|password|secret)\s*[:=]", lowered):
        findings.append("possible_credential")
    if re.search(r"r\$\s*\d", lowered):
        findings.append("possible_exact_currency")
    for s in forbidden_substrings or []:
        if s and s in (text or ""):
            findings.append("forbidden_token")
    return findings
