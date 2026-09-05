"""Orchestrator tests using stage overrides (no network)."""

from __future__ import annotations

from twin.cognize.models import (
    Interpretation,
    InterpretationStatus,
    NarrativeRevisionDecision,
    NarrativeRevisionOutcome,
    Reflection,
    ReflectionStatus,
    Situation,
    SurpriseLevel,
)
from twin.cognize.orchestrator import (
    CognizeStage,
    StageResult,
    StageRunStatus,
    clear_cognize_stage_overrides,
    run_cognize,
    set_cognize_stage_override,
)
from twin.sense.sensory.percept import Percept


def _install_overrides():
    clear_cognize_stage_overrides()

    def salience(store, cfg, ctx, *, dry_run):
        ctx["kept_percepts"] = list(ctx["percepts"])
        return StageResult(CognizeStage.salience, StageRunStatus.ok, {"kept": len(ctx["kept_percepts"])})

    def situate(store, cfg, ctx, *, dry_run):
        sit = Situation(
            vault_id=ctx["vault_id"],
            percept_ids=[p.id for p in ctx["kept_percepts"]],
            summary="test situation",
        )
        ctx["situation"] = sit
        if not dry_run:
            store.upsert_situation(sit)
        return StageResult(CognizeStage.situate, StageRunStatus.ok, {"situations": 1})

    def raise_ref(store, cfg, ctx, *, dry_run):
        ref = Reflection(
            vault_id=ctx["vault_id"],
            text="Is Feature A still a launch blocker?",
            status=ReflectionStatus.open,
            situation_ids=[ctx["situation"].id],
            evidence_ids=[p.id for p in ctx["kept_percepts"]],
        )
        ctx["reflections"] = [ref]
        if not dry_run:
            store.upsert_reflection(ref)
        return StageResult(CognizeStage.raise_reflections, StageRunStatus.ok, {"reflections": 1})

    def form_intp(store, cfg, ctx, *, dry_run):
        intp = Interpretation(
            vault_id=ctx["vault_id"],
            explanation="Feature A was the blocker; PR merged it.",
            status=InterpretationStatus.competing,
            reflection_ids=[ctx["reflections"][0].id],
            evidence_ids=[p.id for p in ctx["kept_percepts"]],
        )
        ctx["interpretations"] = [intp]
        if not dry_run:
            store.upsert_interpretation(intp)
        return StageResult(CognizeStage.form_interpretations, StageRunStatus.ok, {"interpretations": 1})

    def cross_r(store, cfg, ctx, *, dry_run):
        return StageResult(CognizeStage.cross_reflections, StageRunStatus.ok, {"relations": 0})

    def cross_i(store, cfg, ctx, *, dry_run):
        return StageResult(CognizeStage.cross_interpretations, StageRunStatus.ok, {"relations": 0})

    def nrev(store, cfg, ctx, *, dry_run):
        d = NarrativeRevisionDecision(
            vault_id=ctx["vault_id"],
            interpretation_ids=[ctx["interpretations"][0].id],
            outcome=NarrativeRevisionOutcome.integrate,
            surprise=SurpriseLevel.low,
            explanatory_delta="first account",
            rationale="override",
        )
        ctx["revision"] = d
        if not dry_run:
            store.upsert_narrative_revision(d)
        return StageResult(CognizeStage.narrative_revision, StageRunStatus.ok, {"decisions": 1})

    def audit(store, cfg, ctx, *, dry_run):
        return StageResult(CognizeStage.evidence_audit, StageRunStatus.ok, {"relations": 0})

    set_cognize_stage_override(CognizeStage.salience, salience)
    set_cognize_stage_override(CognizeStage.situate, situate)
    set_cognize_stage_override(CognizeStage.raise_reflections, raise_ref)
    set_cognize_stage_override(CognizeStage.form_interpretations, form_intp)
    set_cognize_stage_override(CognizeStage.cross_reflections, cross_r)
    set_cognize_stage_override(CognizeStage.cross_interpretations, cross_i)
    set_cognize_stage_override(CognizeStage.narrative_revision, nrev)
    set_cognize_stage_override(CognizeStage.evidence_audit, audit)


