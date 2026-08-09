"""Cognize orchestrator — stages 0–7 with LLM-or-halt and test overrides.

Without stage overrides, every thinking stage requires a live chat LLM
(``llm_available``). Overrides are the CI stand-in (like episode
``set_stage_override``). Default lexical invention is forbidden.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from twin.cognize.gate import require_chat_llm
from twin.cognize.models import (
    EvidenceAnchor,
    Interpretation,
    InterpretationStatus,
    NarrativeRevisionDecision,
    NarrativeRevisionOutcome,
    Reflection,
    ReflectionStatus,
    Relation,
    RelationAssertedBy,
    RelationType,
    Situation,
    SituationStatus,
    SurpriseLevel,
)
from twin.cognize.stale import mark_stale_for_new_percept
from twin.config import Config
from twin.sensory.percept import Percept


class CognizeStage(str, Enum):
    salience = "salience"
    situate = "situate"
    raise_reflections = "raise_reflections"
    form_interpretations = "form_interpretations"
    cross_reflections = "cross_reflections"
    cross_interpretations = "cross_interpretations"
    narrative_revision = "narrative_revision"
    evidence_audit = "evidence_audit"


STAGE_ORDER: list[CognizeStage] = [
    CognizeStage.salience,
    CognizeStage.situate,
    CognizeStage.raise_reflections,
    CognizeStage.form_interpretations,
    CognizeStage.cross_reflections,
    CognizeStage.cross_interpretations,
    CognizeStage.narrative_revision,
    CognizeStage.evidence_audit,
]


class StageRunStatus(str, Enum):
    ok = "ok"
    halted = "halted"
    deferred = "deferred"
    skipped = "skipped"
    blocked = "blocked"


@dataclass
class StageResult:
    stage: CognizeStage
    status: StageRunStatus
    counts: dict[str, int] = field(default_factory=dict)
    detail: str = ""


@dataclass
class CognitionReport:
    ok: bool
    halted: bool = False
    halt_reason: Optional[str] = None
    detail: str = ""
    stages: list[StageResult] = field(default_factory=list)
    situation_ids: list[str] = field(default_factory=list)
    reflection_ids: list[str] = field(default_factory=list)
    interpretation_ids: list[str] = field(default_factory=list)
    relation_ids: list[str] = field(default_factory=list)
    revision_ids: list[str] = field(default_factory=list)
    stale_narrative_ids: list[str] = field(default_factory=list)
    review_enqueued: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "halted": self.halted,
            "halt_reason": self.halt_reason,
            "detail": self.detail,
            "stages": [
                {
                    "stage": s.stage.value,
                    "status": s.status.value,
                    "counts": s.counts,
                    "detail": s.detail,
                }
                for s in self.stages
            ],
            "situation_ids": self.situation_ids,
            "reflection_ids": self.reflection_ids,
            "interpretation_ids": self.interpretation_ids,
            "relation_ids": self.relation_ids,
            "revision_ids": self.revision_ids,
            "stale_narrative_ids": self.stale_narrative_ids,
            "review_enqueued": self.review_enqueued,
        }


_OVERRIDES: dict[str, Callable[..., Any]] = {}


def set_cognize_stage_override(stage: Any, fn: Optional[Callable[..., Any]]) -> None:
    key = stage.value if isinstance(stage, CognizeStage) else str(stage)
    if fn is None:
        _OVERRIDES.pop(key, None)
    else:
        _OVERRIDES[key] = fn


def clear_cognize_stage_overrides() -> None:
    _OVERRIDES.clear()


def _until_index(until: Optional[CognizeStage]) -> int:
    if until is None:
        return len(STAGE_ORDER) - 1
    return STAGE_ORDER.index(until)


def _vault(percepts: list[Percept]) -> str:
    for p in percepts:
        meta = p.metadata or {}
        if meta.get("vault_id") or meta.get("vault"):
            return str(meta.get("vault_id") or meta.get("vault"))
    return "default"


def _load_percepts(store: Any, percept_ids: Optional[list[str]], limit: int) -> list[Percept]:
    if percept_ids:
        out = []
        for pid in percept_ids:
            p = store.get_percept(pid)
            if p is not None:
                out.append(p)
        return out
    if hasattr(store, "percepts_pending_interpretation"):
        from twin.cognition.interpreter import MAX_INTERPRETATION_ATTEMPTS

        return store.percepts_pending_interpretation(
            max_attempts=MAX_INTERPRETATION_ATTEMPTS,
        )[:limit]
    return store.list_percepts()[:limit]


def _percept_brief(percepts: list[Percept], limit: int = 8) -> str:
    lines = []
    for p in percepts[:limit]:
        body = (p.content or "").strip().replace("\n", " ")[:240]
        lines.append(f"- [{p.id}] sensor={p.source_sensor} :: {body}")
    return "\n".join(lines)


def run_cognize(
    store: Any,
    cfg: Config,
    *,
    percept_ids: Optional[list[str]] = None,
    until: Optional[CognizeStage] = None,
    dry_run: bool = False,
    limit: int = 50,
    vault_id: Optional[str] = None,
    chat_reachable: Optional[bool] = None,
) -> CognitionReport:
    """Run Cognize stages 0–7. Never commits Narratives."""
    allow_echo = os.environ.get("TWIN_ALLOW_ECHO_COGNITION", "") == "1"
    has_overrides = bool(_OVERRIDES)

    reachable = chat_reachable
    if reachable is None and not has_overrides:
        try:
            from twin.cognition.llm import llm_available

            reachable = llm_available(cfg)
        except Exception:
            reachable = False

    gate = require_chat_llm(
        extractor=cfg.extractor,
        chat_provider=getattr(cfg, "normalized_llm_provider", "") or "",
        chat_reachable=True if has_overrides and chat_reachable is None else reachable,
        allow_echo_cognition=allow_echo or has_overrides,
    )
    if gate.halted:
        return CognitionReport(
            ok=False,
            halted=True,
            halt_reason=gate.halt_reason.value if gate.halt_reason else "halt",
            detail=gate.detail,
        )

    percepts = _load_percepts(store, percept_ids, limit)
    if not percepts:
        return CognitionReport(ok=True, detail="no percepts to cognize")

    vault = vault_id or _vault(percepts)
    report = CognitionReport(ok=True)

    if not dry_run:
        for p in percepts:
            report.stale_narrative_ids.extend(mark_stale_for_new_percept(store, p))

    llm = None
    if not has_overrides:
        from twin.cognition.llm import get_chat_client

        llm = get_chat_client(cfg)

    ctx: dict[str, Any] = {
        "percepts": percepts,
        "vault_id": vault,
        "kept_percepts": list(percepts),
        "situation": None,
        "reflections": [],
        "interpretations": [],
        "relations": [],
        "revision": None,
        "llm": llm,
        "model_id": getattr(cfg, "resolved_llm_model", "") or "",
    }

    stop_at = _until_index(until)
    try:
        for i, stage in enumerate(STAGE_ORDER):
            if i > stop_at:
                report.stages.append(
                    StageResult(
                        stage=stage,
                        status=StageRunStatus.skipped,
                        detail="after --until",
                    )
                )
                continue
            result = _run_stage(store, cfg, stage, ctx, dry_run=dry_run)
            report.stages.append(result)
            if result.status is StageRunStatus.halted:
                report.ok = False
                report.halted = True
                report.halt_reason = stage.value
                report.detail = result.detail
                return report
    finally:
        if llm is not None:
            close = getattr(llm, "close", None)
            if callable(close):
                close()

    report.situation_ids = [ctx["situation"].id] if ctx.get("situation") else []
    report.reflection_ids = [r.id for r in ctx.get("reflections") or []]
    report.interpretation_ids = [r.id for r in ctx.get("interpretations") or []]
    report.relation_ids = [r.id for r in ctx.get("relations") or []]
    if ctx.get("revision") is not None:
        report.revision_ids = [ctx["revision"].id]
    report.review_enqueued = bool(report.interpretation_ids) and not dry_run
    return report


def _run_stage(
    store: Any,
    cfg: Config,
    stage: CognizeStage,
    ctx: dict[str, Any],
    *,
    dry_run: bool,
) -> StageResult:
    override = _OVERRIDES.get(stage.value)
    if override is not None:
        return override(store, cfg, ctx, dry_run=dry_run)
    return _llm_stage(store, cfg, stage, ctx, dry_run=dry_run)


def _llm_json(ctx: dict[str, Any], system: str, user: str) -> dict[str, Any]:
    llm = ctx.get("llm")
    if llm is None:
        raise RuntimeError("chat LLM unavailable for Cognize stage")
    return llm.complete_json(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
    )


def _llm_stage(
    store: Any,
    cfg: Config,
    stage: CognizeStage,
    ctx: dict[str, Any],
    *,
    dry_run: bool,
) -> StageResult:
    vault = ctx["vault_id"]
    brief = _percept_brief(ctx["kept_percepts"] if stage != CognizeStage.salience else ctx["percepts"])
    try:
        if stage is CognizeStage.salience:
            data = _llm_json(
                ctx,
                "You gate cognitive work. Reply JSON: "
                '{"keep_percept_ids":["..."],"drop_percept_ids":["..."],"rationale":"..."}',
                f"Percepts:\n{brief}",
            )
            keep_ids = set(data.get("keep_percept_ids") or [p.id for p in ctx["percepts"]])
            ctx["kept_percepts"] = [p for p in ctx["percepts"] if p.id in keep_ids]
            return StageResult(
                stage=stage,
                status=StageRunStatus.ok,
                counts={
                    "kept": len(ctx["kept_percepts"]),
                    "dropped": len(ctx["percepts"]) - len(ctx["kept_percepts"]),
                },
                detail=str(data.get("rationale") or ""),
            )

        if stage is CognizeStage.situate:
            data = _llm_json(
                ctx,
                "Cluster percepts into one situation. JSON: "
                '{"summary":"...","domain":"technical"}',
                f"Percepts:\n{brief}",
            )
            sit = Situation(
                vault_id=vault,
                percept_ids=[p.id for p in ctx["kept_percepts"]],
                status=SituationStatus.working,
                summary=str(data.get("summary") or "situation"),
                domain=str(data.get("domain") or ""),
            )
            ctx["situation"] = sit
            if not dry_run:
                store.upsert_situation(sit)
            return StageResult(stage=stage, status=StageRunStatus.ok, counts={"situations": 1})

        if stage is CognizeStage.raise_reflections:
            data = _llm_json(
                ctx,
                "Raise the most important open question. JSON: "
                '{"reflections":[{"text":"..."}]}',
                f"Situation: {(ctx['situation'].summary if ctx.get('situation') else '')}\n"
                f"Percepts:\n{brief}",
            )
            refs = []
            for item in data.get("reflections") or []:
                text = str(item.get("text") or "").strip()
                if not text:
                    continue
                ref = Reflection(
                    vault_id=vault,
                    text=text,
                    status=ReflectionStatus.open,
                    situation_ids=[ctx["situation"].id] if ctx.get("situation") else [],
                    evidence_ids=[p.id for p in ctx["kept_percepts"]],
                )
                refs.append(ref)
                if not dry_run:
                    store.upsert_reflection(ref)
            if not refs:
                raise RuntimeError("LLM returned no reflections")
            ctx["reflections"] = refs
            return StageResult(
                stage=stage, status=StageRunStatus.ok, counts={"reflections": len(refs)}
            )

        if stage is CognizeStage.form_interpretations:
            data = _llm_json(
                ctx,
                "Form competing explanations. JSON: "
                '{"interpretations":[{"explanation":"...","evidence_percept_ids":["..."]}]}',
                f"Reflections: {json.dumps([r.text for r in ctx['reflections']])}\n"
                f"Percepts:\n{brief}",
            )
            intps = []
            for item in data.get("interpretations") or []:
                expl = str(item.get("explanation") or "").strip()
                if not expl:
                    continue
                evid = item.get("evidence_percept_ids") or [p.id for p in ctx["kept_percepts"]]
                intp = Interpretation(
                    vault_id=vault,
                    explanation=expl,
                    status=InterpretationStatus.competing,
                    reflection_ids=[r.id for r in ctx["reflections"]],
                    situation_ids=[ctx["situation"].id] if ctx.get("situation") else [],
                    evidence_ids=list(evid),
                )
                intps.append(intp)
                if not dry_run:
                    store.upsert_interpretation(intp)
                    for pid in evid:
                        p = next((x for x in ctx["kept_percepts"] if x.id == pid), None)
                        if p is None:
                            continue
                        quote = (p.content or "")[:500]
                        if quote:
                            store.upsert_evidence_anchor(
                                EvidenceAnchor(
                                    vault_id=vault,
                                    percept_id=p.id,
                                    quote=quote,
                                    target_kind="interpretation",
                                    target_id=intp.id,
                                )
                            )
            if not intps:
                raise RuntimeError("LLM returned no interpretations")
            ctx["interpretations"] = intps
            return StageResult(
                stage=stage,
                status=StageRunStatus.ok,
                counts={"interpretations": len(intps)},
            )

        if stage is CognizeStage.cross_reflections:
            if len(ctx["reflections"]) < 2:
                return StageResult(
                    stage=stage,
                    status=StageRunStatus.ok,
                    counts={"relations": 0},
                    detail="nothing to cross",
                )
            data = _llm_json(
                ctx,
                "Link reflections. JSON: "
                '{"relations":[{"from_index":0,"to_index":1,"type":"same-as","rationale":"..."}]}',
                json.dumps([r.text for r in ctx["reflections"]]),
            )
            rels = []
            for item in data.get("relations") or []:
                fi = int(item.get("from_index", 0))
                ti = int(item.get("to_index", 0))
                refs = ctx["reflections"]
                if not (0 <= fi < len(refs) and 0 <= ti < len(refs)):
                    continue
                rtype = str(item.get("type") or "related")
                rel = Relation(
                    vault_id=vault,
                    from_id=refs[fi].id,
                    to_id=refs[ti].id,
                    type=RelationType(rtype),
                    asserted_by=RelationAssertedBy.llm,
                    rationale=str(item.get("rationale") or ""),
                    model_id=ctx.get("model_id") or "",
                )
                rels.append(rel)
                if not dry_run:
                    store.upsert_relation(rel)
            ctx["relations"] = list(ctx.get("relations") or []) + rels
            return StageResult(
                stage=stage, status=StageRunStatus.ok, counts={"relations": len(rels)}
            )

        if stage is CognizeStage.cross_interpretations:
            if len(ctx["interpretations"]) < 2:
                return StageResult(
                    stage=stage,
                    status=StageRunStatus.ok,
                    counts={"relations": 0},
                    detail="nothing to cross",
                )
            data = _llm_json(
                ctx,
                "Link interpretations. JSON: "
                '{"relations":[{"from_index":0,"to_index":1,"type":"contradicts","rationale":"..."}]}',
                json.dumps([i.explanation for i in ctx["interpretations"]]),
            )
            rels = []
            for item in data.get("relations") or []:
                fi = int(item.get("from_index", 0))
                ti = int(item.get("to_index", 0))
                intps = ctx["interpretations"]
                if not (0 <= fi < len(intps) and 0 <= ti < len(intps)):
                    continue
                rtype = str(item.get("type") or "related")
                rel = Relation(
                    vault_id=vault,
                    from_id=intps[fi].id,
                    to_id=intps[ti].id,
                    type=RelationType(rtype),
                    asserted_by=RelationAssertedBy.llm,
                    rationale=str(item.get("rationale") or ""),
                    model_id=ctx.get("model_id") or "",
                )
                rels.append(rel)
                if not dry_run:
                    store.upsert_relation(rel)
            ctx["relations"] = list(ctx.get("relations") or []) + rels
            return StageResult(
                stage=stage, status=StageRunStatus.ok, counts={"relations": len(rels)}
            )

        if stage is CognizeStage.narrative_revision:
            priors = store.list_narratives(vault)[:3]
            data = _llm_json(
                ctx,
                "Decide narrative revision. JSON: "
                '{"outcome":"integrate|branch|contradict|supersede|keep_separate|defer",'
                '"surprise":"low|medium|high","explanatory_delta":"...","rationale":"...",'
                '"retained_dissent_ids":[]}',
                json.dumps(
                    {
                        "prior": [n.account for n in priors],
                        "interpretations": [i.explanation for i in ctx["interpretations"]],
                    }
                ),
            )
            outcome = str(data.get("outcome") or "defer")
            decision = NarrativeRevisionDecision(
                vault_id=vault,
                prior_narrative_id=priors[0].id if priors else None,
                interpretation_ids=[i.id for i in ctx["interpretations"]],
                outcome=NarrativeRevisionOutcome(outcome),
                surprise=SurpriseLevel(str(data.get("surprise") or "medium")),
                explanatory_delta=str(data.get("explanatory_delta") or ""),
                retained_dissent_ids=list(data.get("retained_dissent_ids") or []),
                rationale=str(data.get("rationale") or ""),
            )
            ctx["revision"] = decision
            if not dry_run:
                store.upsert_narrative_revision(decision)
            return StageResult(stage=stage, status=StageRunStatus.ok, counts={"decisions": 1})

        if stage is CognizeStage.evidence_audit:
            data = _llm_json(
                ctx,
                "Audit independence. JSON: "
                '{"same_originating_decision_groups":[["percept_id",...]],"rationale":"..."}',
                f"Percepts:\n{brief}\nInterpretations:\n"
                + json.dumps([i.explanation for i in ctx["interpretations"]]),
            )
            rels = []
            for group in data.get("same_originating_decision_groups") or []:
                ids = [str(x) for x in group]
                for a, b in zip(ids, ids[1:]):
                    rel = Relation(
                        vault_id=vault,
                        from_id=a,
                        to_id=b,
                        type=RelationType.same_originating_decision,
                        asserted_by=RelationAssertedBy.llm,
                        rationale=str(data.get("rationale") or ""),
                        model_id=ctx.get("model_id") or "",
                    )
                    rels.append(rel)
                    if not dry_run:
                        store.upsert_relation(rel)
            ctx["relations"] = list(ctx.get("relations") or []) + rels
            return StageResult(
                stage=stage, status=StageRunStatus.ok, counts={"relations": len(rels)}
            )
    except Exception as exc:
        return StageResult(
            stage=stage,
            status=StageRunStatus.halted,
            detail=str(exc),
        )

    return StageResult(stage=stage, status=StageRunStatus.skipped, detail="unhandled")
