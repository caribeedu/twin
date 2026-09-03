"""Cognize orchestrator — stages 0–7.

Without stage overrides, every thinking stage requires a live chat LLM.
Overrides stand in for CI. Lexical invention is forbidden.
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
from twin.sense.sensory.percept import Percept


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

# Heuristic system prompts + expected completion size for Web/CLI token previews.
# Not billed usage — rough chars÷4 estimates so operators can size a run.
_STAGE_SYSTEM_EST: dict[CognizeStage, str] = {
    CognizeStage.salience: (
        'You gate cognitive work. Reply JSON: '
        '{"keep_percept_ids":["..."],"drop_percept_ids":["..."],"rationale":"..."}'
    ),
    CognizeStage.situate: (
        'Cluster percepts into one situation. JSON: '
        '{"summary":"...","domain":"technical"}'
    ),
    CognizeStage.raise_reflections: (
        'Raise the most important open question. JSON: '
        '{"reflections":[{"text":"..."}]}'
    ),
    CognizeStage.form_interpretations: (
        'Form competing explanations. JSON: '
        '{"interpretations":[{"explanation":"...","evidence_percept_ids":["..."]}]}'
    ),
    CognizeStage.cross_reflections: (
        "Relate reflections. JSON: "
        '{"relations":[{"from_id":"...","to_id":"...","type":"related","rationale":"..."}]}'
    ),
    CognizeStage.cross_interpretations: (
        "Relate interpretations. JSON: "
        '{"relations":[{"from_id":"...","to_id":"...","type":"contradicts","rationale":"..."}]}'
    ),
    CognizeStage.narrative_revision: (
        "Propose narrative revision decisions. JSON: "
        '{"decision":"...","rationale":"...","evidence_percept_ids":["..."]}'
    ),
    CognizeStage.evidence_audit: (
        "Audit evidence grounding. JSON: "
        '{"relations":[{"from_id":"...","to_id":"...","type":"supports","rationale":"..."}]}'
    ),
}

_STAGE_OUTPUT_EST: dict[CognizeStage, int] = {
    CognizeStage.salience: 220,
    CognizeStage.situate: 180,
    CognizeStage.raise_reflections: 260,
    CognizeStage.form_interpretations: 420,
    CognizeStage.cross_reflections: 280,
    CognizeStage.cross_interpretations: 280,
    CognizeStage.narrative_revision: 240,
    CognizeStage.evidence_audit: 260,
}


def _approx_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def plan_cognize(
    store: Any,
    cfg: Config,
    *,
    limit: int = 50,
    vault_id: Optional[str] = None,
    percept_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Pending items + per-stage token/cost estimates (no LLM calls).

    One Cognize run processes up to ``limit`` percepts through stages 0–7.
    Clearing a larger queue takes multiple runs; ``queue_totals`` scales the
    batch estimate by ``runs_to_clear``.
    """
    import math
    import os

    from twin.cognize.gate import require_chat_llm
    from twin.llm import llm_available
    from twin.llm.usage import estimate_cost

    vault = vault_id or "default"
    batch_limit = max(1, int(limit or 50))
    try:
        reachable = llm_available(cfg)
    except Exception:
        reachable = False
    gate = require_chat_llm(
        extractor=cfg.extractor,
        chat_provider=getattr(cfg, "normalized_llm_provider", "") or "",
        chat_reachable=reachable,
        allow_echo_cognition=os.environ.get("TWIN_ALLOW_ECHO_COGNITION", "") == "1",
    )

    # Scan the full pending queue (capped), then take this Execute batch.
    scan_cap = 5_000 if not percept_ids else batch_limit
    scanned = _load_percepts(store, percept_ids, scan_cap)
    if vault:
        scanned = [
            p for p in scanned
            if str((p.metadata or {}).get("vault_id") or (p.metadata or {}).get("vault") or vault) == vault
        ]
    pending_total = len(scanned)
    queue_truncated = (not percept_ids) and pending_total >= scan_cap
    percepts = scanned[:batch_limit]

    brief_n = _brief_limit(batch_limit)
    brief = _percept_brief(percepts, limit=brief_n)
    # Later stages also send intermediate artefacts — pad input roughly (tokens).
    stage_user_extra_tok = {
        CognizeStage.raise_reflections: 40,
        CognizeStage.form_interpretations: 120,
        CognizeStage.cross_reflections: 140,
        CognizeStage.cross_interpretations: 160,
        CognizeStage.narrative_revision: 140,
        CognizeStage.evidence_audit: 120,
    }

    stages: list[dict[str, Any]] = []
    total_in = 0
    total_out = 0
    total_cost = 0.0
    model = getattr(cfg, "resolved_llm_model", "") or ""
    kind = ""
    try:
        kind = str(getattr(cfg, "llm_provider_kind", "") or "")
    except Exception:
        kind = ""
    if not kind:
        try:
            kind = str(getattr(cfg, "normalized_llm_provider", "") or "")
        except Exception:
            kind = ""
    home = getattr(cfg, "home", None)

    any_priced = False
    for stage in STAGE_ORDER:
        system = _STAGE_SYSTEM_EST.get(stage, "")
        user = f"Percepts:\n{brief}"
        in_tok = (
            _approx_tokens(system)
            + _approx_tokens(user)
            + int(stage_user_extra_tok.get(stage, 0))
        )
        out_tok = int(_STAGE_OUTPUT_EST.get(stage, 200))
        # Price by model id even when kind is unknown (gateway / mislabeled provider).
        cost, priced = estimate_cost(kind or "openai_compatible", model, in_tok, out_tok, home=home)
        if priced:
            any_priced = True
        total_in += in_tok
        total_out += out_tok
        total_cost += cost
        stages.append({
            "stage": stage.value,
            "label": stage.value.replace("_", " ").title(),
            "input_tokens": in_tok,
            "output_tokens_est": out_tok,
            "total_tokens_est": in_tok + out_tok,
            "cost_usd": cost,
            "priced": priced,
        })

    items = []
    for p in percepts:
        body = (p.content or "").strip().replace("\n", " ")
        title = body[:120] if body else p.id
        items.append({
            "id": p.id,
            "title": title,
            "source_sensor": p.source_sensor or "",
            "href": f"#explore/percept/{p.id}",
        })

    runs_to_clear = math.ceil(pending_total / batch_limit) if pending_total else 0
    total_cost_rounded = round(total_cost, 6)
    queue_in = total_in * runs_to_clear
    queue_out = total_out * runs_to_clear
    queue_cost = round(total_cost * runs_to_clear, 6)

    return {
        "ok": True,
        "vault_id": vault,
        "gate_ok": gate.ok,
        "halt_reason": gate.halt_reason.value if gate.halt_reason else None,
        "detail": gate.detail,
        "llm_reachable": reachable,
        "model": model,
        "provider_kind": kind,
        "batch_limit": batch_limit,
        "batch_count": len(items),
        "pending_total": pending_total,
        "queue_truncated": queue_truncated,
        "runs_to_clear": runs_to_clear,
        "item_count": len(items),
        "items": items,
        "stages": stages,
        "totals": {
            "scope": "batch",
            "input_tokens": total_in,
            "output_tokens_est": total_out,
            "total_tokens_est": total_in + total_out,
            "cost_usd": total_cost_rounded,
            "priced": any_priced,
        },
        "queue_totals": {
            "scope": "full_queue",
            "runs": runs_to_clear,
            "pending_total": pending_total,
            "input_tokens": queue_in,
            "output_tokens_est": queue_out,
            "total_tokens_est": queue_in + queue_out,
            "cost_usd": queue_cost,
            "priced": any_priced,
        },
        "brief_limit": brief_n,
        "estimate_note": (
            f"Heuristic chars÷4 · {model or 'model'}"
            + (" · priced" if any_priced else " · cost unknown for this model")
            + f" · one run = up to {batch_limit} items"
            + (f" · brief {brief_n}" if brief_n != batch_limit else "")
        ),
    }


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
    if hasattr(store, "percepts_pending_cognize"):
        return store.percepts_pending_cognize(limit=limit)
    return store.list_percepts()[:limit]


