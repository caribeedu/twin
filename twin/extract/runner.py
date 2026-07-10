"""Extraction pipeline: PII mask → extractor → classification checks →
dedupe → persist (memory + entities + relations + evidence + embedding).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import ids
from ..config import Config
from ..db import Database
from ..dedupe import check as dedupe_check
from ..embeddings import Embedder, to_blob
from ..models import Evidence, MemoryItem, Relation, Source
from ..pii import mask
from . import heuristic, llm
from .schema import ExtractedMemory, ExtractionResult


@dataclass
class ExtractReport:
    source_id: str
    extractor: str = ""
    inserted: list[str] = field(default_factory=list)
    duplicates: int = 0
    flagged_for_review: int = 0
    pii_findings: int = 0


def _choose_extractor(cfg: Config) -> str:
    if cfg.extractor == "llm":
        return "llm"
    if cfg.extractor == "heuristic":
        return "heuristic"
    return "llm" if llm.available() else "heuristic"


def _run_extractor(cfg: Config, source: Source) -> tuple[ExtractionResult, int]:
    masked_text, findings = mask(source.raw_text)
    which = _choose_extractor(cfg)
    if which == "llm":
        try:
            text = masked_text if cfg.mask_pii_before_cloud else source.raw_text
            return llm.extract(source, text, model=cfg.extraction_model), len(findings)
        except Exception as exc:  # credential/network/API error → degrade gracefully
            import sys

            print(f"twin: LLM extraction failed ({exc!r}); falling back to heuristic",
                  file=sys.stderr)
    return heuristic.extract(source), len(findings)


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


def extract_source(db: Database, cfg: Config, embedder: Embedder, source: Source) -> ExtractReport:
    report = ExtractReport(source_id=source.id)
    result, pii_count = _run_extractor(cfg, source)
    report.extractor = result.extractor
    report.pii_findings = pii_count

    for extracted in result.memories:
        extracted = extracted.normalized()
        dedupe_text = f"{extracted.title}\n{extracted.summary}"
        verdict = dedupe_check(db, embedder, extracted.type, dedupe_text)

        if verdict.action == "duplicate" and verdict.existing_id:
            # New evidence for an existing memory, not a new memory.
            db.insert_evidence(Evidence(
                id=ids.evidence_id(),
                memory_id=verdict.existing_id,
                source_id=source.id,
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
            valid_from=extracted.valid_from or (source.created_at or None),
            payload=extracted.payload,
            needs_review=review_reason is not None,
            review_reason=review_reason,
            entities=extracted.entities,
        )
        db.insert_memory(mem)
        db.insert_evidence(Evidence(
            id=ids.evidence_id(),
            memory_id=mem.id,
            source_id=source.id,
            quote=extracted.evidence_quote or extracted.summary,
        ))
        vector = embedder.embed(dedupe_text)
        db.store_embedding(mem.id, "memory", embedder.name, to_blob(vector), embedder.dim)

        if verdict.action == "review" and verdict.existing_id:
            db.insert_relation(Relation(
                id=ids.relation_id(),
                subject_id=mem.id, predicate="related_to", object_id=verdict.existing_id,
                memory_id=mem.id,
            ))
        for rel in extracted.relations:
            subj = db.upsert_entity(rel.subject)
            obj = db.upsert_entity(rel.object)
            db.insert_relation(Relation(
                id=ids.relation_id(),
                subject_id=subj.id, predicate=rel.predicate, object_id=obj.id,
                memory_id=mem.id, valid_from=mem.valid_from,
            ))

        report.inserted.append(mem.id)
        if review_reason:
            report.flagged_for_review += 1

    return report


def extract_pending(db: Database, cfg: Config, embedder: Embedder) -> list[ExtractReport]:
    """Extract every source that has no evidence pointing at it yet."""
    reports = []
    for source in db.list_sources():
        row = db.conn.execute(
            "SELECT COUNT(*) AS n FROM evidence WHERE source_id = ?", (source.id,)
        ).fetchone()
        if row["n"] == 0:
            reports.append(extract_source(db, cfg, embedder, source))
    return reports
