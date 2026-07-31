"""Model-backed episode reflection (hippocampus_consolidate).

Given an :class:`EpisodeBrief`, ask a chat model to name the trajectory the
phase arc implies (e.g. "intended Kafka, then chose SQS"). The model receives
already-derived structure, denser member quotes, and related memories from
search (confirmed / candidate / rejected). It returns 0..N claims. Every claim
still lands as a MemoryCandidate for human review — the model never confirms
anything. A parse/model failure defers (never fabricates).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...config import ALL_DOMAINS
from ...memory.models import MemoryType

if TYPE_CHECKING:  # avoid import cycle at module load
    from ..episode_reflect import EpisodeBrief, TrajectoryClaim

PROMPT_VERSION = "6"
SCHEMA_VERSION = "1"

_MEMORY_TYPES = [t.value for t in MemoryType]
_DOMAINS = list(ALL_DOMAINS)

_SYSTEM = """\
You synthesize DURABLE memories from a unit of work across sources.
You are given:
- an episode's ordered phases (goal → decision → execution → outcome),
- narrative edges,
- denser member quotes (PR bodies, commits, chat/Slack — not titles alone),
- RELATED context: vault memories (confirmed / candidate / rejected) and
  open-session artifacts (live Cursor/chat intent not yet extracted).

Your job is NOT to narrate GitHub process. Emit a claim ONLY when the arc
(plus related context) reveals something worth remembering later across
domains — a durable preference, decision, constraint, belief, procedure,
relationship fact, task policy, etc.

Prefer, in order:
1. a durable pivot grounded in evidence: earlier approach superseded
   (e.g. 'intended Kafka, then chose SQS for operational cost');
2. linking episode evidence to RELATED context (open-session intent,
   Slack/chat notes, prior decisions, rejected alternatives) that the
   version sources alone omit;
3. a contradiction across sources or vs related context;
4. a goal/decision that closed as a distinct outcome with lasting force.

Use related context:
- confirmed: treat as established (still cite episode quotes for new claims);
- candidate: suggestive only — do not treat as fact;
- rejected: negative evidence — do not re-propose the same claim;
- session_artifact: live human/assistant intent from an open session —
  high-value for linking chat→PR, but still unconfirmed.

Hard negatives — return an empty claims array for these:
- restating that a pull request was followed by its commit when both say
  the same thing in different words;
- 'the goal was executed' / 'PR motivated the commit' tautologies;
- meta-PR process narration: 'scope narrowed to blockers', 'landing commit
  focused on X', 'addressed PR blockers', 'PR framed A; commits did B'
  when that only describes how this PR landed, not a durable stance;
- restating a single commit message or PR title with no trajectory;
- anything atomic extract would already say from one source alone;
- re-stating related context without new evidence from this episode.

Catalog — pick the best Memory type and domain for each claim:
- types: """ + " | ".join(_MEMORY_TYPES) + """
- domains: """ + " | ".join(_DOMAINS) + """

Ground every claim in the provided quotes and/or related ids.
Prefer zero claims over a shallow or process-only claim. You never confirm
anything; these are candidates for human review.

Respond with JSON only, matching the schema. Field names MUST be exactly:
- claims: array of objects
- type: one of the Memory types above
- domain: one of the domains above
- title, summary: strings
- evidence_quotes: array of strings (optional)
- related_memory_ids: ids from RELATED context you used (optional)
- from_phase_key / to_phase_key: phase_key strings from the input (optional)
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
                    "related_memory_ids": {
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
    lines.append("Quotes by member (title + body; look for intent shifts):")
    for ref, q in brief.quotes_by_ref.items():
        lines.append(f"  {ref}: {q}")
    lines.append("")
    lines.append(
        "RELATED context (vault memories + open-session artifacts — use as "
        "context; do not restate without new episode evidence):"
    )
    if brief.related_memories:
        for rm in brief.related_memories:
            lines.append(
                f"  [{rm.get('status')}] {rm.get('id')} "
                f"type={rm.get('type')} domain={rm.get('domain')}: "
                f"{rm.get('title')} — {rm.get('summary')}"
            )
    else:
        lines.append("  (none retrieved)")
    lines.append("")
    lines.append(
        "If quotes across phases are near-paraphrases AND related context "
        "adds nothing durable, return {\"claims\":[]}. Prefer durable "
        "preferences/decisions/constraints over PR-process narration. "
        "When session_artifact intent matches the episode, prefer a claim "
        "that names that durable stance."
    )
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
    related_ids = {rm.get("id") for rm in brief.related_memories if rm.get("id")}
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
        domain = str(rc.get("domain") or "technical")
        if domain not in ALL_DOMAINS:
            domain = "technical"
        mem_type = str(rc.get("type") or "decision")
        if mem_type not in _MEMORY_TYPES:
            mem_type = "decision"
        used_related = [
            str(i) for i in (rc.get("related_memory_ids") or [])
            if i in related_ids
        ]
        out.append(TrajectoryClaim(
            type=mem_type,
            domain=domain,
            title=str(rc["title"])[:200],
            summary=str(rc.get("summary") or ""),
            evidence_quotes=[
                str(q) for q in (rc.get("evidence_quotes") or []) if q
            ][:6],
            related_memory_ids=used_related,
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
