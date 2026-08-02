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

PROMPT_VERSION = "8"
SCHEMA_VERSION = "1"

_MEMORY_TYPES = [t.value for t in MemoryType]
_DOMAINS = list(ALL_DOMAINS)

_SYSTEM = """\
You are an advisor, not a parrot. You synthesize DURABLE memories from a unit
of work across sources, using a compiled dossier.
You are given:
- an episode's ordered phases (goal → decision → execution → outcome),
- narrative edges,
- a DOSSIER: dense PRIMARY evidence, CROSS-SENSE soft neighbors (same
  project/time/people/topic but NOT explicitly linked), NEIGHBOR episodes,
  RELATED memories (confirmed / candidate / rejected), the user's established
  STANCE, per-sense LENSES, and COMPILER HINTS.

Read each sense through its LENS: what matters in a GitHub PR (decisions,
trade-offs, style/DRY, pivots) is not what matters in Slack (commitments,
symptoms, tone) or a meeting (decisions, owners, open questions).

Your job is NOT to narrate GitHub process. Emit a claim ONLY when the evidence
reveals something worth remembering later across domains — a durable
preference, decision, constraint, belief, procedure, relationship fact, task
policy, etc.

Prefer, in order:
1. CROSS-SENSE synthesis: connect a symptom/request in one sense to work in
   another when project/time/topic align — e.g. 'PR #7 resolved the payments
   double-charge that ops reported in Slack by adding webhook idempotency'.
   The COMPILER HINTS point at exactly these unlinked pairs;
2. a durable pivot grounded in evidence: earlier approach superseded
   (e.g. 'intended Kafka, then chose SQS for operational cost');
3. a durable preference/procedure revealed by choices (style, DRY, workflow)
   that extends — not restates — the established STANCE;
4. a contradiction across sources or vs related context;
5. a goal/decision that closed as a distinct outcome with lasting force.

Use related context:
- confirmed / STANCE: treat as established — extend it, never restate it;
- candidate: suggestive only — do not treat as fact;
- rejected: negative evidence — do not re-propose the same claim;
- cross_sense: a soft neighbor, not a proven link — judge whether it truly
  relates before connecting it, and cite it when you do;
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

Type discriminators (do not confuse these):
- decision: a CHOICE among alternatives that commits future work
  (picked X over Y, assigned an owner, chose a version/stack). Not every
  resolved outcome is a decision.
- constraint: a hard requirement / gate that shapes what is allowed
  (must have X to launch) — keep as constraint even when later fulfilled.
- event: a completed occurrence with lasting significance when it is not a
  standing rule (blocker resolved, feature shipped, launch gate cleared).
- fact: a durable state of the world / mechanism (how persistence works).
- Prefer event or constraint over decision for "requirement fulfilled /
  resolved by PR #N" claims that do not name an explicit choice.

When quoting people or channels, use the human labels already in the brief
(@Name, #channel) — never invent or echo bare Slack ids (U… / C…).

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
- cross_sense_refs: the exact ref(s) (e.g. 'slack:channel_message:123') from the
  CROSS-SENSE block that this claim genuinely connects — list one ONLY when the
  claim actually links that neighbor to the primary work. These become
  independent corroborating evidence, so do not pad them. (optional)
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
                    "cross_sense_refs": {
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


def _coerce_claim_type(mem_type: str, *, title: str, summary: str) -> str:
    """Fix common mis-labels: fulfilled gates are not decisions."""
    if mem_type != "decision":
        return mem_type
    blob = f"{title}\n{summary}".lower()
    choice_markers = (
        "chose", "chosen", "decided", "picked", "selected", "opted",
        "over ", "instead of", "rather than", "prefer",
    )
    if any(m in blob for m in choice_markers):
        return mem_type
    resolved_markers = (
        "resolved by", "fulfilled", "blocker", "launch gate",
        "requirement", "constraint", "cannot launch", "hard gate",
        "cleared by", "landed",
    )
    if any(m in blob for m in resolved_markers):
        if any(m in blob for m in ("must", "needs to", "required", "cannot launch", "gate")):
            return "constraint"
        return "event"
    return mem_type


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

    dossier = getattr(brief, "dossier", None)
    if dossier is not None:
        # The compiler already assembled dense primary + cross-sense + related
        # + lenses + hints; render it verbatim as the analyst's briefing.
        lines.append("=== DOSSIER ===")
        lines.append(dossier.render())
    else:
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
        "If the evidence is near-paraphrase across phases AND nothing durable "
        "or cross-sense emerges, return {\"claims\":[]}. Prefer durable "
        "preferences/decisions/constraints and cross-sense synthesis over "
        "PR-process narration. When a COMPILER HINT or session_artifact points "
        "at a real link, prefer a claim that names that durable stance."
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
    dossier = getattr(brief, "dossier", None)
    cross_refs = {
        b.ref for b in getattr(dossier, "cross_sense", [])
    } if dossier is not None else set()
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
        mem_type = _coerce_claim_type(
            mem_type,
            title=str(rc.get("title") or ""),
            summary=str(rc.get("summary") or ""),
        )
        used_related = [
            str(i) for i in (rc.get("related_memory_ids") or [])
            if i in related_ids
        ]
        used_cross = [
            str(r) for r in (rc.get("cross_sense_refs") or [])
            if r in cross_refs
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
            cross_sense_refs=used_cross,
            canonical_claim={
                "subject": brief.project_id or brief.title,
                "predicate": "trajectory",
                "object": str(rc["title"])[:120],
            },
            twin_influenced=True,
        ))
    return out
