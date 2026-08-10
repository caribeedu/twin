"""Render modes for context packs."""

from __future__ import annotations

from typing import Any, Literal

PackMode = Literal["compact", "explainable", "references_only"]


def render_pack(
    *,
    mode: PackMode,
    sections_text: str,
    provenance: list[dict[str, Any]],
    active: dict[str, Any],
    explanation: dict[str, Any],
    uncertainty: dict[str, Any],
) -> str:
    # Unclassified / awaiting domain confirmation: default-deny empty pack.
    # Scope chrome alone would still look like injectable context.
    if (active.get("domain") or "") == "unclassified" and not sections_text:
        return ""

    header_bits = []
    if active.get("domain"):
        header_bits.append(f"domain={active['domain']}")
    if active.get("persona"):
        header_bits.append(f"persona={active['persona']}")
    if active.get("project"):
        header_bits.append(f"project={active['project']}")
    if active.get("session_id"):
        header_bits.append(f"session={active['session_id']}")
    header = "## Scope\n" + (", ".join(header_bits) if header_bits else "(unscoped)")
    goals = active.get("goals") or []
    if goals:
        header += "\nGoals: " + "; ".join(str(g) for g in goals[:8])

    if mode == "references_only":
        lines = [header, "", "## References"]
        for p in provenance:
            lines.append(
                f"- [{p.get('label', 'item')}] {p.get('claim_id')} "
                f"(conf={p.get('confidence', 0):.2f}, ev={p.get('evidence_n', 0)}) "
                f"→ {p.get('inspect_path')}"
            )
        if uncertainty.get("low_confidence_ids"):
            lines.append("")
            lines.append(
                f"Uncertainty: {len(uncertainty['low_confidence_ids'])} low-confidence refs"
            )
        return "\n".join(lines)

    body = sections_text or ""
    if mode == "explainable":
        parts = [header, "", body, "", "## Explanation"]
        parts.append(f"profile={explanation.get('profile')}")
        dropped = explanation.get("dropped") or {}
        if dropped:
            parts.append(
                "dropped: " + ", ".join(f"{k}={v}" for k, v in dropped.items() if v)
            )
        inj = explanation.get("injection_blocked") or []
        if inj:
            parts.append(f"injection_blocked={len(inj)}")
        parts.append(f"blocked_count={explanation.get('blocked_count', 0)}")
        if provenance:
            parts.append("")
            parts.append("## Provenance")
            for p in provenance[:12]:
                parts.append(
                    f"- {p.get('claim_id')}: {p.get('title')} "
                    f"[{p.get('label')}] {p.get('inspect_path')}"
                )
        return "\n".join(parts)

    # compact
    if header_bits or goals:
        return header + ("\n\n" + body if body else "")
    return body
