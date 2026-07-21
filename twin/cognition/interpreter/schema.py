"""Output schema of the cognitive interpreter (v0.7).

The interpreter is the production path for *semantic identification and
cataloguing*: it decides what a Percept means. Its job is richer than the
old extractor's flat list of memories — every catalogued item carries the
cognitive act that produced it (was this a decision, or merely a proposal?
a fact, or a third-party claim?), who it is attributed to, and a verbatim
evidence span grounding it in the source. Unresolved references and genuine
ambiguities are reported instead of being papered over with a confident
guess.

Deterministic governance downstream (dedupe, source policy, confidentiality
floor, review) is unchanged: this module only describes what the interpreter
is allowed to *say*, never what the system is allowed to *do* with it. The
bridge to :class:`ExtractedMemory` keeps the existing persistence path intact
so v0.7 is an evolution of the pipeline, not a rewrite.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from ...config import ALL_DOMAINS
from ..schema import MEMORY_TYPES, SENSITIVITIES, ExtractedMemory, ExtractedRelation


class CognitiveAct(str, Enum):
    """The speech/thought act the interpreter believes produced the item.

    The distinction has governance teeth: only a ``decision`` is a settled
    choice. A ``proposal`` is a decision not yet taken; a ``question`` or
    ``hypothesis`` is unsettled; an ``opinion`` is a stance, not a fact; a
    ``third_party_claim`` is something a non-author asserted and must be
    attributed, not adopted as the user's own knowledge."""

    statement = "statement"
    question = "question"
    hypothesis = "hypothesis"
    proposal = "proposal"
    decision = "decision"
    opinion = "opinion"
    third_party_claim = "third_party_claim"


# Acts that never stand on their own as settled knowledge — anything the
# interpreter tags with one of these is born needing human review, no matter
# how confident the model was about the *classification*.
UNSETTLED_ACTS = frozenset({
    CognitiveAct.question,
    CognitiveAct.hypothesis,
    CognitiveAct.proposal,
    CognitiveAct.opinion,
    CognitiveAct.third_party_claim,
})

# The interpreter may catalogue a rejected alternative as its own item; it
# maps onto a decision carrying ``payload.rejected_alternative = True`` so the
# memory model needs no new type.
INTERPRETATION_TYPES = MEMORY_TYPES + ["rejected_alternative"]


class InterpretedItem(BaseModel):
    """One catalogued unit of meaning, grounded in the source."""

    memory_type: str
    cognitive_act: CognitiveAct = CognitiveAct.statement
    title: str
    summary: str
    domain: str = "technical"
    sensitivity: str = "internal"
    # The interpreter's confidence in *this classification*, not a trust score.
    confidence: float = 0.5
    # Who the item is attributed to (a speaker/author), grounded in the source.
    attributed_to: Optional[str] = None
    # Whether the attributed speaker is the account owner or a third party.
    speaker_is_owner: Optional[bool] = None
    entities: list[str] = Field(default_factory=list)
    temporal_refs: list[str] = Field(default_factory=list)
    project_ref: Optional[str] = None
    relations: list[ExtractedRelation] = Field(default_factory=list)
    valid_from: Optional[str] = None
    # A verbatim span from the Percept that supports the item. Required in
    # spirit: an item with no evidence span is unsupported and is dropped.
    evidence_span: str = ""
    # References the interpreter could not resolve from the source alone.
    unresolved_references: list[str] = Field(default_factory=list)
    # A short note when the item is genuinely ambiguous (competing readings).
    ambiguity: Optional[str] = None

    def resolved_type(self) -> tuple[str, bool]:
        """(memory_type, is_rejected_alternative) after normalization."""
        if self.memory_type == "rejected_alternative":
            return "decision", True
        if self.memory_type not in MEMORY_TYPES:
            return "fact", False
        return self.memory_type, False

    def to_extracted(self) -> ExtractedMemory:
        """Bridge to the persistence-facing schema, preserving the cognitive
        act, attribution and unresolved references in the payload so nothing
        the interpreter established is lost on the way to storage."""
        mem_type, rejected = self.resolved_type()
        payload: dict[str, Any] = {
            "cognitive_act": self.cognitive_act.value,
            "interpreted": True,
        }
        if rejected:
            payload["rejected_alternative"] = True
        if self.attributed_to:
            payload["attributed_to"] = self.attributed_to
        if self.speaker_is_owner is not None:
            payload["speaker_is_owner"] = self.speaker_is_owner
        if self.temporal_refs:
            payload["temporal_refs"] = self.temporal_refs
        if self.project_ref:
            payload["project_ref"] = self.project_ref
        if self.unresolved_references:
            payload["unresolved_references"] = self.unresolved_references
        if self.ambiguity:
            payload["ambiguity"] = self.ambiguity
        domain = self.domain if self.domain in ALL_DOMAINS else "technical"
        sensitivity = self.sensitivity if self.sensitivity in SENSITIVITIES else "internal"
        return ExtractedMemory(
            type=mem_type,
            title=self.title,
            summary=self.summary,
            domain=domain,
            sensitivity=sensitivity,
            confidence=max(0.0, min(1.0, self.confidence)),
            valid_from=self.valid_from,
            entities=self.entities,
            relations=self.relations,
            evidence_quote=self.evidence_span,
            payload=payload,
        ).normalized()


