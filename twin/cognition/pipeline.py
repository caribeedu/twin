"""Interpretation pipeline (v0.7): quarantine → cognitive interpreter →
grounding → classification checks → dedupe → persist (memory + entities +
relations + evidence + embedding).

Mode selection (``TWIN_EXTRACTOR``):
    auto      → cognitive interpreter if the local model is reachable,
                otherwise DEFER (retry later — never fabricate conclusions)
    ollama    → cognitive interpreter; DEFER when the model is unreachable
    stub      → deterministic offline interpreter (test/CI stand-in for the LLM)
    heuristic → NOT an interpreter — conservative detection only. It records
                ``DetectionSignal``s (routing/prioritization hints) and NEVER a
                ``MemoryItem``: lexical rules must not establish a memory type,
                domain, entity or cognitive confidence.

Load-bearing v0.7 rules:
- a Percept is understood only when a cognitive interpreter actually ran; an
  unavailable model DEFERS (retryable) and a service outage never consumes a
  Percept's retry budget;
- every catalogued item is grounded by a verbatim evidence span validated
  deterministically against the (masked) text the interpreter read — an
  invented span, even a non-empty one, is dropped;
- deterministic governance (quarantine, source policy, confidentiality floor,
  dedupe, calibration, review) is unchanged and still decides *use*.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from .. import ids
from ..config import ALL_DOMAINS, SENSITIVITY_ORDER, Config
from ..judgment.pii import mask
from ..memory.calibration import calibrated_confidence, load_calibration
from ..memory.embeddings import Embedder
from ..memory.models import (
    DetectionSignal, Evidence, ExtractorVersion, MemoryItem,
    PerceptInterpretation, Relation,
)
from ..memory.provenance import ensure_artifact_from_percept
from ..memory.store.base import MemoryStore
from ..sensory.percept import Percept
from .dedupe import check as dedupe_check
from .extractors import heuristic as heuristic_detector
from .interpreter import service as interp_service
from .interpreter.grounding import validate_grounding
from .interpreter.schema import (
    INTERPRETATION_TYPES,
    UNSETTLED_ACTS,
    InterpretationResult,
    InterpretationStatus,
)
from .quality import analyze_memory
from .schema import ExtractedMemory

# Cognitive acts (as stored in payload) that are never settled knowledge on
# their own — a proposal is not a decision, a question is not a fact.
_UNSETTLED_ACT_VALUES = frozenset(a.value for a in UNSETTLED_ACTS)
# Owner self-reference labels — a speaker_is_owner=True claim is only verified
# when the attribution matches one of these (or is a known actor tagged owner).
_OWNER_LABELS = frozenset({"self", "me", "eu", "owner", "i", "eu mesmo"})
# Error backoff bounds (seconds) for reachable-but-failing interpreters.
_BACKOFF_BASE = 60
_BACKOFF_CAP = 3600


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
    ungrounded: int = 0      # items with an invented/empty evidence span, dropped
    invalid: int = 0         # items with an out-of-vocabulary memory type, dropped
    grounded: int = 0        # items that passed evidence grounding (before policy/dedupe)
    detection_signals: int = 0  # heuristic-mode detection hints (never memories)

    def stage_counts(self) -> dict[str, int]:
        return {
            "grounded": self.grounded,
            "inserted": len(self.inserted),
            "deduplicated": self.duplicates,
            "policy_dropped": self.policy_dropped,
            "ungrounded": self.ungrounded,
            "invalid": self.invalid,
            "review_bound": self.flagged_for_review,
        }


# -- interpretation-state persistence -------------------------------------------


def _backoff_next_attempt(attempts: int) -> str:
    delay = min(_BACKOFF_CAP, _BACKOFF_BASE * (2 ** max(0, attempts - 1)))
    return (datetime.now(timezone.utc) + timedelta(seconds=delay)) \
        .strftime("%Y-%m-%dT%H:%M:%SZ")


def _record_state(store: MemoryStore, percept: Percept, *, status: str,
                  interpreter: str = "", model: str = "", prompt_version: str = "",
                  schema_version: str = "", failure_class: str = "",
                  interpretation_attempted: bool = False, items: int = 0,
                  unresolved: int = 0, detail: str = "", terminal: bool = False,
                  next_attempt_at: str = "", attempts: Optional[int] = None,
                  stage_counts: Optional[dict] = None) -> None:
    prev = store.get_interpretation(percept.id)
    store.record_interpretation(PerceptInterpretation(
        percept_id=percept.id, status=status, failure_class=failure_class,
        interpretation_attempted=interpretation_attempted, terminal=terminal,
        next_attempt_at=next_attempt_at, interpreter=interpreter, model=model,
        prompt_version=prompt_version, schema_version=schema_version,
        attempts=attempts if attempts is not None else (prev.attempts if prev else 0) + 1,
        items_catalogued=items, unresolved_count=unresolved, detail=detail,
        content_hash=percept.content_hash, stage_counts=stage_counts or {},
        created_at=prev.created_at if prev else "",
    ))


def _record_failure(store: MemoryStore, percept: Percept,
                    result: InterpretationResult) -> None:
    """Persist a deferral/error. A service outage (deferred/unavailable) is
    never terminal and never gated by backoff — it stays eligible until the
    model returns. A reachable-but-failing interpreter is bounded: after the
    budget it goes terminal, and a permanent failure is terminal at once."""
    prev = store.get_interpretation(percept.id)
    attempts = (prev.attempts if prev else 0) + 1
    if result.status == InterpretationStatus.deferred:
        # outage: do NOT consume budget, retry as soon as the model is back
        _record_state(
            store, percept, status="deferred", failure_class=result.failure_class,
            interpretation_attempted=True, interpreter=result.interpreter,
            model=result.model, prompt_version=result.prompt_version,
            schema_version=result.schema_version, detail=result.detail,
            attempts=attempts, terminal=False, next_attempt_at="",
        )
        return
    permanent = result.failure_class == "permanent"
    terminal = permanent or attempts >= interp_service.MAX_INTERPRETATION_ATTEMPTS
    _record_state(
        store, percept, status="error", failure_class=result.failure_class or "transient",
        interpretation_attempted=True, interpreter=result.interpreter,
        model=result.model, prompt_version=result.prompt_version,
        schema_version=result.schema_version, detail=result.detail,
        attempts=attempts, terminal=terminal,
        next_attempt_at="" if terminal else _backoff_next_attempt(attempts),
    )


# -- heuristic detection (never a memory) ---------------------------------------


def _run_detection(store: MemoryStore, percept: Percept) -> list[DetectionSignal]:
    signals: list[DetectionSignal] = []
    for hit in heuristic_detector.scan(percept.content or ""):
        signal = DetectionSignal(
            id=ids.new_id("sig"), percept_id=percept.id, kind=hit.kind,
            span=hit.span, confidence=hit.confidence,
            reason="lexical detection (routing hint only; not a memory)",
        )
        store.insert_detection_signal(signal)
        signals.append(signal)
    return signals


# -- item preparation: grounding already done; validate type/domain/attribution -


def _known_actor_labels(percept: Percept) -> set[str]:
    labels: set[str] = set()
    for actor in percept.actors or []:
        a = str(actor).strip().casefold()
        if not a:
            continue
        labels.add(a)
        # tolerate provider-prefixed ids like "github:bob"
        if ":" in a:
            labels.add(a.split(":", 1)[1])
    return labels


def _prepare_item(item, percept: Percept, report: ExtractReport):
    """Turn a grounded InterpretedItem into an ExtractedMemory, refusing the
    silent semantic fallbacks the old code did. Returns (extracted, forced
    review reasons) or (None, []) when the item must be dropped."""
    # invalid memory type is a schema error, never silently a 'fact'
    if item.memory_type not in INTERPRETATION_TYPES:
        report.invalid += 1
        return None, []
    forced: list[str] = []
    # invalid domain is never silently 'technical': remap to 'unknown' for the
    # conversion boundary, then force review. to_extracted() refuses unknowns
    # other than the explicit 'unknown' governance value.
    raw_domain = item.domain
    if raw_domain not in ALL_DOMAINS:
        item = item.model_copy(update={"domain": "unknown"})
        forced.append("unrecognized domain — needs review before trust")
    extracted = item.to_extracted()
    if raw_domain not in ALL_DOMAINS:
        extracted.payload["invalid_domain"] = raw_domain
        extracted.domain = "unknown"
    # attribution must be grounded in known actors; an unknown speaker is
    # unresolved, and an owner claim the actors cannot confirm is unverified
    attributed = item.attributed_to
    if attributed:
        known = _known_actor_labels(percept)
        label = attributed.strip().casefold()
        resolved = bool(known) and (
            label in known or any(label in k or k in label for k in known))
        if not resolved:
            extracted.payload["attribution_unresolved"] = True
            forced.append(f"unresolved speaker attribution: {attributed}")
        if item.speaker_is_owner and not (label in _OWNER_LABELS or (resolved and label in _OWNER_LABELS)):
            extracted.payload["owner_claim_unverified"] = True
            forced.append("owner attribution not verified against a known identity")
    return extracted, forced


# -- source qualification / review ----------------------------------------------


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
        extractor_reliability=1.0 if extractor_name.startswith("ollama") else 0.95,
        calibration=cal,
    )
    order = SENSITIVITY_ORDER
    if order.index(extracted.sensitivity) < order.index(percept.source_confidentiality):
        extracted.sensitivity = percept.source_confidentiality
    return extracted


def _needs_review(cfg: Config, mem: ExtractedMemory, percept: Percept) -> Optional[str]:
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


# -- main entry points ----------------------------------------------------------


def extract_percept(store: MemoryStore, cfg: Config, embedder: Embedder,
                    percept: Percept, *,
                    runtime: Optional[interp_service.InterpretationRuntime] = None,
                    ) -> ExtractReport:
    report = ExtractReport(percept_id=percept.id)

    # 1. Quarantine is a governance/safety gate BEFORE the interpreter — the
    #    Percept is not interpreted, it is prevented from reaching the
    #    interpreter. Record that distinctly (interpretation_attempted=False).
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
        _record_state(store, percept, status="quarantined", interpreter="quarantine",
                      interpretation_attempted=False, terminal=True)
        return report

    # 2. Heuristic mode: conservative detection only — signals, never memories.
    if not interp_service.interpreting_mode(cfg):
        signals = _run_detection(store, percept)
        report.extractor = "heuristic"
        report.interpretation_status = "heuristic_detection"
        report.detection_signals = len(signals)
        _record_state(store, percept, status="heuristic_detection",
                      interpreter="heuristic", interpretation_attempted=False,
                      terminal=True, items=0,
                      stage_counts={"detection_signals": len(signals)})
        return report

    # 3. Cognitive interpreter (production path).
    own_runtime = runtime is None
    if own_runtime:
        runtime = interp_service.InterpretationRuntime(cfg)
    masked_text, findings = mask(percept.content)
    report.pii_findings = len(findings)
    try:
        result = runtime.interpret(percept, masked_text)
    finally:
        if own_runtime:
            runtime.close()

    report.extractor = result.interpreter
    report.interpretation_status = result.status.value

    # 3a. Unavailable/failed → defer (nothing catalogued, retryable).
    if result.status in (InterpretationStatus.deferred, InterpretationStatus.error):
        report.deferred = True
        report.unresolved_references = len(result.unresolved_references)
        _record_failure(store, percept, result)
        return report

    # 3b. Deterministic grounding: an item whose evidence span is not a verbatim
    #     excerpt of the masked text (empty OR invented) is dropped here, before
    #     it can become a memory — this closes the hallucinated-evidence path.
    grounded, ungrounded = validate_grounding(result.items, masked_text)
    report.grounded = len(grounded)
    report.ungrounded = len(ungrounded)
    report.unresolved_references = len(result.unresolved_references) + sum(
        len(it.unresolved_references) for it in grounded)

    artifact_id = ensure_artifact_from_percept(store, percept)
    from .source_policy import evaluate as policy_evaluate
    from .source_policy import policy_for_percept
    source_policy = policy_for_percept(percept)

    for item in grounded:
        extracted, forced_reasons = _prepare_item(item, percept, report)
        if extracted is None:
            continue
        # to_extracted() already normalized; do NOT re-normalize here or a
        # deliberate 'unknown' domain would be silently coerced back.
        extracted = _apply_source_qualification(
            extracted, percept, extractor_name=result.interpreter,
        )
        policy_decision = policy_evaluate(source_policy, extracted.type)
        if policy_decision.action == "drop":
            report.policy_dropped += 1
            continue  # stays searchable as raw/artifact, never becomes memory
        dedupe_text = f"{extracted.title}\n{extracted.summary}"
        verdict = dedupe_check(store, embedder, extracted.type, dedupe_text)

        if verdict.action == "duplicate" and verdict.existing_id:
            from ..memory.provenance import attach_corroborating_evidence
            from .correlation.independence import independence_group_for
            igroup = independence_group_for(percept, fallback=artifact_id or percept.id)
            attach_corroborating_evidence(
                store, verdict.existing_id, percept.id,
                extracted.evidence_quote or extracted.summary,
                independence_group=igroup, source_trust=percept.source_trust,
            )
            report.duplicates += 1
            continue

        review_reason = _needs_review(cfg, extracted, percept)
        # v0.7 cognitive-act governance: a proposal, question, hypothesis,
        # opinion or third-party claim is born needing review, however
        # confident the interpreter was about the classification.
        act = extracted.payload.get("cognitive_act")
        if act in _UNSETTLED_ACT_VALUES:
            review_reason = review_reason or f"unsettled cognitive act: {act}"
        if forced_reasons:
            review_reason = review_reason or forced_reasons[0]
        if policy_decision.action == "review":
            review_reason = review_reason or policy_decision.reason
        if verdict.action == "review" and verdict.existing_id:
            review_reason = review_reason or (
                f"similar to {verdict.existing_id} (cos={verdict.similarity:.2f}) — update or contradiction?"
            )

        from ..memory.formation import propose_or_corroborate
        from .correlation.independence import (
            evidence_directness_for,
            independence_group_for,
        )
        igroup = independence_group_for(percept, fallback=artifact_id or percept.id)
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
                extractor=result.interpreter,
                model=result.model,
                prompt_version=result.prompt_version,
                schema_version=result.schema_version,
                created_at=percept.ingested_at or "",
            ),
        )
        mem, formation_action = propose_or_corroborate(
            store, mem,
            percept_id=percept.id,
            evidence_quote=extracted.evidence_quote or extracted.summary,
            independence_group=igroup,
            source_trust=percept.source_trust,
            directness=evidence_directness_for(percept),
            artifact_id=artifact_id,
        )
        if formation_action == "corroborated":
            report.duplicates += 1
            continue

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

        try:
            analyze_memory(store, embedder, mem.id, persist=True)
        except Exception:
            pass

        report.inserted.append(mem.id)
        reloaded = store.get_memory(mem.id)
        if (reloaded and reloaded.needs_review) or review_reason:
            report.flagged_for_review += 1

    # 3c. Terminal interpretation state. 'interpreted' iff the interpreter
    #     grounded at least one item; otherwise 'empty' (understood, nothing to
    #     catalogue). Neither is re-interpreted until the content changes.
    status = (InterpretationStatus.interpreted.value if grounded
              else InterpretationStatus.empty.value)
    report.interpretation_status = status
    _record_state(
        store, percept, status=status, interpreter=result.interpreter,
        model=result.model, prompt_version=result.prompt_version,
        schema_version=result.schema_version, interpretation_attempted=True,
        terminal=False, items=len(report.inserted),
        unresolved=report.unresolved_references,
        stage_counts={"emitted": len(result.items), **report.stage_counts()},
    )
    return report


def extract_pending(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    *,
    on_progress=None,
) -> list[ExtractReport]:
    """Interpret every Percept still pending interpretation.

    Availability and the HTTP client are resolved once for the whole batch via
    an :class:`InterpretationRuntime`, so a single outage never fans out into
    hundreds of health checks. Selection is by interpretation state: a deferred
    Percept is retried (a prolonged outage never abandons it), while one already
    interpreted — even to an empty result — is left alone.

    ``on_progress(done, total, percept, report)`` is called after each percept
    when provided (CLI progress / ETA).
    """
    pending = store.percepts_pending_interpretation(
        max_attempts=interp_service.MAX_INTERPRETATION_ATTEMPTS)
    if not pending:
        return []
    runtime = interp_service.InterpretationRuntime(cfg) \
        if interp_service.interpreting_mode(cfg) else None
    reports: list[ExtractReport] = []
    total = len(pending)
    try:
        for idx, percept in enumerate(pending, start=1):
            report = extract_percept(
                store, cfg, embedder, percept, runtime=runtime,
            )
            reports.append(report)
            if on_progress is not None:
                on_progress(idx, total, percept, report)
        return reports
    finally:
        if runtime is not None:
            runtime.close()
