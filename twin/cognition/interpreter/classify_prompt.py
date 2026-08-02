"""Amygdala stage — cognitive role + salience classification of episode members.

Replaces lexical type/keyword rules: a chat model reads each member's type,
time and content excerpt and assigns a role in the work arc
(``goal | decision | execution | outcome | other``) plus a salience score.
Output is evidence-grounded structure, never Memory or Judgment.
"""

from __future__ import annotations

from typing import Any

PROMPT_VERSION = "2"
SCHEMA_VERSION = "1"

_SYSTEM = """\
You classify the cognitive role each artifact plays in a unit of work.
For every member you receive (an issue, pull request, commit, message, etc.)
assign exactly one role:
- goal: frames intent, a problem to solve, a question to answer;
- decision: chooses or reconsiders an approach (including a pivot away from
  an earlier choice);
- execution: carries out the work (commits, builds, edits);
- outcome: closes the arc (merged, shipped, released, resolved);
- other: none of the above.

Also give a salience score in [0,1]: how decision-relevant this member is for
understanding the trajectory. Judge from the actual content, not the artifact
type alone — a commit whose message reconsiders an approach is a decision, a
PR that only renames a file is execution.

Respond with JSON only, matching the schema. Field names MUST be exactly:
- roles: array of objects
- ref: the member ref string you were given (copy it verbatim)
- kind: one of goal | decision | execution | outcome | other
- salience: number in [0,1] (optional but preferred)
Do NOT emit "members", "classification", "type", "role", or prose/bullets.
Return one entry per member ref you were given, nothing invented.
"""

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "roles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": [
                            "goal", "decision", "execution", "outcome", "other",
                        ],
                    },
                    "salience": {"type": "number"},
                },
                "required": ["ref", "kind"],
            },
        },
    },
    "required": ["roles"],
}

_KIND_ALIASES = {
    "goal": "goal",
    "decision": "decision",
    "execution": "execution",
    "outcome": "outcome",
    "other": "other",
    "classification": None,  # not a kind
}


def _render(members: list[dict[str, Any]]) -> str:
    lines = ["Members (in time order):", ""]
    for m in members:
        lines.append(
            f"- ref={m.get('ref')} type={m.get('external_type')} "
            f"at={m.get('occurred_at') or '?'}\n    {m.get('excerpt') or ''}"
        )
    lines.append("")
    lines.append(
        'Return JSON: {"roles":[{"ref":"…","kind":"goal|decision|execution|'
        'outcome|other","salience":0.0}]} — one entry per ref above.'
    )
    return "\n".join(lines)


def _rows_from_payload(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Accept the canonical ``roles`` key; tolerate a few common aliases."""
    for key in ("roles", "members", "classifications", "items"):
        rows = data.get(key)
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


def _kind_of(row: dict[str, Any]) -> str:
    for key in ("kind", "classification", "role", "type", "label"):
        val = row.get(key)
        if isinstance(val, str) and val.lower() in (
            "goal", "decision", "execution", "outcome", "other",
        ):
            return val.lower()
    return "other"


def classify_members(
    client, members: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Ask the model to classify members. Returns ``ref → {kind, salience}``.

    Only refs the model returns that were in the input are kept. A malformed
    response yields an empty map (the caller then defers — never fabricates).
    """
    if not members:
        return {}
    data = client.complete_json(
        system=_SYSTEM,
        user=_render(members),
        schema=_SCHEMA,
        temperature=0.1,
    )
    if not isinstance(data, dict):
        return {}
    rows = _rows_from_payload(data)
    known = {m.get("ref") for m in members}
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        ref = r.get("ref")
        if ref not in known:
            continue
        out[ref] = {
            "kind": _kind_of(r),
            "salience": r.get("salience"),
        }
    return out
