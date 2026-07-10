"""Extraction pipeline: PII mask → extractor → classification checks →
dedupe → persist (memory + entities + relations + evidence + embedding).

Extractor selection (``TWIN_EXTRACTOR``):
    auto      → ollama (local, if reachable) → heuristic
    ollama    → force local LLM (falls back to heuristic on failure)
    heuristic → rule-based only, fully offline
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

from .. import ids
from ..config import Config
from ..judgment.pii import mask
from ..memory.embeddings import Embedder
from ..memory.models import Evidence, MemoryItem, Relation
from ..memory.store.base import MemoryStore
from ..sensory.percept import Percept
from .dedupe import check as dedupe_check
from .extractors import heuristic as heuristic_extractor
from .extractors import ollama as ollama_extractor
from .schema import ExtractedMemory, ExtractionResult


@dataclass
class ExtractReport:
    percept_id: str
    extractor: str = ""
    inserted: list[str] = field(default_factory=list)
    duplicates: int = 0
    flagged_for_review: int = 0
    pii_findings: int = 0


def _choose_extractor(cfg: Config) -> str:
    if cfg.extractor in ("ollama", "heuristic"):
        return cfg.extractor
    # auto: local LLM first, rules as offline fallback
    if ollama_extractor.available(cfg.ollama_url):
        return "ollama"
    return "heuristic"


def _run_extractor(cfg: Config, percept: Percept) -> tuple[ExtractionResult, int]:
    masked_text, findings = mask(percept.content)
    which = _choose_extractor(cfg)
    try:
        if which == "ollama":
            # local model → nothing leaves the machine; mask anyway for
            # defense in depth (extraction output should never carry PII)
            return ollama_extractor.extract(
                percept, masked_text, base_url=cfg.ollama_url, model=cfg.ollama_model
            ), len(findings)
    except Exception as exc:  # server down / network error → degrade gracefully
        print(f"twin: {which} extraction failed ({exc!r}); falling back to heuristic",
              file=sys.stderr)
    return heuristic_extractor.extract(percept), len(findings)


def _needs_review(cfg: Config, mem: ExtractedMemory) -> str | None:
    if mem.confidence < cfg.review_confidence_threshold:
        return f"low confidence ({mem.confidence:.2f})"
    if mem.sensitivity in ("private", "restricted"):
        return f"sensitivity {mem.sensitivity}"
    if mem.type in ("belief", "procedure"):
        return "judgment-adjacent memory type"
    if mem.domain not in ("work", "technical", "personal_preferences", "assistant_preferences"):
        return f"non-MVP domain {mem.domain}"
    return None


def extract_percept(store: MemoryStore, cfg: Config, embedder: Embedder,
                    percept: Percept) -> ExtractReport:
    report = ExtractReport(percept_id=percept.id)
    result, pii_count = _run_extractor(cfg, percept)
    report.extractor = result.extractor
    report.pii_findings = pii_count

    for extracted in result.memories:
        extracted = extracted.normalized()
        dedupe_text = f"{extracted.title}\n{extracted.summary}"
        verdict = dedupe_check(store, embedder, extracted.type, dedupe_text)

        if verdict.action == "duplicate" and verdict.existing_id:
            # New evidence for an existing memory, not a new memory.
            store.insert_evidence(Evidence(
                id=ids.evidence_id(),
                memory_id=verdict.existing_id,
                percept_id=percept.id,
                quote=extracted.evidence_quote or extracted.summary,
            ))
            report.duplicates += 1
            continue

        review_reason = _needs_review(cfg, extracted)
        if verdict.action == "review" and verdict.existing_id:
            review_reason = review_reason or (
                f"similar to {verdict.existing_id} (cos={verdict.similarity:.2f}) — update or contradiction?"
            )

        mem = MemoryItem(
            id=ids.memory_id(),
            type=extracted.type,  # type: ignore[arg-type]
            title=extracted.title,
            summary=extracted.summary,
            domain=extracted.domain,
            sensitivity=extracted.sensitivity,  # type: ignore[arg-type]
            confidence=extracted.confidence,
            valid_from=extracted.valid_from or (percept.occurred_at or None),
            payload=extracted.payload,
            needs_review=review_reason is not None,
            review_reason=review_reason,
            entities=extracted.entities,
        )
        store.insert_memory(mem)
        store.insert_evidence(Evidence(
            id=ids.evidence_id(),
            memory_id=mem.id,
            percept_id=percept.id,
            quote=extracted.evidence_quote or extracted.summary,
        ))
        store.store_embedding(mem.id, "memory", embedder.name, embedder.embed(dedupe_text))

        if verdict.action == "review" and verdict.existing_id:
            store.insert_relation(Relation(
                id=ids.relation_id(),
                subject_id=mem.id, predicate="related_to", object_id=verdict.existing_id,
                memory_id=mem.id,
            ))
        for rel in extracted.relations:
            subj = store.upsert_entity(rel.subject)
            obj = store.upsert_entity(rel.object)
            store.insert_relation(Relation(
                id=ids.relation_id(),
                subject_id=subj.id, predicate=rel.predicate, object_id=obj.id,
                memory_id=mem.id, valid_from=mem.valid_from,
            ))

        report.inserted.append(mem.id)
        if review_reason:
            report.flagged_for_review += 1

    return report


def extract_pending(store: MemoryStore, cfg: Config, embedder: Embedder) -> list[ExtractReport]:
    """Extract every percept no memory has been derived from yet."""
    return [
        extract_percept(store, cfg, embedder, percept)
        for percept in store.unprocessed_percepts()
    ]