def test_run_cognize_with_overrides(store, cfg):
    _install_overrides()
    try:
        p = Percept(
            percept_type="message",
            source_sensor="test",
            content="Feature A blocks launch",
            metadata={"vault_id": "vault_general", "domain": "technical"},
        )
        store.insert_percept(p)
        report = run_cognize(store, cfg, percept_ids=[p.id])
        assert report.ok
        assert not report.halted
        assert report.reflection_ids
        assert report.interpretation_ids
        assert store.get_reflection(report.reflection_ids[0]) is not None
    finally:
        clear_cognize_stage_overrides()


def test_run_cognize_emits_progress(store, cfg):
    _install_overrides()
    events = []
    try:
        p = Percept(
            percept_type="message",
            source_sensor="test",
            content="Feature A blocks launch",
            metadata={"vault_id": "vault_general", "domain": "technical"},
        )
        store.insert_percept(p)
        report = run_cognize(
            store, cfg, percept_ids=[p.id], on_progress=events.append,
        )
        assert report.ok
        assert events
        assert events[0]["phase"] == "running"
        assert events[-1]["phase"] == "complete"
        assert events[-1]["percent"] == 100
        assert any(e.get("entities", {}).get("reflection_ids") for e in events)
    finally:
        clear_cognize_stage_overrides()


def test_cognize_halts_without_llm_or_override(store, cfg, monkeypatch):
    clear_cognize_stage_overrides()
    monkeypatch.setattr(cfg, "extractor", "heuristic")
    p = Percept(
        percept_type="message",
        source_sensor="test",
        content="x",
        metadata={"vault_id": "vault_general"},
    )
    store.insert_percept(p)
    report = run_cognize(store, cfg, percept_ids=[p.id], chat_reachable=False)
    assert report.halted


def test_run_cognize_retires_pending_percepts(store, cfg):
    _install_overrides()
    try:
        ids = []
        for i in range(3):
            p = Percept(
                percept_type="message",
                source_sensor="test",
                content=f"pending item {i}",
                metadata={"vault_id": "vault_general"},
            )
            store.insert_percept(p)
            ids.append(p.id)
        assert len(store.percepts_pending_cognize(limit=50)) == 3
        report = run_cognize(store, cfg, limit=2)
        assert report.ok
        pending = store.percepts_pending_cognize(limit=50)
        assert len(pending) == 1
        assert pending[0].id == ids[2]
        second = run_cognize(store, cfg, limit=2)
        assert second.ok
        assert store.percepts_pending_cognize(limit=50) == []
    finally:
        clear_cognize_stage_overrides()


def test_progress_percent_is_percept_weighted():
    from twin.cognize.orchestrator import CognizeStage, CognitionReport, _progress_payload

    report = CognitionReport(ok=True)
    ctx = {"batch_count": 100, "percepts": [], "kept_percepts": []}
    # Stage 0 (first), 5 percepts done of 100, across 8 stages.
    mid = _progress_payload(
        stage=CognizeStage.salience,
        stage_index=0,
        stage_total=8,
        phase="running",
        report=report,
        ctx=ctx,
        percept_done=5,
    )
    assert mid["percent"] == round(100.0 * 5 / (8 * 100), 1)
    assert mid["percept_done"] == 5
    assert mid["percept_total"] == 100
    # End of stage 0 = 100/800.
    done0 = _progress_payload(
        stage=CognizeStage.salience,
        stage_index=0,
        stage_total=8,
        phase="done",
        report=report,
        ctx=ctx,
    )
    assert done0["percent"] == round(100.0 * 100 / 800, 1)
    # Mid stage 1 (index 1) with 5 done = (100+5)/800.
    mid1 = _progress_payload(
        stage=CognizeStage.situate,
        stage_index=1,
        stage_total=8,
        phase="running",
        report=report,
        ctx=ctx,
        percept_done=5,
    )
    assert mid1["percent"] == round(100.0 * 105 / 800, 1)


