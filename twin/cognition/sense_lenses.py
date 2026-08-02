"""Sense lenses — what an analyzer should look for per connector source.

The Analysis Context Compiler labels every evidence blob with a ``sense``
(github / slack / meeting / session / …) and injects the matching *lens* into
the reflect/pattern prompt. A lens is not a separate LLM extractor yet — it is
a short, source-specific checklist that tells the single analyzer model what is
worth remembering when it reads that kind of evidence.

This materializes "each sense is analyzed differently" **in the analyzer's
input**, without multiplying pipelines.
"""

from __future__ import annotations

from typing import Any, Optional

# sense -> ordered "look for" prompts. Kept short; the analyzer still decides.
_LENSES: dict[str, list[str]] = {
    "github": [
        "technical decisions and the trade-offs behind them",
        "coding style / conventions (DRY, naming, formatting) applied by choice",
        "pivots: an earlier approach superseded by a later one",
        "constraints or gates the author insists on before landing work",
    ],
    "slack": [
        "commitments, promises and pending follow-ups (owners + due)",
        "informal decisions reached in conversation",
        "problems / symptoms reported that later work may resolve",
        "tone and working-relationship signals",
    ],
    "meeting": [
        "decisions made on the call and who owns the follow-up",
        "open questions left unresolved",
        "problems or blockers raised out loud",
        "agreements that bind future work",
    ],
    "calendar": [
        "recurring commitments and cadence",
        "who the person regularly meets and about what",
    ],
    "mail": [
        "explicit requests and commitments",
        "decisions or approvals stated in writing",
        "pending items awaiting a reply",
    ],
    "document": [
        "durable design choices and rationale",
        "requirements, constraints and non-goals stated as intent",
    ],
    "session": [
        "explicit stated intent for the current work",
        "preferences said out loud OR revealed by repeated choices",
        "the problem the person is actually trying to solve",
    ],
    "generic": [
        "durable preferences, decisions, constraints or procedures",
        "anything worth remembering later across domains",
    ],
}

# provider / external_type hints -> canonical sense.
_PROVIDER_SENSE: dict[str, str] = {
    "github": "github",
    "slack": "slack",
    "fireflies": "meeting",
    "zoom": "meeting",
    "calendar": "calendar",
    "google_calendar": "calendar",
    "gmail": "mail",
    "outlook": "mail",
    "mail": "mail",
    "folder": "document",
    "documents": "document",
}

_EXTERNAL_TYPE_SENSE: tuple[tuple[str, str], ...] = (
    ("pull_request", "github"),
    ("commit", "github"),
    ("push", "github"),
    ("issue", "github"),
    ("review", "github"),
    ("discussion", "github"),
    ("slack", "slack"),
    ("channel_message", "slack"),
    ("thread_message", "mail"),  # refined below by provider
    ("calendar", "calendar"),
    ("meeting", "meeting"),
    ("transcript", "meeting"),
    ("document", "document"),
)


def look_for(sense: str) -> list[str]:
    """The analyzer checklist for a sense (falls back to ``generic``)."""
    return list(_LENSES.get(sense) or _LENSES["generic"])


def _provider_of(record: Any) -> str:
    sm = getattr(record, "source_metadata", None) or {}
    prov = str(sm.get("provider") or "").lower()
    if prov:
        return prov
    if sm.get("repo"):
        return "github"
    if sm.get("channel_id") or sm.get("team_id"):
        return "slack"
    if sm.get("calendar_event_id"):
        return "calendar"
    return ""


def sense_for_record(record: Any) -> str:
    """Classify a ConnectorRecord into a sense from provider / external_type."""
    prov = _provider_of(record)
    if prov in _PROVIDER_SENSE:
        return _PROVIDER_SENSE[prov]
    et = str(getattr(record, "external_type", "") or "").lower()
    for needle, sense in _EXTERNAL_TYPE_SENSE:
        if needle in et:
            # mail vs slack thread_message: disambiguate by provider family
            if needle == "thread_message" and prov in _PROVIDER_SENSE:
                return _PROVIDER_SENSE[prov]
            return sense
    return "generic"


def lenses_for(senses: list[str]) -> list[dict[str, Any]]:
    """De-duplicated ``[{sense, look_for}]`` blocks for the prompt."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for s in senses:
        key = s if s in _LENSES else "generic"
        if key in seen:
            continue
        seen.add(key)
        out.append({"sense": key, "look_for": look_for(key)})
    return out


def known_senses() -> list[str]:
    return list(_LENSES.keys())


def refine_sense(sense: Optional[str], fallback: str = "generic") -> str:
    return sense if sense in _LENSES else fallback
