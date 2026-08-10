"""Model-backed pattern reflection (the nightly "dream" pass).

Where episode reflection reads one unit of work, pattern reflection reads a
*window* of activity (a day / week, optionally scoped to a project) via an
:class:`~twin.cognize.services.analysis_dossier.AnalysisDossier` and mines for
persistent, cross-domain patterns: preferences, procedures/habits and standing
constraints revealed by repeated choices — the "Edu writes ``if`` without
parentheses" / "Edu applies DRY on project X" class of memory, and equally the
non-code kind (how Edu runs meetings, replies on Slack, prioritizes).

Every claim still lands as a MemoryCandidate for human review. A parse/model
failure defers (never fabricates).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from twin.config import ALL_DOMAINS
from twin.store.models import MemoryType

if TYPE_CHECKING:
    from ..analysis_dossier import AnalysisDossier
    from ..episode_reflect import TrajectoryClaim

PROMPT_VERSION = "1"
SCHEMA_VERSION = "1"

_MEMORY_TYPES = [t.value for t in MemoryType]
_DOMAINS = list(ALL_DOMAINS)

_SYSTEM = """\
You are the user's advisor. You are given a DOSSIER covering a WINDOW of the
user's activity across senses (GitHub, Slack, meetings, docs, sessions),
optionally scoped to one project. Your task is to notice DURABLE PATTERNS the
user would not bother to state, but that a good chief-of-staff would remember.

Look for, across the window (multi-domain, not only code):
- preferences revealed by REPEATED choices (style, tooling, phrasing, workflow,
  how they run meetings, how they reply);
- procedures / habits: the way they consistently do a recurring thing;
- standing constraints they keep enforcing before they accept work;
- relationship / communication patterns with recurring people.

Rules:
- A pattern needs REPETITION or clear standing intent — not a single event.
  Two or more independent signals in the window, or one signal that plainly
  restates an established stance, is the bar.
- EXTEND the established STANCE; never restate what is already confirmed.
- Do not narrate process ("worked on X then Y"). Name the durable trait.
- Ground each pattern in concrete evidence from the dossier.
- Read each sense through its LENS. Prefer zero patterns over a shallow one.

Catalog — pick the best Memory type and domain per pattern:
- types: """ + " | ".join(_MEMORY_TYPES) + """
- domains: """ + " | ".join(_DOMAINS) + """

Respond with JSON only, matching the schema. Field names MUST be exactly:
- claims: array of objects
- type: one of the Memory types above (usually preference | procedure | constraint)
- domain: one of the domains above
- title, summary: strings
- evidence_quotes: array of strings (optional)
- confidence: number in [0,1] (optional)
Do NOT emit prose or alternate field names.
"""

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": _MEMORY_TYPES},
                    "domain": {"type": "string", "enum": _DOMAINS},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "evidence_quotes": {
                        "type": "array", "items": {"type": "string"},
                    },
                    "confidence": {"type": "number"},
                },
                "required": ["type", "title", "summary"],
            },
        },
    },
    "required": ["claims"],
}


def _render(dossier: "AnalysisDossier") -> str:
    lines = [
        "Mine the following window for durable, repeated patterns.",
        "",
        dossier.render(),
        "",
        "Return {\"claims\":[]} unless a pattern is supported by repetition or "
        "a clear standing stance. Prefer preferences / procedures / "
        "constraints. Never restate the established STANCE.",
    ]
    return "\n".join(lines)


def reflect_patterns_with_model(
    client, dossier: "AnalysisDossier",
) -> list["TrajectoryClaim"]:
    from ..episode_reflect import TrajectoryClaim

    data = client.complete_json(
        system=_SYSTEM,
        user=_render(dossier),
        schema=_SCHEMA,
        temperature=0.2,
    )
    raw_claims = data.get("claims") if isinstance(data, dict) else None
    if not isinstance(raw_claims, list):
        return []

    out: list[TrajectoryClaim] = []
    valid_from = dossier.focus.time_from
    for rc in raw_claims:
        if not isinstance(rc, dict) or not rc.get("title"):
            continue
        domain = str(rc.get("domain") or "technical")
        if domain not in ALL_DOMAINS:
            domain = "technical"
        mem_type = str(rc.get("type") or "preference")
        if mem_type not in _MEMORY_TYPES:
            mem_type = "preference"
        out.append(TrajectoryClaim(
            type=mem_type,
            domain=domain,
            title=str(rc["title"])[:200],
            summary=str(rc.get("summary") or ""),
            evidence_quotes=[
                str(q) for q in (rc.get("evidence_quotes") or []) if q
            ][:6],
            valid_from=valid_from,
            valid_until=None,
            confidence=float(rc.get("confidence") or 0.5),
            canonical_claim={
                "subject": dossier.focus.project_id or dossier.focus.vault_id,
                "predicate": "pattern",
                "object": str(rc["title"])[:120],
            },
            twin_influenced=True,
        ))
    return out
