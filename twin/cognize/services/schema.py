"""Shared output schema for all extractors (LLM or heuristic)."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from twin.config import ALL_DOMAINS

CLAIM_TYPES = [
    "event", "fact", "decision", "preference", "belief",
    "task", "procedure", "relationship", "communication_act", "constraint",
]
SENSITIVITIES = ["public", "internal", "private", "restricted"]


class ExtractedRelation(BaseModel):
    subject: str
    predicate: str
    object: str


class ExtractedClaim(BaseModel):
    type: str
    title: str
    summary: str
    domain: str = "technical"
    sensitivity: str = "internal"
    confidence: float = 0.5
    valid_from: Optional[str] = None
    entities: list[str] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)
    evidence_quote: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)

    def normalized(self) -> "ExtractedClaim":
        if self.type not in CLAIM_TYPES:
            self.type = "fact"
        # Preserve the explicit governance remap 'unknown'; other invalids
        # still fall back to technical for legacy extractor paths.
        if self.domain not in ALL_DOMAINS and self.domain != "unknown":
            self.domain = "technical"
        if self.sensitivity not in SENSITIVITIES:
            self.sensitivity = "internal"
        self.confidence = max(0.0, min(1.0, self.confidence))
        return self


class ExtractionResult(BaseModel):
    claims: list[ExtractedClaim] = Field(default_factory=list)
    extractor: str = "unknown"

    @classmethod
    def from_llm_payload(cls, data: dict, extractor: str = "unknown") -> "ExtractionResult":
        raw = data.get("claims") or []
        return cls(
            claims=[ExtractedClaim(**m).normalized() for m in raw],
            extractor=extractor,
        )

# JSON schema handed to the LLM via structured outputs.
EXTRACTION_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": CLAIM_TYPES},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "domain": {"type": "string", "enum": ALL_DOMAINS},
                    "sensitivity": {"type": "string", "enum": SENSITIVITIES},
                    "confidence": {"type": "number"},
                    "valid_from": {"type": ["string", "null"]},
                    "entities": {"type": "array", "items": {"type": "string"}},
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
                    "evidence_quote": {"type": "string"},
                },
                "required": [
                    "type", "title", "summary", "domain", "sensitivity",
                    "confidence", "entities", "relations", "evidence_quote",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["claims"],
    "additionalProperties": False,
}