def test_llm_json_emits_soft_progress_while_waiting():
    """Batch LLM stages must not sit at 0/N for the whole model latency."""
    import time

    from twin.cognize.orchestrator import (
        CognizeStage,
        CognitionReport,
        _llm_json,
    )

    events: list[dict] = []
    report = CognitionReport(ok=True)

    class SlowLlm:
        def complete_json(self, **kwargs):
            time.sleep(2.4)
            return {"summary": "ok", "domain": "technical"}

    ctx = {
        "llm": SlowLlm(),
        "_stage": CognizeStage.situate,
        "_stage_index": 1,
        "_stage_total": 8,
        "_report": report,
        "_emit_progress": events.append,
        "batch_count": 50,
        "_progress_floor": 0,
        "percepts": [],
        "kept_percepts": [],
    }
    out = _llm_json(ctx, "system", "user prompt with enough chars " * 40)
    assert out["summary"] == "ok"
    soft = [e for e in events if e.get("activity") == "model"]
    assert soft, "expected soft model heartbeats during LLM wait"
    assert soft[-1]["percept_done"] > 0
    assert soft[-1]["percept_done"] < 50  # capped below full batch
    assert all(e["stage"] == "situate" for e in soft)


def test_halt_discards_partial_entities_keeps_percepts_pending(store, cfg):
    """Failed mid-run must not leave orphan entities or retire percepts."""
    clear_cognize_stage_overrides()

    def salience(store, cfg, ctx, *, dry_run):
        ctx["kept_percepts"] = list(ctx["percepts"])
        return StageResult(CognizeStage.salience, StageRunStatus.ok, {"kept": 1})

    def situate(store, cfg, ctx, *, dry_run):
        from twin.cognize.models import Situation

        sit = Situation(
            vault_id=ctx["vault_id"],
            percept_ids=[p.id for p in ctx["kept_percepts"]],
            summary="partial sit",
        )
        ctx["situation"] = sit
        if not dry_run:
            store.upsert_situation(sit)
            from twin.cognize.orchestrator import _track_created
            _track_created(ctx, "situations", sit.id)
        return StageResult(CognizeStage.situate, StageRunStatus.ok, {"situations": 1})

    def raise_ref(store, cfg, ctx, *, dry_run):
        from twin.cognize.models import Reflection, ReflectionStatus
        from twin.cognize.orchestrator import _track_created

        ref = Reflection(
            vault_id=ctx["vault_id"],
            text="open Q?",
            status=ReflectionStatus.open,
            situation_ids=[ctx["situation"].id],
            evidence_ids=[p.id for p in ctx["kept_percepts"]],
        )
        ctx["reflections"] = [ref]
        if not dry_run:
            store.upsert_reflection(ref)
            _track_created(ctx, "reflections", ref.id)
        return StageResult(CognizeStage.raise_reflections, StageRunStatus.ok, {"reflections": 1})

    def boom(store, cfg, ctx, *, dry_run):
        return StageResult(
            CognizeStage.form_interpretations,
            StageRunStatus.halted,
            detail="simulated mid-run failure",
        )

    set_cognize_stage_override(CognizeStage.salience, salience)
    set_cognize_stage_override(CognizeStage.situate, situate)
    set_cognize_stage_override(CognizeStage.raise_reflections, raise_ref)
    set_cognize_stage_override(CognizeStage.form_interpretations, boom)
    try:
        p = Percept(
            percept_type="message",
            source_sensor="test",
            content="needs cognize",
            metadata={"vault_id": "vault_general"},
        )
        store.insert_percept(p)
        report = run_cognize(store, cfg, limit=10, vault_id="vault_general")
        assert report.halted
        assert "discarded partial run" in (report.detail or "")
        assert store.list_situations("vault_general") == []
        assert store.list_reflections("vault_general") == []
        assert store.list_cognize_interpretations("vault_general") == []
        pending = store.percepts_pending_cognize(limit=50)
        assert any(x.id == p.id for x in pending)
        assert report.situation_ids == []
        assert report.reflection_ids == []
    finally:
        clear_cognize_stage_overrides()


