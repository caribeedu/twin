"""Model-backed episode reflection (optional enrichment over the structural
reflector).

Given an :class:`EpisodeBrief`, ask a chat model to name the trajectory the
phase arc implies (e.g. "intended Kafka, then chose SQS"). The model receives
only already-derived structure and verbatim member quotes; it returns 0..N
claims. Every claim still lands as a MemoryCandidate for human review — the
model never confirms anything, and a failure falls back to structure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # avoid import cycle at module load
    from ..episode_reflect import EpisodeBrief, TrajectoryClaim

PROMPT_VERSION = "1"
SCHEMA_VERSION = "1"

_SYSTEM = (
    "You summarize the TRAJECTORY of a unit of work across multiple sources. "
    "You are given an episode's ordered phases (goal → decision → execution → "
    "outcome) and narrative edges (which decision superseded or motivated "
    "which). Produce claims that only a cross-source view reveals — e.g. "
    "'intended approach X, then chose Y' — never restating a single commit. "
    "Ground every claim in the provided quotes. If the arc shows no meaningful "
    "trajectory, return an empty list. You never confirm anything; these are "
    "candidates for human review."
)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["decision", "belief"]},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "evidence_quotes": {
                        "type": "array", "items": {"type": "string"},
                    },
                    "from_phase_key": {"type": "string"},
                    "to_phase_key": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["type", "title", "summary"],
            },
        },
    },
    "required": ["claims"],
}


def _render_brief(brief: "EpisodeBrief") -> str:
    lines = [f"Episode: {brief.title}", ""]
    lines.append("Phases (in order):")
    for p in sorted(brief.phases, key=lambda x: x["order"]):
        lines.append(
            f"  [{p['kind']}] key={p['phase_key']} "
            f"{p.get('started_at') or '?'} — {p.get('summary') or ''}"
        )
    lines.append("")
    lines.append("Narrative edges:")
    for e in brief.edges:
        lines.append(
            f"  {e['from_key']} --{e['relation']}--> {e['to_key']} "
            f"({e.get('evidence_quote') or ''})"
        )
    lines.append("")
    lines.append("Quotes by member:")
    for ref, q in brief.quotes_by_ref.items():
        lines.append(f"  {ref}: {q}")
    return "\n".join(lines)


def reflect_with_model(client, brief: "EpisodeBrief") -> list["TrajectoryClaim"]:
    from ..episode_reflect import TrajectoryClaim

    data = client.complete_json(
        system=_SYSTEM,
        user=_render_brief(brief),
        schema=_SCHEMA,
        temperature=0.1,
    )
    raw_claims = data.get("claims") if isinstance(data, dict) else None
    if not isinstance(raw_claims, list):
        return []

    phase_keys = {p["phase_key"] for p in brief.phases}
    out: list[TrajectoryClaim] = []
    for rc in raw_claims:
        if not isinstance(rc, dict) or not rc.get("title"):
            continue
        keys = [
            k for k in (rc.get("from_phase_key"), rc.get("to_phase_key"))
            if k in phase_keys
        ]
        edge_ids = [
            e["id"] for e in brief.edges
            if e["from_key"] in keys or e["to_key"] in keys
        ]
        percept_ids: list[str] = []
        for p in brief.phases:
            if p["phase_key"] in keys:
                for ref in p.get("members", []):
                    pid = brief.percept_by_ref.get(ref)
                    if pid and pid not in percept_ids:
                        percept_ids.append(pid)
        valid_from = brief.valid_from
        for p in brief.phases:
            if p["phase_key"] == rc.get("to_phase_key"):
                valid_from = p.get("started_at") or valid_from
        out.append(TrajectoryClaim(
            type=str(rc.get("type") or "decision"),
            title=str(rc["title"])[:200],
            summary=str(rc.get("summary") or ""),
            evidence_quotes=[
                str(q) for q in (rc.get("evidence_quotes") or []) if q
            ][:6],
            valid_from=valid_from,
            valid_until=brief.valid_until,
            confidence=float(rc.get("confidence") or 0.55),
            phase_keys=keys,
            edge_ids=edge_ids,
            percept_ids=percept_ids,
            canonical_claim={
                "subject": brief.project_id or brief.title,
                "predicate": "trajectory",
                "object": str(rc["title"])[:120],
            },
            twin_influenced=True,
        ))
    return out
