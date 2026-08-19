"""Preflight token/cost estimate for a Cognize run (estimate only)."""

from __future__ import annotations

import json
from typing import Any, Optional

from twin.cognize.orchestrator import (
    STAGE_ORDER,
    CognizeStage,
    _load_percepts,
    _percept_brief,
    _until_index,
    _vault,
)
from twin.config import Config
from twin.llm.tokenize import count_messages_tokens, encoding_name_for_model
from twin.llm.usage import estimate_cost

# Mid output tokens per LLM stage when no ledger history exists.
_DEFAULT_OUT: dict[str, int] = {
    CognizeStage.salience.value: 220,
    CognizeStage.situate.value: 180,
    CognizeStage.raise_reflections.value: 320,
    CognizeStage.form_interpretations.value: 520,
    CognizeStage.cross_reflections.value: 280,
    CognizeStage.cross_interpretations.value: 360,
    CognizeStage.narrative_revision.value: 400,
    CognizeStage.evidence_audit.value: 300,
}

# Anthropic tool/schema framing (approx); ignored for local.
_TOOL_OVERHEAD = {
    "anthropic": 180,
    "openai_compatible": 40,
    "gemini": 40,
    "ollama": 16,
}


def _stage_prompts(brief: str) -> dict[str, tuple[str, str]]:
    """Approximate (system, user) per stage — mirrors orchestrator wording."""
    sit = "situation summary pending"
    refs = json.dumps(["open reflection A", "open reflection B"])
    intps = json.dumps(["interpretation A", "interpretation B"])
    return {
        CognizeStage.salience.value: (
            "You gate cognitive work. Reply JSON: "
            '{"keep_percept_ids":["..."],"drop_percept_ids":["..."],"rationale":"..."}',
            f"Percepts:\n{brief}",
        ),
        CognizeStage.situate.value: (
            "Cluster percepts into one situation. JSON: "
            '{"summary":"...","domain":"technical"}',
            f"Percepts:\n{brief}",
        ),
        CognizeStage.raise_reflections.value: (
            "Raise the most important open question. JSON: "
            '{"reflections":[{"text":"..."}]}',
            f"Situation: {sit}\nPercepts:\n{brief}",
        ),
        CognizeStage.form_interpretations.value: (
            "Form competing explanations. JSON: "
            '{"interpretations":[{"explanation":"...","evidence_percept_ids":["..."]}]}',
            f"Reflections: {refs}\nPercepts:\n{brief}",
        ),
        CognizeStage.cross_reflections.value: (
            "Link reflections. JSON: "
            '{"relations":[{"from_index":0,"to_index":1,"type":"same-as","rationale":"..."}]}',
            refs,
        ),
        CognizeStage.cross_interpretations.value: (
            "Link interpretations. JSON: "
            '{"relations":[{"from_index":0,"to_index":1,"type":"contradicts","rationale":"..."}]}',
            intps,
        ),
        CognizeStage.narrative_revision.value: (
            "Decide narrative revision. JSON: "
            '{"outcome":"integrate|branch|contradict|supersede|keep_separate|defer",'
            '"surprise":"low|medium|high","explanatory_delta":"...","rationale":"...",'
            '"retained_dissent_ids":[]}',
            json.dumps({"prior": ["prior account"], "interpretations": ["interpretation A", "interpretation B"]}),
        ),
        CognizeStage.evidence_audit.value: (
            "Audit independence. JSON: "
            '{"same_originating_decision_groups":[["percept_id",...]],"rationale":"..."}',
            f"Percepts:\n{brief}\nInterpretations:\n{intps}",
        ),
    }


def _historical_out(
    home: Any,
    *,
    model: str,
    stage: str,
) -> Optional[float]:
    """Average output tokens for stage+model from usage ledger, if any."""
    try:
        from pathlib import Path

        from twin.llm.usage import JsonlLedger, default_ledger_path

        path = default_ledger_path(Path(home)) if home else None
        if path is None or not path.exists():
            return None
        rows = JsonlLedger(path).read()
        matched = [
            int(r.get("output_tokens") or 0)
            for r in rows
            if (r.get("stage") or "") == stage
            and (not model or model.lower() in str(r.get("model") or "").lower())
            and int(r.get("output_tokens") or 0) > 0
        ]
        if len(matched) < 3:
            return None
        return sum(matched) / len(matched)
    except Exception:
        return None


def estimate_cognize_run(
    store: Any,
    cfg: Config,
    *,
    until: Optional[str] = "evidence_audit",
    limit: int = 20,
    vault_id: str = "default",
    percept_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Estimate tokens/cost before running Cognize. Never calls the LLM."""
    model = getattr(cfg, "resolved_llm_model", "") or ""
    kind = getattr(cfg, "llm_provider_kind", "") or "ollama"
    home = getattr(cfg, "home", None)

    until_stage = CognizeStage(until) if until else CognizeStage.evidence_audit
    stop_at = _until_index(until_stage)
    stages = [s.value for s in STAGE_ORDER[: stop_at + 1]]

    percepts = _load_percepts(store, percept_ids, limit)
    vault = vault_id or (_vault(percepts) if percepts else "default")
    kept = []
    for p in percepts:
        meta = p.metadata or {}
        pvault = str(meta.get("vault_id") or meta.get("vault") or vault)
        if pvault == vault:
            kept.append(p)
    percepts = kept
    brief = _percept_brief(percepts) if percepts else "(no percepts)"
    prompts = _stage_prompts(brief)
    overhead = _TOOL_OVERHEAD.get(kind, 40)
    enc_name = encoding_name_for_model(model)

    by_stage: list[dict[str, Any]] = []
    input_total = 0
    out_mid = 0
    for stage in stages:
        pair = prompts.get(stage)
        if not pair:
            continue
        system, user = pair
        in_tok = count_messages_tokens(
            system=system, user=user, model=model, overhead=overhead,
        )
        hist = _historical_out(home, model=model, stage=stage)
        mid = int(round(hist)) if hist is not None else _DEFAULT_OUT.get(stage, 300)
        input_total += in_tok
        out_mid += mid
        by_stage.append({
            "stage": stage,
            "input_tokens": in_tok,
            "output_tokens_est": mid,
            "output_source": "ledger" if hist is not None else "default",
        })

    out_low = int(round(out_mid * 0.6))
    out_high = int(round(out_mid * 1.5))
    cost_mid, priced = estimate_cost(kind, model, input_total, out_mid, home=home)
    cost_low, _ = estimate_cost(kind, model, input_total, out_low, home=home)
    cost_high, _ = estimate_cost(kind, model, input_total, out_high, home=home)

    return {
        "ok": True,
        "estimate": True,
        "model": model,
        "provider": kind,
        "tokenizer": f"tiktoken:{enc_name}",
        "percepts": len(percepts),
        "vault_id": vault,
        "until": until_stage.value,
        "stages": stages,
        "input_tokens": input_total,
        "output_tokens_est": out_mid,
        "output_tokens_low": out_low,
        "output_tokens_high": out_high,
        "total_tokens_est": input_total + out_mid,
        "cost_usd_est": cost_mid,
        "cost_usd_low": cost_low,
        "cost_usd_high": cost_high,
        "priced": priced,
        "by_stage": by_stage,
        "disclaimer": (
            "Estimate only (tiktoken). Early halt, salience drops, and model "
            "variance change actual tokens and cost."
        ),
    }