def test_plan_cognize_zero_when_empty(store, cfg, monkeypatch):
    from twin.cognize.orchestrator import plan_cognize

    monkeypatch.delenv("TWIN_VAULT", raising=False)
    plan = plan_cognize(store, cfg, limit=50, vault_id="vault_personal")
    assert plan["batch_count"] == 0
    assert plan["pending_total"] == 0
    assert plan["totals"]["total_tokens_est"] == 0
    assert plan["totals"]["cost_usd"] == 0
    assert plan["queue_totals"]["total_tokens_est"] == 0
    assert "no-op" in plan["estimate_note"].lower() or "nothing pending" in plan["estimate_note"].lower()


def test_unstamped_pending_only_in_general(store, cfg, monkeypatch):
    from twin.cognize.orchestrator import plan_cognize

    monkeypatch.delenv("TWIN_VAULT", raising=False)
    store.insert_percept(Percept(
        percept_type="message",
        source_sensor="test",
        content="legacy no vault",
        metadata={},
    ))
    store.insert_percept(Percept(
        percept_type="message",
        source_sensor="test",
        content="work item",
        metadata={"vault_id": "vault_work"},
    ))
    general = plan_cognize(store, cfg, limit=20, vault_id="vault_general")
    work = plan_cognize(store, cfg, limit=20, vault_id="vault_work")
    personal = plan_cognize(store, cfg, limit=20, vault_id="vault_personal")
    assert general["pending_total"] >= 1
    assert work["pending_total"] == 1
    assert personal["pending_total"] == 0


def test_run_cognize_skips_foreign_pending_for_vault(store, cfg):
    """Global pending queue must not starve the active vault with foreign stamps."""
    _install_overrides()
    try:
        for i in range(3):
            store.insert_percept(Percept(
                percept_type="message",
                source_sensor="test",
                content=f"dogfood {i}",
                metadata={"vault_id": "vault_dogfood"},
            ))
        mine = Percept(
            percept_type="message",
            source_sensor="test",
            content="personal note",
            metadata={"vault_id": "vault_personal"},
        )
        store.insert_percept(mine)
        report = run_cognize(store, cfg, limit=2, vault_id="vault_personal")
        assert report.ok
        assert not report.halted
        pending = store.percepts_pending_cognize(limit=50)
        pending_ids = {p.id for p in pending}
        assert mine.id not in pending_ids
        assert all(
            (p.metadata or {}).get("vault_id") == "vault_dogfood" for p in pending
        )
    finally:
        clear_cognize_stage_overrides()


def test_percept_brief_scales_with_batch_limit(store, cfg, monkeypatch):
    from twin.cognize.orchestrator import _brief_limit, _percept_brief, plan_cognize

    monkeypatch.delenv("TWIN_COGNIZE_BRIEF_LIMIT", raising=False)
    rows = []
    for i in range(12):
        p = Percept(
            percept_type="message",
            source_sensor="test",
            content=f"batch body {i} " + ("x" * 40),
            metadata={"vault_id": "vault_general"},
        )
        store.insert_percept(p)
        rows.append(p)

    assert _brief_limit(50) == 50
    brief = _percept_brief(rows, limit=_brief_limit(12))
    assert brief.count("\n") + 1 == 12

    monkeypatch.setenv("TWIN_COGNIZE_BRIEF_LIMIT", "5")
    assert _brief_limit(12) == 5
    plan = plan_cognize(store, cfg, limit=12, vault_id="vault_general")
    assert plan["batch_limit"] == 12
    assert plan["brief_limit"] == 5
    # Explicit UI override wins over env.
    plan_ui = plan_cognize(
        store, cfg, limit=12, vault_id="vault_general", brief_limit=3,
    )
    assert plan_ui["brief_limit"] == 3
    # Fewer briefed items → smaller input estimate than uncapped.
    monkeypatch.delenv("TWIN_COGNIZE_BRIEF_LIMIT", raising=False)
    plan_full = plan_cognize(store, cfg, limit=12, vault_id="vault_general")
    assert plan_full["brief_limit"] == 12
    assert plan["totals"]["input_tokens"] < plan_full["totals"]["input_tokens"]
    assert plan_ui["totals"]["input_tokens"] < plan["totals"]["input_tokens"]


