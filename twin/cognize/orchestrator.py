"""Cognize orchestrator — stages 0–7.

Without stage overrides, every thinking stage requires a live chat LLM.
Overrides stand in for CI. Lexical invention is forbidden.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
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
from twin.cognize.relations import coerce_relation_type
from twin.config import Config
from twin.sense.sensory.percept import Percept
from twin.privacy.vault import FALLBACK_VAULT, resolve_vault


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

STAGE_COUNT = len(STAGE_ORDER)

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
        'Raise open questions. JSON: '
        '{"reflections":[{"text":"..."}]} '
        'Each text must be only the question itself — no preamble like '
        '"The most important open question is:".'
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

# Default completion size when a new stage is added without a specific estimate.
_STAGE_OUTPUT_DEFAULT = 200

# Later stages also send intermediate artefacts — pad input roughly (tokens).
_STAGE_USER_EXTRA_TOK: dict[CognizeStage, int] = {
    CognizeStage.raise_reflections: 40,
    CognizeStage.form_interpretations: 120,
    CognizeStage.cross_reflections: 140,
    CognizeStage.cross_interpretations: 160,
    CognizeStage.narrative_revision: 140,
    CognizeStage.evidence_audit: 120,
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
    brief_limit: Optional[int] = None,
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

    vault = resolve_vault(vault_id, cfg=cfg, store=store)
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

    # Vault-scoped pending (capped scan) → this Execute batch.
    scan_cap = batch_limit if percept_ids else 5_000
    scanned = _load_percepts(
        store, percept_ids, scan_cap, vault_id=vault,
    )
    pending_total = len(scanned)
    queue_truncated = (not percept_ids) and pending_total >= scan_cap
    percepts = scanned[:batch_limit]
    batch_count = len(percepts)
    # Cap brief to what this run will actually see, not the empty "limit" knob.
    brief_n = _brief_limit(batch_count or batch_limit, brief_limit)
    brief = _percept_brief(percepts, limit=brief_n)

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

    if batch_count == 0:
        # No percepts → Execute no-ops; don't price stage overhead as a "batch".
        for stage in STAGE_ORDER:
            stages.append({
                "stage": stage.value,
                "label": stage.value.replace("_", " ").title(),
                "input_tokens": 0,
                "output_tokens_est": 0,
                "total_tokens_est": 0,
                "cost_usd": 0.0,
                "priced": False,
            })
        estimate_note = (
            f"Nothing pending in vault={vault} · Execute would no-op"
            + (f" · {model}" if model else "")
        )
    else:
        for stage in STAGE_ORDER:
            system = _STAGE_SYSTEM_EST.get(stage, "")
            user = f"Percepts:\n{brief}"
            in_tok = (
                _approx_tokens(system)
                + _approx_tokens(user)
                + int(_STAGE_USER_EXTRA_TOK.get(stage, 0))
            )
            out_tok = int(_STAGE_OUTPUT_EST.get(stage, _STAGE_OUTPUT_DEFAULT))
            cost, priced = estimate_cost(
                kind or "openai_compatible", model, in_tok, out_tok, home=home,
            )
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
        estimate_note = (
            f"Heuristic tokens (chars÷4) · {model or 'model'}"
            + (" · priced" if any_priced else " · cost unknown for this model")
            + f" · this run = {batch_count} percept"
            + ("s" if batch_count != 1 else "")
            + f" · {STAGE_COUNT} stages"
            + (
                f" · prompt brief = first {brief_n} percepts"
                if brief_n < batch_count
                else " · prompt brief = full batch"
            )
        )

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
        "batch_count": batch_count,
        "stage_count": STAGE_COUNT,
        "pending_total": pending_total,
        "queue_truncated": queue_truncated,
        "runs_to_clear": runs_to_clear,
        "item_count": batch_count,
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
        "brief_limit": brief_n if batch_count else _brief_limit(batch_limit, brief_limit),
        "estimate_note": estimate_note,
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


def _track_created(ctx: dict[str, Any], kind: str, entity_id: str) -> None:
    bag = ctx.setdefault(
        "created_ids",
        {
            "situations": [],
            "reflections": [],
            "interpretations": [],
            "relations": [],
            "revisions": [],
            "evidence_anchors": [],
        },
    )
    if entity_id and entity_id not in bag.setdefault(kind, []):
        bag[kind].append(entity_id)


def _discard_partial_run(store: Any, ctx: dict[str, Any], *, dry_run: bool) -> dict[str, int]:
    """Remove entities created mid-run so a halt leaves percepts re-cognizable.

    Percepts stay pending (never stamped cognized on halt). Partial situations /
    reflections / interpretations / relations / revisions would otherwise orphan
    and risk duplicating storylines on the next Execute.
    """
    counts = {
        "situations": 0,
        "reflections": 0,
        "interpretations": 0,
        "relations": 0,
        "revisions": 0,
        "evidence_anchors": 0,
    }
    if dry_run:
        return counts

    created = dict(ctx.get("created_ids") or {})
    # Fall back to live ctx objects when the run predated created_ids tracking.
    if ctx.get("situation") is not None:
        created.setdefault("situations", []).append(ctx["situation"].id)
    for ref in ctx.get("reflections") or []:
        created.setdefault("reflections", []).append(ref.id)
    for intp in ctx.get("interpretations") or []:
        created.setdefault("interpretations", []).append(intp.id)
    for rel in ctx.get("relations") or []:
        created.setdefault("relations", []).append(rel.id)
    if ctx.get("revision") is not None:
        created.setdefault("revisions", []).append(ctx["revision"].id)

    def _uniq(ids: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for i in ids:
            if i and i not in seen:
                seen.add(i)
                out.append(i)
        return out

    for sid in _uniq(list(created.get("situations") or [])):
        if hasattr(store, "delete_situation") and store.delete_situation(sid):
            counts["situations"] += 1
    for rid in _uniq(list(created.get("reflections") or [])):
        if hasattr(store, "delete_reflection") and store.delete_reflection(rid):
            counts["reflections"] += 1
    for iid in _uniq(list(created.get("interpretations") or [])):
        if hasattr(store, "delete_cognize_interpretation") and store.delete_cognize_interpretation(iid):
            counts["interpretations"] += 1
    for rel_id in _uniq(list(created.get("relations") or [])):
        if hasattr(store, "delete_cognize_relation") and store.delete_cognize_relation(rel_id):
            counts["relations"] += 1
    for rev_id in _uniq(list(created.get("revisions") or [])):
        if hasattr(store, "delete_narrative_revision") and store.delete_narrative_revision(rev_id):
            counts["revisions"] += 1
    for aid in _uniq(list(created.get("evidence_anchors") or [])):
        if hasattr(store, "delete_evidence_anchor") and store.delete_evidence_anchor(aid):
            counts["evidence_anchors"] += 1

    ctx["situation"] = None
    ctx["reflections"] = []
    ctx["interpretations"] = []
    ctx["relations"] = []
    ctx["revision"] = None
    ctx["created_ids"] = {
        "situations": [],
        "reflections": [],
        "interpretations": [],
        "relations": [],
        "revisions": [],
        "evidence_anchors": [],
    }
    return counts


def _until_index(until: Optional[CognizeStage]) -> int:
    if until is None:
        return len(STAGE_ORDER) - 1
    return STAGE_ORDER.index(until)


def _vault(percepts: list[Percept]) -> str:
    for p in percepts:
        meta = p.metadata or {}
        raw = str(meta.get("vault_id") or meta.get("vault") or "").strip()
        if raw:
            return raw
    return ""


def _batch_vault(
    percepts: list[Percept],
    vault_id: Optional[str],
    *,
    cfg: Any = None,
    store: Any = None,
) -> str:
    """Vault for this Cognize batch.

    Prefer an explicit non-phantom vault_id, else the vault stamped on the
    percepts (including legacy ``default`` so the batch stays coherent), else
    the active resolved vault.
    """
    explicit = str(vault_id or "").strip()
    if explicit and explicit != "default":
        return explicit
    stamped = _vault(percepts)
    if stamped:
        return stamped
    return resolve_vault(None, cfg=cfg, store=store)


def _percept_vault_stamp(percept: Percept) -> str:
    meta = percept.metadata or {}
    return str(meta.get("vault_id") or meta.get("vault") or "").strip()


def _matches_vault(percept: Percept, vault_id: str) -> bool:
    """Does this percept belong in ``vault_id``'s Cognize queue?

    Stamped rows must match exactly. Legacy unstamped rows only belong to
    ``FALLBACK_VAULT`` (``vault_general``) — not every active vault — so Work /
    Personal / custom vaults do not inherit a phantom shared queue.
    """
    stamped = _percept_vault_stamp(percept)
    if not stamped or stamped == "default":
        return vault_id == FALLBACK_VAULT
    return stamped == vault_id


def _load_percepts(
    store: Any,
    percept_ids: Optional[list[str]],
    limit: int,
    *,
    vault_id: Optional[str] = None,
) -> list[Percept]:
    """Load a Cognize batch, optionally scoped to ``vault_id``.

    Pending queue is global; without a vault filter the first N rows can all be
    foreign and the run halts with ``cross_vault_refuse`` while the UI plan
    (which filters by vault) looked fine.
    """
    batch_limit = max(1, int(limit or 50))
    vault = str(vault_id or "").strip()

    if percept_ids:
        # Explicit ids: load as-is; run_cognize enforces cross-vault refuse.
        out = []
        for pid in percept_ids:
            p = store.get_percept(pid)
            if p is not None:
                out.append(p)
                if len(out) >= batch_limit:
                    break
        return out

    if hasattr(store, "percepts_pending_cognize"):
        # Over-scan when vault-scoped so foreign stamps ahead in the queue
        # do not starve the active vault.
        scan_cap = batch_limit if not vault else min(5_000, max(batch_limit * 40, 500))
        scanned = store.percepts_pending_cognize(limit=scan_cap)
    else:
        scanned = store.list_percepts()[: batch_limit if not vault else 5_000]

    if not vault:
        return list(scanned)[:batch_limit]
    out = []
    for p in scanned:
        if not _matches_vault(p, vault):
            continue
        out.append(p)
        if len(out) >= batch_limit:
            break
    return out


def _clean_reflection_text(raw: str) -> str:
    """Drop LLM preambles so the reflection is just the question."""
    text = str(raw or "").strip()
    if not text:
        return ""
    text = re.sub(
        r"^(?:the\s+)?(?:most\s+important\s+)?open\s+question"
        r"(?:\s+right\s+now)?(?:\s+is)?\s*:\s*",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    ).strip()
    return text or str(raw or "").strip()


def _brief_limit(batch_limit: int, explicit: Optional[int] = None) -> int:
    """How many percepts enter each stage prompt.

    Order: explicit arg → ``TWIN_COGNIZE_BRIEF_LIMIT`` → full batch.
    Always capped to ``batch_limit``.
    """
    batch = max(1, int(batch_limit or 1))
    if explicit is not None:
        try:
            return max(1, min(int(explicit), batch))
        except (TypeError, ValueError):
            pass
    raw = os.environ.get("TWIN_COGNIZE_BRIEF_LIMIT", "").strip()
    if raw:
        try:
            return max(1, min(int(raw), batch))
        except ValueError:
            pass
    return batch


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
    percept_done: Optional[int] = None,
    activity: str = "",
) -> dict[str, Any]:
    """Snapshot for runtime job.result.progress (and UI polling).

    Percent is percept-weighted across stages::

        (stage_index * N + percept_done) / (stage_total * N)

    so 5/100 percepts on stage 0 → 5/(8*100), not a flat 1/8 stage step.
    """
    total = max(1, int(stage_total))
    idx = max(0, min(int(stage_index), total - 1 if total else 0))
    batch = max(
        1,
        int(
            ctx.get("batch_count")
            or len(ctx.get("kept_percepts") or [])
            or len(ctx.get("percepts") or [])
            or 1
        ),
    )
    if phase == "complete":
        done = batch
        percent = 100.0
        idx = max(0, total - 1)
    else:
        if percept_done is None:
            done = batch if phase == "done" else 0
        else:
            done = int(percept_done)
        done = max(0, min(done, batch))
        denom = max(1, total * batch)
        numer = idx * batch + done
        if phase == "done":
            # Finished this stage: count full stage slot.
            numer = (idx + 1) * batch
        percent = round(100.0 * min(numer, denom) / denom, 1)
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
    act = str(activity or "").strip()
    return {
        "phase": phase,
        "stage": stage.value,
        "label": stage.value.replace("_", " ").title(),
        "stage_index": idx,
        "stage_total": total,
        "batch_count": batch,
        "percept_total": batch,
        "percept_done": batch if phase in ("done", "complete") else done,
        "percent": percent,
        "activity": act,
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


def _emit_percept_progress(
    ctx: dict[str, Any],
    stage: CognizeStage,
    *,
    percept_done: int,
    phase: str = "running",
    activity: str = "",
) -> None:
    """Mid-stage progress update (percept-weighted)."""
    emit = ctx.get("_emit_progress")
    report = ctx.get("_report")
    if not callable(emit) or report is None:
        return
    done = max(0, int(percept_done))
    # Soft LLM beats must not rewind real apply progress.
    prev = int(ctx.get("_progress_floor") or 0)
    if activity == "model" and done < prev:
        return
    if activity != "model":
        ctx["_progress_floor"] = max(prev, done)
    try:
        emit(
            _progress_payload(
                stage=stage,
                stage_index=int(ctx.get("_stage_index") or 0),
                stage_total=int(ctx.get("_stage_total") or STAGE_COUNT),
                phase=phase,
                report=report,
                ctx=ctx,
                percept_done=done,
                activity=activity,
            )
        )
    except Exception:
        pass


def run_cognize(
    store: Any,
    cfg: Config,
    *,
    percept_ids: Optional[list[str]] = None,
    until: Optional[CognizeStage] = None,
    dry_run: bool = False,
    limit: int = 50,
    vault_id: Optional[str] = None,
    brief_limit: Optional[int] = None,
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

    resolved = resolve_vault(vault_id, cfg=cfg, store=store)
    # Pending queue is vault-scoped via the resolved id. Explicit percept_ids
    # load unfiltered so legacy stamps (incl. phantom ``default``) still hit
    # ``_batch_vault`` / cross-vault refuse correctly.
    percepts = _load_percepts(
        store,
        percept_ids,
        limit,
        vault_id=None if percept_ids else resolved,
    )
    if not percepts:
        report = CognitionReport(
            ok=True,
            detail=f"no pending percepts in vault={resolved}",
        )
        _persist_run(store, resolved, report)
        return report

    vault = _batch_vault(percepts, vault_id, cfg=cfg, store=store)
    kept_vault: list[Percept] = []
    foreign = 0
    for p in percepts:
        stamped = _percept_vault_stamp(p)
        # Legacy empty stamp follows the batch vault; any explicit stamp must match.
        pvault = stamped or vault
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
        "batch_count": len(percepts),
        "situation": None,
        "reflections": [],
        "interpretations": [],
        "relations": [],
        "revision": None,
        "llm": llm,
        "model_id": getattr(cfg, "resolved_llm_model", "") or "",
        "ungrounded_dropped": 0,
        "brief_limit": _brief_limit(limit, brief_limit),
        "_emit_progress": _emit,
        "_report": report,
        "created_ids": {
            "situations": [],
            "reflections": [],
            "interpretations": [],
            "relations": [],
            "revisions": [],
            "evidence_anchors": [],
        },
    }

    stop_at = _until_index(until)
    stage_total = stop_at + 1
    ctx["stale_narrative_ids"] = list(report.stale_narrative_ids)
    ctx["_stage_total"] = stage_total
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
            ctx["_stage_index"] = i
            ctx["_stage"] = stage
            ctx["_progress_floor"] = 0
            ctx["batch_count"] = max(
                1,
                len(ctx.get("kept_percepts") or ctx.get("percepts") or percepts),
            )
            _emit(
                _progress_payload(
                    stage=stage,
                    stage_index=i,
                    stage_total=stage_total,
                    phase="running",
                    report=report,
                    ctx=ctx,
                    percept_done=0,
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
                    percept_done=int(ctx.get("batch_count") or 1),
                )
            )
            if result.status is StageRunStatus.halted:
                report.ok = False
                report.halted = True
                report.halt_reason = stage.value
                report.detail = result.detail
                discarded = _discard_partial_run(store, ctx, dry_run=dry_run)
                bits = ", ".join(f"{k}={v}" for k, v in discarded.items() if v) or "none"
                report.detail = (
                    (report.detail + "; " if report.detail else "")
                    + f"discarded partial run ({bits})"
                )
                report.situation_ids = []
                report.reflection_ids = []
                report.interpretation_ids = []
                report.relation_ids = []
                report.revision_ids = []
                # Refresh live UI so Last run does not keep stale entity links.
                _emit(
                    _progress_payload(
                        stage=stage,
                        stage_index=i,
                        stage_total=stage_total,
                        phase="done",
                        report=report,
                        ctx=ctx,
                        percept_done=0,
                    )
                )
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
    """One JSON chat completion, with soft progress heartbeats while waiting.

    Most Cognize stages are a single batch LLM call over the whole brief — not
    per-percept work. Without beats the UI sits at ``0/N`` for minutes, then
    jumps when apply loops (or stage-done) finally fire.
    """
    llm = ctx.get("llm")
    if llm is None:
        raise RuntimeError("chat LLM unavailable for Cognize stage")

    stage = ctx.get("_stage")
    if not isinstance(stage, CognizeStage):
        stage = CognizeStage.situate
    batch = max(1, int(ctx.get("batch_count") or 1))
    floor = max(0, min(batch, int(ctx.get("_progress_floor") or 0)))
    # Leave headroom so apply / stage-done can still advance the bar.
    soft_cap = max(floor, int(floor + (batch - floor) * 0.85))
    # Brief-sized tau: bigger prompts → longer expected wait, slower climb.
    expected_s = max(25.0, min(240.0, (len(system) + len(user)) / 90.0))
    stop = threading.Event()
    last_done = floor

    def _beat() -> None:
        nonlocal last_done
        t0 = time.monotonic()
        while not stop.wait(2.0):
            elapsed = time.monotonic() - t0
            frac = 1.0 - math.exp(-elapsed / expected_s)
            done = min(soft_cap, floor + int((soft_cap - floor) * frac))
            if done <= last_done:
                continue
            last_done = done
            _emit_percept_progress(ctx, stage, percept_done=done, activity="model")

    thr = threading.Thread(target=_beat, name="cognize-llm-progress", daemon=True)
    thr.start()
    try:
        return llm.complete_json(
            system=system,
            user=user,
            schema=_OPEN_JSON_SCHEMA,
        )
    finally:
        stop.set()
        thr.join(timeout=1.0)


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
            kept: list[Percept] = []
            total_p = max(1, len(ctx["percepts"]))
            for i, p in enumerate(ctx["percepts"]):
                if p.id in keep_ids:
                    kept.append(p)
                _emit_percept_progress(ctx, stage, percept_done=i + 1)
            ctx["kept_percepts"] = kept
            ctx["batch_count"] = max(1, len(kept) or total_p)
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
            # One LLM call covers the whole batch — not a per-percept loop.
            batch = max(1, int(ctx.get("batch_count") or len(ctx["kept_percepts"]) or 1))
            _emit_percept_progress(ctx, stage, percept_done=batch)
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
                _track_created(ctx, "situations", sit.id)
            return StageResult(stage=stage, status=StageRunStatus.ok, counts={"situations": 1})

        if stage is CognizeStage.raise_reflections:
            data = _llm_json(
                ctx,
                "Raise open questions. JSON: "
                '{"reflections":[{"text":"..."}]} '
                "Each text must be only the question itself — no preamble like "
                '"The most important open question is:".',
                f"Situation: {(ctx['situation'].summary if ctx.get('situation') else '')}\n"
                f"Percepts:\n{brief}",
            )
            refs = []
            for item in data.get("reflections") or []:
                text = _clean_reflection_text(str(item.get("text") or ""))
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
                for r in refs:
                    store.upsert_reflection(r)
                    _track_created(ctx, "reflections", r.id)
            if not refs:
                raise RuntimeError("LLM returned no reflections")
            ctx["reflections"] = refs
            batch = max(1, int(ctx.get("batch_count") or len(ctx["kept_percepts"]) or 1))
            _emit_percept_progress(ctx, stage, percept_done=batch)
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
            raw_items = list(data.get("interpretations") or [])
            batch = max(1, int(ctx.get("batch_count") or len(ctx["kept_percepts"]) or 1))
            steps = max(1, len(raw_items))
            for step_i, item in enumerate(raw_items):
                expl = str(item.get("explanation") or "").strip()
                if not expl:
                    _emit_percept_progress(
                        ctx, stage, percept_done=int((step_i + 1) / steps * batch),
                    )
                    continue
                evid = [
                    pid
                    for pid in (item.get("evidence_percept_ids") or [])
                    if pid in known_ids
                ]
                if not evid:
                    dropped += 1
                    _emit_percept_progress(
                        ctx, stage, percept_done=int((step_i + 1) / steps * batch),
                    )
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
                    _track_created(ctx, "interpretations", intp.id)
                    for pid in evid:
                        p = next((x for x in ctx["kept_percepts"] if x.id == pid), None)
                        if p is None:
                            continue
                        quote = (p.content or "")[:500]
                        if quote:
                            anchor = EvidenceAnchor(
                                vault_id=vault,
                                percept_id=p.id,
                                quote=quote,
                                target_kind="interpretation",
                                target_id=intp.id,
                            )
                            store.upsert_evidence_anchor(anchor)
                            _track_created(ctx, "evidence_anchors", anchor.id)
                _emit_percept_progress(
                    ctx, stage, percept_done=int((step_i + 1) / steps * batch),
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
                '{"relations":[{"from_index":0,"to_index":1,'
                '"type":"related|same-as|supports|contradicts|depends-on|supersedes|part-of|continues",'
                '"rationale":"..."}]} '
                "(use type supports, never supported_by)",
                json.dumps([r.text for r in ctx["reflections"]]),
            )
            rels = []
            skipped = 0
            raw_rels = list(data.get("relations") or [])
            batch = max(1, int(ctx.get("batch_count") or len(ctx["kept_percepts"]) or 1))
            steps = max(1, len(raw_rels))
            for step_i, item in enumerate(raw_rels):
                fi = int(item.get("from_index", 0))
                ti = int(item.get("to_index", 0))
                refs = ctx["reflections"]
                if not (0 <= fi < len(refs) and 0 <= ti < len(refs)):
                    _emit_percept_progress(
                        ctx, stage, percept_done=int((step_i + 1) / steps * batch),
                    )
                    continue
                try:
                    rtype = coerce_relation_type(item.get("type") or "related")
                except ValueError:
                    skipped += 1
                    _emit_percept_progress(
                        ctx, stage, percept_done=int((step_i + 1) / steps * batch),
                    )
                    continue
                rel = Relation(
                    vault_id=vault,
                    from_id=refs[fi].id,
                    to_id=refs[ti].id,
                    type=rtype,
                    asserted_by=RelationAssertedBy.llm,
                    rationale=str(item.get("rationale") or ""),
                    model_id=ctx.get("model_id") or "",
                )
                rels.append(rel)
                if not dry_run:
                    store.upsert_relation(rel)
                    _track_created(ctx, "relations", rel.id)
                _emit_percept_progress(
                    ctx, stage, percept_done=int((step_i + 1) / steps * batch),
                )
            ctx["relations"] = list(ctx.get("relations") or []) + rels
            return StageResult(
                stage=stage,
                status=StageRunStatus.ok,
                counts={"relations": len(rels), "skipped_types": skipped},
                detail=("skipped invalid types" if skipped else ""),
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
                '{"relations":[{"from_index":0,"to_index":1,'
                '"type":"related|same-as|supports|contradicts|depends-on|supersedes|part-of|continues",'
                '"rationale":"..."}]} '
                "(use type supports, never supported_by)",
                json.dumps([i.explanation for i in ctx["interpretations"]]),
            )
            rels = []
            skipped = 0
            raw_rels = list(data.get("relations") or [])
            batch = max(1, int(ctx.get("batch_count") or len(ctx["kept_percepts"]) or 1))
            steps = max(1, len(raw_rels))
            for step_i, item in enumerate(raw_rels):
                fi = int(item.get("from_index", 0))
                ti = int(item.get("to_index", 0))
                intps = ctx["interpretations"]
                if not (0 <= fi < len(intps) and 0 <= ti < len(intps)):
                    _emit_percept_progress(
                        ctx, stage, percept_done=int((step_i + 1) / steps * batch),
                    )
                    continue
                try:
                    rtype = coerce_relation_type(item.get("type") or "related")
                except ValueError:
                    skipped += 1
                    _emit_percept_progress(
                        ctx, stage, percept_done=int((step_i + 1) / steps * batch),
                    )
                    continue
                rel = Relation(
                    vault_id=vault,
                    from_id=intps[fi].id,
                    to_id=intps[ti].id,
                    type=rtype,
                    asserted_by=RelationAssertedBy.llm,
                    rationale=str(item.get("rationale") or ""),
                    model_id=ctx.get("model_id") or "",
                )
                rels.append(rel)
                if not dry_run:
                    store.upsert_relation(rel)
                    _track_created(ctx, "relations", rel.id)
                _emit_percept_progress(
                    ctx, stage, percept_done=int((step_i + 1) / steps * batch),
                )
            ctx["relations"] = list(ctx.get("relations") or []) + rels
            return StageResult(
                stage=stage,
                status=StageRunStatus.ok,
                counts={"relations": len(rels), "skipped_types": skipped},
                detail=("skipped invalid types" if skipped else ""),
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
                _track_created(ctx, "revisions", decision.id)
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
                        _track_created(ctx, "relations", rel.id)
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
