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
from ..config import SENSITIVITY_ORDER, Config
from ..judgment.pii import mask
from ..memory.calibration import calibrated_confidence, load_calibration
from ..memory.embeddings import Embedder
from ..memory.models import Evidence, ExtractorVersion, MemoryItem, Relation
from ..memory.provenance import ensure_artifact_from_percept
from ..memory.store.base import MemoryStore
from ..sensory.percept import Percept
from .dedupe import check as dedupe_check
from .extractors import heuristic as heuristic_extractor
from .extractors import ollama as ollama_extractor
from .quality import analyze_memory
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


def _apply_source_qualification(extracted: ExtractedMemory, percept: Percept,
                                extractor_name: str = "heuristic") -> ExtractedMemory:
    """Source metadata shapes the derived memory:
    trust scales confidence; confidentiality is a sensitivity floor.
    v0.3: also apply source×type calibration matrix."""
    cal = load_calibration()
    extracted.confidence = calibrated_confidence(
        percept.source_sensor,
        extracted.type,
        extracted.confidence,
        source_trust=percept.source_trust,
        evidence_directness=1.0,
        extractor_reliability=1.0 if extractor_name == "ollama" else 0.95,
        calibration=cal,
    )
    order = SENSITIVITY_ORDER
    if order.index(extracted.sensitivity) < order.index(percept.source_confidentiality):
        extracted.sensitivity = percept.source_confidentiality
    return extracted


def _needs_review(cfg: Config, mem: ExtractedMemory, percept: Percept) -> str | None:
    if mem.confidence < cfg.review_confidence_threshold:
        return f"low confidence ({mem.confidence:.2f})"
    if percept.source_trust < cfg.low_trust_threshold:
        return f"low-trust source ({percept.source_trust:.2f})"
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
    artifact_id = ensure_artifact_from_percept(store, percept)

    for extracted in result.memories:
        extracted = _apply_source_qualification(
            extracted.normalized(), percept, extractor_name=result.extractor,
        )
        dedupe_text = f"{extracted.title}\n{extracted.summary}"
        verdict = dedupe_check(store, embedder, extracted.type, dedupe_text)

        if verdict.action == "duplicate" and verdict.existing_id:
            # New evidence for an existing memory — corroboration, not a new memory.
            from ..memory.provenance import attach_corroborating_evidence
            attach_corroborating_evidence(
                store, verdict.existing_id, percept.id,
                extracted.evidence_quote or extracted.summary,
                independence_group=artifact_id or percept.id,
                source_trust=percept.source_trust,
            )
            report.duplicates += 1
            continue

        review_reason = _needs_review(cfg, extracted, percept)
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
            project_id=percept.project_id,
            extractor_version=ExtractorVersion(
                extractor=result.extractor,
                model=cfg.ollama_model if result.extractor == "ollama" else "heuristic",
                prompt_version="extract-v3",
                schema_version="2",
                created_at=percept.ingested_at or "",
            ),
        )
        store.insert_memory(mem)
        store.insert_evidence(Evidence(
            id=ids.evidence_id(),
            memory_id=mem.id,
            percept_id=percept.id,
            quote=extracted.evidence_quote or extracted.summary,
            source_trust=percept.source_trust,
            independence_group=artifact_id or percept.id,
            artifact_id=artifact_id,
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

        # v0.3: quality neighborhood analysis + priority scoring
        try:
            analyze_memory(store, embedder, mem.id, persist=True)
        except Exception:
            pass

        report.inserted.append(mem.id)
        reloaded = store.get_memory(mem.id)
        if reloaded and reloaded.needs_review:
            report.flagged_for_review += 1
        elif review_reason:
            report.flagged_for_review += 1

    return report


def extract_pending(store: MemoryStore, cfg: Config, embedder: Embedder) -> list[ExtractReport]:
    """Extract every percept no memory has been derived from yet."""
    return [
        extract_percept(store, cfg, embedder, percept)
        for percept in store.unprocessed_percepts()
    ]
