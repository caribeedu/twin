"""Non-interpreting offline mock — a deterministic CI stand-in for the LLM.

This is the honest counterpart of the ``hash`` embedder: it produces
deterministic, structurally valid output with **no semantic content of its
own**. It does NOT classify meaning — there is no lexical analysis anywhere in
here. Every sentence becomes a provisional ``fact``/``statement`` observation,
grounded verbatim in the source and born needing review. Category, cognitive
act and confidence are FIXED mock values, not decisions derived from the text
— establishing what a Percept actually *means* (decision vs proposal, its
domain, entities, confidence, attribution) is the cognitive interpreter's job,
and a test that asserts meaning must supply that interpretation itself (via
``set_interpreter_override``), exactly as it would record a golden LLM output.

Selected with ``TWIN_EXTRACTOR=echo``. Used only so tests that merely need
"some grounded memory exists" (retrieval, packs, metrics, connector plumbing)
run without a model — never to stand in for real interpretation quality.
"""

from __future__ import annotations

import re

from twin.config import Config
from twin.sense.sensory.percept import Percept
from .schema import (
    CognitiveAct,
    InterpretationResult,
    InterpretationStatus,
    InterpretedItem,
)

PROMPT_VERSION = "echo-v1"
SCHEMA_VERSION = "1"
ECHO_CONFIDENCE = 0.5   # fixed — never derived from the content

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def interpret(percept: Percept, masked_text: str, cfg: Config) -> InterpretationResult:
    items: list[InterpretedItem] = []
    seen: set[str] = set()
    for raw in _SENTENCE_SPLIT.split(masked_text or ""):
        sentence = raw.strip()
        if not 15 <= len(sentence) <= 600:
            continue
        key = sentence.lower()
        if key in seen:
            continue
        seen.add(key)
        title = sentence if len(sentence) <= 90 else sentence[:87] + "..."
        items.append(InterpretedItem(
            claim_type="fact",                 # the null category — no analysis
            cognitive_act=CognitiveAct.statement,
            title=title, summary=sentence,
            domain=percept.privacy_hints.get(
                "domain_hint",
                "technical" if percept.percept_type == "document" else "work"),
            sensitivity="internal",
            confidence=ECHO_CONFIDENCE,         # fixed mock value
            evidence_span=sentence,             # verbatim slice → grounded
        ))
    status = (InterpretationStatus.interpreted if items
              else InterpretationStatus.empty)
    return InterpretationResult(
        items=items, status=status, interpreter="echo", model="echo",
        prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION,
    )


def available(cfg: Config) -> bool:
    return True