class InterpretationStatus(str, Enum):
    interpreted = "interpreted"   # produced one or more catalogued items
    empty = "empty"               # interpreted successfully, nothing to catalogue
    deferred = "deferred"         # interpreter unavailable — retry later
    error = "error"               # interpreter reached but failed on this input


class InterpretationResult(BaseModel):
    """What the interpreter produced for one Percept, with execution metadata.

    ``status`` is the execution outcome, never inferred from item count alone:
    an empty result from a healthy interpreter (``empty``) is a settled fact,
    while a ``deferred`` result means the Percept was never understood and must
    be retried — the two must not be conflated (that conflation is exactly what
    v0.7 exists to remove)."""

    items: list[InterpretedItem] = Field(default_factory=list)
    status: InterpretationStatus = InterpretationStatus.interpreted
    interpreter: str = "unknown"          # e.g. "ollama:qwen3.6"
    model: str = ""
    prompt_version: str = ""
    schema_version: str = ""
    unresolved_references: list[str] = Field(default_factory=list)
    detail: str = ""                       # sanitized note (e.g. why deferred)

    @property
    def deferred(self) -> bool:
        return self.status == InterpretationStatus.deferred

    def grounded_items(self) -> list[InterpretedItem]:
        """Only items with a real evidence span survive — an interpreted item
        the model could not ground in the source is an unsupported guess, and
        v0.7 reports the gap instead of storing the guess."""
        return [it for it in self.items if (it.evidence_span or "").strip()]


# JSON schema handed to the local LLM via Ollama structured outputs.
INTERPRETATION_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "memory_type": {"type": "string", "enum": INTERPRETATION_TYPES},
                    "cognitive_act": {
                        "type": "string",
                        "enum": [a.value for a in CognitiveAct],
                    },
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "domain": {"type": "string", "enum": ALL_DOMAINS},
                    "sensitivity": {"type": "string", "enum": SENSITIVITIES},
                    "confidence": {"type": "number"},
                    "attributed_to": {"type": ["string", "null"]},
                    "speaker_is_owner": {"type": ["boolean", "null"]},
                    "entities": {"type": "array", "items": {"type": "string"}},
                    "temporal_refs": {"type": "array", "items": {"type": "string"}},
                    "project_ref": {"type": ["string", "null"]},
                    "relations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "subject": {"type": "string"},
                                "predicate": {"type": "string"},
                                "object": {"type": "string"},
                            },
                            "required": ["subject", "predicate", "object"],
                            "additionalProperties": False,
                        },
                    },
                    "evidence_span": {"type": "string"},
                    "unresolved_references": {
                        "type": "array", "items": {"type": "string"},
                    },
                    "ambiguity": {"type": ["string", "null"]},
                },
                "required": [
                    "memory_type", "cognitive_act", "title", "summary",
                    "domain", "sensitivity", "confidence", "entities",
                    "evidence_span",
                ],
                "additionalProperties": False,
            },
        },
        "unresolved_references": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["items"],
    "additionalProperties": False,
}