def _brief_limit(batch_limit: int) -> int:
    """How many percepts enter each stage prompt.

    Defaults to the full batch. Cap with ``TWIN_COGNIZE_BRIEF_LIMIT`` when you
    want a cheaper / smaller context window.
    """
    raw = os.environ.get("TWIN_COGNIZE_BRIEF_LIMIT", "").strip()
    if raw:
        try:
            return max(1, min(int(raw), max(1, batch_limit)))
        except ValueError:
            pass
    return max(1, batch_limit)


def _percept_brief(percepts: list[Percept], limit: int) -> str:
    lines = []
    for p in percepts[:limit]:
        body = (p.content or "").strip().replace("\n", " ")[:240]
        lines.append(f"- [{p.id}] sensor={p.source_sensor} :: {body}")
    return "\n".join(lines)


def _ctx_entity_ids(ctx: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "situation_ids": [ctx["situation"].id] if ctx.get("situation") else [],
        "reflection_ids": [r.id for r in (ctx.get("reflections") or [])],
        "interpretation_ids": [r.id for r in (ctx.get("interpretations") or [])],
        "relation_ids": [r.id for r in (ctx.get("relations") or [])],
        "revision_ids": [ctx["revision"].id] if ctx.get("revision") else [],
        "stale_narrative_ids": list(ctx.get("stale_narrative_ids") or []),
    }


