"""Cortex stage — narrative edges over an episode's phase arc.

Given ordered phases (already grouped from amygdala roles) and member quotes,
a chat model proposes revisable causal / narrative edges between phases:
``motivated | superseded | resolved | continues | contradicts``. Edges are
proposals for human confirm / reject — never Memory or Judgment. No lexical
rules: without a model, no edges are proposed.
"""

from __future__ import annotations

from typing import Any

PROMPT_VERSION = "2"
SCHEMA_VERSION = "1"

_SYSTEM = """\
You read the ordered phases of a unit of work and propose the causal /
narrative links between them. Use only these relations:
- motivated: an earlier phase (goal/decision) prompted a later one;
- superseded: a later decision overturns or replaces an earlier one
  (the heart of 'intended X, then chose Y');
- resolved: an outcome closes/answers an earlier goal or decision;
- continues: a phase simply carries on the previous work;
- contradicts: two phases disagree across sources.

Reference phases by their phase_key. Only connect phases that are given.
Prefer the most informative relation; do not emit an edge you cannot ground
in the quotes. Return an empty edges array if the arc has no meaningful
structure.

Respond with JSON only, matching the schema. Field names MUST be exactly:
- edges: array of objects
- from_key / to_key: phase_key strings from the input
- relation: one of motivated | superseded | resolved | continues | contradicts
- confidence: number in [0,1] (optional)
- evidence_quote: short grounding quote (optional)
Do NOT emit prose, bullets, or alternate field names.
"""

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "from_key": {"type": "string"},
                    "to_key": {"type": "string"},
                    "relation": {
                        "type": "string",
                        "enum": [
                            "motivated", "superseded", "resolved",
                            "continues", "contradicts",
                        ],
                    },
                    "confidence": {"type": "number"},
                    "evidence_quote": {"type": "string"},
                },
                "required": ["from_key", "to_key", "relation"],
            },
        },
    },
    "required": ["edges"],
}


def _render(phases: list[dict[str, Any]], quotes_by_ref: dict[str, str]) -> str:
    lines = ["Phases (in order):", ""]
    for p in sorted(phases, key=lambda x: x.get("order", 0)):
        lines.append(
            f"- phase_key={p.get('phase_key')} kind={p.get('kind')} "
            f"at={p.get('started_at') or '?'}\n    {p.get('summary') or ''}"
        )
        for ref in p.get("members", []):
            q = quotes_by_ref.get(ref)
            if q:
                lines.append(f"      · {ref}: {q}")
    lines.append("")
    lines.append(
        'Return JSON: {"edges":[{"from_key":"…","to_key":"…","relation":'
        '"motivated|superseded|resolved|continues|contradicts",'
        '"confidence":0.6,"evidence_quote":"…"}]}'
    )
    return "\n".join(lines)


def understand_edges(
    client,
    phases: list[dict[str, Any]],
    quotes_by_ref: dict[str, str],
) -> list[dict[str, Any]]:
    """Ask the model for narrative edges. Returns a list of proposal dicts.

    Malformed output yields an empty list (caller defers, never fabricates).
    """
    if len(phases) < 2:
        return []
    data = client.complete_json(
        system=_SYSTEM,
        user=_render(phases, quotes_by_ref),
        schema=_SCHEMA,
        temperature=0.1,
    )
    if not isinstance(data, dict):
        return []
    rows = data.get("edges")
    if not isinstance(rows, list):
        # tolerate a couple of aliases without inventing structure
        for key in ("links", "relations", "proposals"):
            if isinstance(data.get(key), list):
                rows = data[key]
                break
        else:
            return []
    return [r for r in rows if isinstance(r, dict)]