def test_as_object_list_rejects_strings():
    from twin.cognize.orchestrator import (
        _as_object_list,
        _as_str_list,
        _index_pair,
        _unwrap_llm_payload,
    )

    assert _as_object_list("abc") == []
    assert _as_object_list([{"text": "q"}, "x"]) == [{"text": "q"}]
    assert _as_str_list("abc") == []
    assert _as_str_list(["a", 1]) == ["a", "1"]
    assert _unwrap_llm_payload({"parameters": {"interpretations": []}}) == {
        "interpretations": [],
    }
    assert _unwrap_llm_payload({"interpretations": []}) == {"interpretations": []}
    assert _index_pair({"from_index": 0, "to_index": 1}) == (0, 1)
    assert _index_pair({"from_index": "nope", "to_index": 1}) is None


def test_empty_interpretations_do_not_halt(store, cfg):
    from twin.cognize.orchestrator import _llm_stage

    class EmptyLlm:
        def complete_json(self, **kwargs):
            return {"parameters": {"interpretations": []}}

    ctx = {
        "llm": EmptyLlm(),
        "vault_id": "vault_general",
        "kept_percepts": [],
        "percepts": [],
        "reflections": [],
        "situation": None,
        "batch_count": 1,
        "brief_limit": 1,
        "created": {},
    }
    formed = _llm_stage(
        store, cfg, CognizeStage.form_interpretations, ctx, dry_run=True,
    )
    assert formed.status is StageRunStatus.ok
    assert formed.counts["interpretations"] == 0
    ctx["interpretations"] = []
    revised = _llm_stage(
        store, cfg, CognizeStage.narrative_revision, ctx, dry_run=True,
    )
    assert revised.status is StageRunStatus.ok
    audited = _llm_stage(
        store, cfg, CognizeStage.evidence_audit, ctx, dry_run=True,
    )
    assert audited.status is StageRunStatus.ok


def test_run_cognize_retires_only_briefed_percepts(store, cfg):
    _install_overrides()
    try:
        ids = []
        for i in range(4):
            p = Percept(
                percept_type="message",
                source_sensor="test",
                content=f"brief window {i}",
                metadata={"vault_id": "vault_general"},
            )
            store.insert_percept(p)
            ids.append(p.id)
        report = run_cognize(store, cfg, limit=4, brief_limit=2)
        assert report.ok
        pending = store.percepts_pending_cognize(limit=50)
        pending_ids = {p.id for p in pending}
        assert ids[0] not in pending_ids
        assert ids[1] not in pending_ids
        assert ids[2] in pending_ids
        assert ids[3] in pending_ids
    finally:
        clear_cognize_stage_overrides()


def test_brief_caps_to_context_window(store, cfg, monkeypatch):
    from twin.cognize.orchestrator import plan_cognize

    monkeypatch.delenv("TWIN_COGNIZE_BRIEF_LIMIT", raising=False)
    monkeypatch.setattr("twin.llm.usage.context_window_for", lambda *a, **k: 8_192)
    for i in range(80):
        store.insert_percept(Percept(
            percept_type="message",
            source_sensor="test",
            content=("token filler " * 80) + str(i),
            metadata={"vault_id": "vault_general"},
        ))
    plan = plan_cognize(store, cfg, limit=80, vault_id="vault_general")
    assert plan["brief_limit"] < 80
    assert plan["batch_count"] == 80
    assert "context window" in plan["estimate_note"]