def _progress_payload(
    *,
    stage: CognizeStage,
    stage_index: int,
    stage_total: int,
    phase: str,
    report: CognitionReport,
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """Snapshot for runtime job.result.progress (and UI polling)."""
    total = max(1, int(stage_total))
    idx = max(0, min(int(stage_index), total))
    if phase == "done":
        percent = round(100.0 * min(idx + 1, total) / total, 1)
    elif phase == "complete":
        percent = 100.0
    else:
        percent = round(100.0 * idx / total, 1)
    entities = _ctx_entity_ids(ctx)
    # Fold ids already on the report (e.g. stale narratives marked before stages).
    if report.stale_narrative_ids and not entities["stale_narrative_ids"]:
        entities["stale_narrative_ids"] = list(report.stale_narrative_ids)
    counts = {
        "situations": len(entities["situation_ids"]),
        "reflections": len(entities["reflection_ids"]),
        "interpretations": len(entities["interpretation_ids"]),
        "relations": len(entities["relation_ids"]),
        "revisions": len(entities["revision_ids"]),
        "stale_narratives": len(entities["stale_narrative_ids"]),
    }
    return {
        "phase": phase,
        "stage": stage.value,
        "label": stage.value.replace("_", " ").title(),
        "stage_index": idx,
        "stage_total": total,
        "percent": percent,
        "stages_done": [
            {
                "stage": s.stage.value,
                "status": s.status.value,
                "counts": dict(s.counts),
            }
            for s in report.stages
        ],
        "counts": counts,
        "entities": entities,
    }


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
    on_progress: Optional[Callable[[dict[str, Any]], None]] = None,
) -> CognitionReport:
    """Run Cognize stages 0–7. Never commits Narratives.

    ``on_progress`` receives a dict after each stage start/finish (and once at
    completion) so runtime jobs can expose live percent / entity ids.
    """
    allow_echo = os.environ.get("TWIN_ALLOW_ECHO_COGNITION", "") == "1"
    has_overrides = bool(_OVERRIDES)

    def _emit(payload: dict[str, Any]) -> None:
        if on_progress is None:
            return
        try:
            on_progress(payload)
        except Exception:
            pass

    reachable = chat_reachable
    if reachable is None and not has_overrides:
        try:
            from twin.llm import llm_available

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
        report = CognitionReport(
            ok=False,
            halted=True,
            halt_reason=gate.halt_reason.value if gate.halt_reason else "halt",
            detail=gate.detail,
        )
        _persist_run(store, vault_id or "", report)
        return report

    percepts = _load_percepts(store, percept_ids, limit)
    if not percepts:
        report = CognitionReport(ok=True, detail="no percepts to cognize")
        _persist_run(store, vault_id or "default", report)
        return report

    vault = vault_id or _vault(percepts)
    kept_vault: list[Percept] = []
    foreign = 0
    for p in percepts:
        meta = p.metadata or {}
        pvault = str(meta.get("vault_id") or meta.get("vault") or vault)
        if pvault != vault:
            foreign += 1
            continue
        kept_vault.append(p)
    if not kept_vault:
        report = CognitionReport(
            ok=False,
            halted=True,
            halt_reason="cross_vault_refuse",
            detail=f"no percepts in vault={vault} (refused {foreign} foreign)",
        )
        _persist_run(store, vault, report)
        return report
    percepts = kept_vault

    report = CognitionReport(ok=True)

    if not dry_run:
        for p in percepts:
            report.stale_narrative_ids.extend(mark_stale_for_new_percept(store, p))

    llm = None
    if not has_overrides:
        from twin.llm import get_chat_client

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
        "ungrounded_dropped": 0,
        "brief_limit": _brief_limit(limit),
    }

    stop_at = _until_index(until)
    stage_total = stop_at + 1
    ctx["stale_narrative_ids"] = list(report.stale_narrative_ids)
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
            _emit(
                _progress_payload(
                    stage=stage,
                    stage_index=i,
                    stage_total=stage_total,
                    phase="running",
                    report=report,
                    ctx=ctx,
                )
            )
            result = _run_stage(store, cfg, stage, ctx, dry_run=dry_run)
            report.stages.append(result)
            _emit(
                _progress_payload(
                    stage=stage,
                    stage_index=i,
                    stage_total=stage_total,
                    phase="done",
                    report=report,
                    ctx=ctx,
                )
            )
            if result.status is StageRunStatus.halted:
                report.ok = False
                report.halted = True
                report.halt_reason = stage.value
                report.detail = result.detail
                _persist_run(store, vault, report)
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
    if ctx.get("ungrounded_dropped"):
        report.detail = (
            (report.detail + "; " if report.detail else "")
            + f"ungrounded_dropped={ctx['ungrounded_dropped']}"
        )
    _emit(
        _progress_payload(
            stage=STAGE_ORDER[min(stop_at, len(STAGE_ORDER) - 1)],
            stage_index=stage_total - 1,
            stage_total=stage_total,
            phase="complete",
            report=report,
            ctx=ctx,
        )
    )
    if not dry_run and report.ok and not report.halted:
        ids = [p.id for p in percepts]
        if hasattr(store, "mark_percepts_cognized"):
            try:
                store.mark_percepts_cognized(ids)
            except Exception:
                pass
    _persist_run(store, vault, report)
    return report


