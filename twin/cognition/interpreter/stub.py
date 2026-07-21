"""Deterministic offline interpreter — the CI/test stand-in for the LLM.

Analogous to the hash embedder: no model, no network, fully reproducible. It
reuses the conservative lexical detector to find candidate spans and emits
*grounded* ``InterpretedItem``s (evidence span = the detected sentence, which
is a verbatim slice of the text it read), so the real interpreter path —
grounding validation, cognitive-act governance, source policy, dedupe,
review — is exercised end to end.

This is a legitimate interpreter double, not the ``heuristic`` mode: heuristic
mode produces only detection signals and never a memory. The stub is selected
with ``TWIN_EXTRACTOR=stub`` (the test suite's default).
"""

from __future__ import annotations

from ...config import Config
from ...sensory.percept import Percept
from ..extractors.heuristic import scan
from .schema import (
    CognitiveAct,
    InterpretationResult,
    InterpretationStatus,
    InterpretedItem,
)

PROMPT_VERSION = "stub-v1"
SCHEMA_VERSION = "1"

# candidate category → (memory_type, cognitive_act)
_MAP = {
    "decision": ("decision", CognitiveAct.decision),
    "rejected_alternative": ("rejected_alternative", CognitiveAct.decision),
    "task": ("task", CognitiveAct.statement),
    "preference": ("preference", CognitiveAct.statement),
    "constraint": ("constraint", CognitiveAct.statement),
}


def interpret(percept: Percept, masked_text: str, cfg: Config) -> InterpretationResult:
    default_domain = percept.privacy_hints.get(
        "domain_hint",
        "technical" if percept.percept_type == "document" else "work",
    )
    items: list[InterpretedItem] = []
    for hit in scan(masked_text):
        mem_type, act = _MAP.get(hit.kind, ("fact", CognitiveAct.statement))
        title = hit.span if len(hit.span) <= 90 else hit.span[:87] + "..."
        items.append(InterpretedItem(
            memory_type=mem_type,
            cognitive_act=act,
            title=title,
            summary=hit.span,
            domain=default_domain,
            sensitivity="internal",
            confidence=hit.confidence,   # deliberately low → review-bound
            entities=hit.entities,
            evidence_span=hit.span,       # verbatim from masked_text → grounded
        ))
    status = (InterpretationStatus.interpreted if items
              else InterpretationStatus.empty)
    return InterpretationResult(
        items=items, status=status, interpreter="stub", model="stub",
        prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION,
    )


def available(cfg: Config) -> bool:
    return True
