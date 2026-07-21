"""Interpretation pipeline (v0.7): quarantine → cognitive interpreter →
classification checks → dedupe → persist (memory + entities + relations +
evidence + embedding).

Mode selection (``TWIN_EXTRACTOR``):
    auto      → cognitive interpreter if the local model is reachable,
                otherwise DEFER (retry later — never fabricate conclusions)
    ollama    → cognitive interpreter; DEFER when the model is unreachable
    heuristic → explicit offline detection mode (rule-based, fully offline);
                its output is detection-only and always review-bound

The load-bearing v0.7 rule: a Percept is understood only when a cognitive
interpreter actually ran. When no interpreter is available the Percept is
recorded ``deferred`` and retried; lexical rules never independently establish
semantic memory types, domains, entities or cognitive confidence in the
production path.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import ids
from ..config import SENSITIVITY_ORDER, Config
from ..judgment.pii import mask
from ..memory.calibration import calibrated_confidence, load_calibration
from ..memory.embeddings import Embedder
from ..memory.models import (
    Evidence, ExtractorVersion, MemoryItem, PerceptInterpretation, Relation,
)
from ..memory.provenance import ensure_artifact_from_percept
from ..memory.store.base import MemoryStore
from ..sensory.percept import Percept
from .dedupe import check as dedupe_check
from .extractors import heuristic as heuristic_extractor
from .interpreter import service as interp_service
from .interpreter.schema import UNSETTLED_ACTS, InterpretationStatus
from .quality import analyze_memory
from .schema import ExtractedMemory

# Cognitive acts (as stored in payload) that are never settled knowledge on
# their own — a proposal is not a decision, a question is not a fact.
_UNSETTLED_ACT_VALUES = frozenset(a.value for a in UNSETTLED_ACTS)
# Non-terminal interpretation states — a deferred/errored Percept produced no
# memory and must be retried.
_RETRYABLE_STATES = frozenset({
    InterpretationStatus.deferred.value, InterpretationStatus.error.value,
})


@dataclass
class ExtractReport:
    percept_id: str
    extractor: str = ""
    inserted: list[str] = field(default_factory=list)
    duplicates: int = 0
    flagged_for_review: int = 0
    pii_findings: int = 0
    policy_dropped: int = 0  # candidates blocked by the source policy (§70)
    deferred: bool = False   # interpreter unavailable — nothing catalogued, retryable
    interpretation_status: str = ""
    unresolved_references: int = 0


@dataclass
class _Interpretation:
    """Normalized interpreter/heuristic output plus execution metadata."""
    memories: list[ExtractedMemory]
    extractor: str
    status: str            # interpreted|empty|deferred|error|heuristic
    model: str
    prompt_version: str
    schema_version: str
    unresolved: int = 0
    pii: int = 0
    detail: str = ""


def _interpret(cfg: Config, percept: Percept) -> _Interpretation:
    """Run the production cognitive interpreter, or — in explicit offline
    mode — the heuristic detector. Never falls back from one to the other:
    when interpreting, an unavailable model DEFERS."""
    masked_text, findings = mask(percept.content)
    pii = len(findings)

    if interp_service.interpreting_mode(cfg):
        result = interp_service.run_interpreter(cfg, percept, masked_text)
        if result.deferred or result.status == InterpretationStatus.error:
            return _Interpretation(
                memories=[], extractor=result.interpreter, status=result.status.value,
                model=result.model, prompt_version=result.prompt_version,
                schema_version=result.schema_version,
                unresolved=len(result.unresolved_references), pii=pii,
                detail=result.detail,
            )
        grounded = result.grounded_items()
        memories = [it.to_extracted() for it in grounded]
        # a healthy interpreter that grounded nothing understood the Percept
        # and found nothing to catalogue — that is 'empty', not 'deferred'
        status = (InterpretationStatus.interpreted.value if grounded
                  else InterpretationStatus.empty.value)
        unresolved = len(result.unresolved_references) + sum(
            len(it.unresolved_references) for it in grounded)
        return _Interpretation(
            memories=memories, extractor=result.interpreter, status=status,
            model=result.model, prompt_version=result.prompt_version,
            schema_version=result.schema_version, unresolved=unresolved, pii=pii,
        )

    # explicit offline detection: rule-based, review-bound, detection-only
    hresult = heuristic_extractor.extract(percept)
    return _Interpretation(
        memories=hresult.memories, extractor=hresult.extractor, status="heuristic",
        model="heuristic", prompt_version="extract-v3", schema_version="2", pii=pii,
    )


def _persist_interpretation_state(store: MemoryStore, percept: Percept,
                                  outcome: _Interpretation, *,
                                  status: str, items: int) -> None:
    prev = store.get_interpretation(percept.id)
    store.record_interpretation(PerceptInterpretation(
        percept_id=percept.id,
        status=status,
        interpreter=outcome.extractor,
        model=outcome.model,
        prompt_version=outcome.prompt_version,
        schema_version=outcome.schema_version,
        attempts=(prev.attempts if prev else 0) + 1,
        items_catalogued=items,
        unresolved_count=outcome.unresolved,
        detail=outcome.detail,
        content_hash=percept.content_hash,
        created_at=prev.created_at if prev else "",
    ))


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

    # Quarantine prompt-injection content before extraction can produce memories
    from ..privacy.quarantine import is_quarantined, quarantine_content
    q = quarantine_content(
        store, percept.content or "",
        percept_id=percept.id,
        artifact_id=(percept.content_refs[0].get("artifact_id")
                     if percept.content_refs and isinstance(percept.content_refs[0], dict)
                     else None),
    )
    if q is not None or is_quarantined(store, percept_id=percept.id):
        report.extractor = "quarantined"
        report.interpretation_status = "quarantined"
        _persist_interpretation_state(
            store, percept,
            _Interpretation([], "quarantine", "quarantined", "", "", ""),
            status="quarantined", items=0,
        )
        return report

    outcome = _interpret(cfg, percept)
    report.extractor = outcome.extractor
    report.pii_findings = outcome.pii
    report.interpretation_status = outcome.status
    report.unresolved_references = outcome.unresolved

    # v0.7 core invariant: an unavailable/failed interpreter DEFERS. Nothing is
    # catalogued and the Percept stays retryable — it was never understood, so
    # it must not be treated as understood-and-empty.
    if outcome.status in _RETRYABLE_STATES:
        report.deferred = True
        _persist_interpretation_state(store, percept, outcome,
                                      status=outcome.status, items=0)
        return report

    artifact_id = ensure_artifact_from_percept(store, percept)

    # v0.6: connector-fed percepts obey a per-source candidate policy —
    # what a source may propose is a governance decision, not the adapter's
    from .source_policy import evaluate as policy_evaluate
    from .source_policy import policy_for_percept
    source_policy = policy_for_percept(percept)

    for extracted in outcome.memories:
        extracted = _apply_source_qualification(
            extracted.normalized(), percept, extractor_name=outcome.extractor,
        )
        policy_decision = policy_evaluate(source_policy, extracted.type)
        if policy_decision.action == "drop":
            report.policy_dropped += 1
            continue  # stays searchable as raw/artifact, never becomes memory
        dedupe_text = f"{extracted.title}\n{extracted.summary}"
        verdict = dedupe_check(store, embedder, extracted.type, dedupe_text)

        if verdict.action == "duplicate" and verdict.existing_id:
            # New evidence for an existing memory — corroboration, not a new memory.
            from ..memory.provenance import attach_corroborating_evidence
            from .correlation.independence import independence_group_for
            igroup = independence_group_for(
                percept, fallback=artifact_id or percept.id,
            )
            attach_corroborating_evidence(
                store, verdict.existing_id, percept.id,
                extracted.evidence_quote or extracted.summary,
                independence_group=igroup,
                source_trust=percept.source_trust,
            )
            report.duplicates += 1
            continue

        review_reason = _needs_review(cfg, extracted, percept)
        # v0.7 cognitive-act governance: only a settled decision/statement is
        # standalone knowledge. A proposal, question, hypothesis, opinion or
        # third-party claim is born needing review no matter how confident the
        # interpreter was about the classification — a proposal is not a
        # decision, and a third party's claim is not the user's own.
        act = extracted.payload.get("cognitive_act")
        if act in _UNSETTLED_ACT_VALUES:
            review_reason = review_reason or f"unsettled cognitive act: {act}"
        if policy_decision.action == "review":
            review_reason = review_reason or policy_decision.reason
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
                extractor=outcome.extractor,
                model=outcome.model,
                prompt_version=outcome.prompt_version,
                schema_version=outcome.schema_version,
                created_at=percept.ingested_at or "",
            ),
        )
        store.insert_memory(mem)
        from .correlation.independence import (
            evidence_directness_for,
            independence_group_for,
        )
        igroup = independence_group_for(
            percept, fallback=artifact_id or percept.id,
        )
        store.insert_evidence(Evidence(
            id=ids.evidence_id(),
            memory_id=mem.id,
            percept_id=percept.id,
            quote=extracted.evidence_quote or extracted.summary,
            source_trust=percept.source_trust,
            directness=evidence_directness_for(percept),
            independence_group=igroup,
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

    # Terminal interpretation state: the Percept was understood (whether or not
    # anything survived governance). ``empty`` and ``interpreted`` are settled
    # outcomes — neither is re-interpreted until the Percept's content changes.
    _persist_interpretation_state(store, percept, outcome,
                                  status=outcome.status,
                                  items=len(report.inserted))
    return report


def extract_pending(store: MemoryStore, cfg: Config, embedder: Embedder) -> list[ExtractReport]:
    """Interpret every Percept still pending interpretation.

    Selection is by interpretation state, not by "has evidence yet": a
    deferred Percept is retried, while one already interpreted (even to an
    empty result) is left alone. This is what lets a temporarily unavailable
    model resume cleanly without re-interpreting settled Percepts."""
    return [
        extract_percept(store, cfg, embedder, percept)
        for percept in store.percepts_pending_interpretation(
            max_attempts=interp_service.MAX_INTERPRETATION_ATTEMPTS)
    ]