def _persist_run(store: Any, vault_id: str, report: CognitionReport) -> None:
    if not hasattr(store, "record_cognize_run"):
        return
    try:
        store.record_cognize_run(
            vault_id=vault_id or "",
            status="halted" if report.halted else ("ok" if report.ok else "error"),
            halt_reason=report.halt_reason or "",
            detail=report.detail or "",
            payload=report.to_dict(),
        )
    except Exception:
        pass


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


_OPEN_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": True,
}


def _llm_json(ctx: dict[str, Any], system: str, user: str) -> dict[str, Any]:
    llm = ctx.get("llm")
    if llm is None:
        raise RuntimeError("chat LLM unavailable for Cognize stage")
    return llm.complete_json(
        system=system,
        user=user,
        schema=_OPEN_JSON_SCHEMA,
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
    source = ctx["kept_percepts"] if stage != CognizeStage.salience else ctx["percepts"]
    brief = _percept_brief(source, limit=int(ctx.get("brief_limit") or len(source) or 1))
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
            known_ids = {p.id for p in ctx["kept_percepts"]}
            intps = []
            dropped = 0
            for item in data.get("interpretations") or []:
                expl = str(item.get("explanation") or "").strip()
                if not expl:
                    continue
                evid = [
                    pid
                    for pid in (item.get("evidence_percept_ids") or [])
                    if pid in known_ids
                ]
                if not evid:
                    dropped += 1
                    continue
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
            ctx["ungrounded_dropped"] = int(ctx.get("ungrounded_dropped") or 0) + dropped
            if not intps:
                raise RuntimeError(
                    f"LLM returned no grounded interpretations (dropped={dropped})"
                )
            ctx["interpretations"] = intps
            return StageResult(
                stage=stage,
                status=StageRunStatus.ok,
                counts={"interpretations": len(intps), "ungrounded_dropped": dropped},
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
