"""LLM usage accounting — token extraction, cost, ledger, stage tagging."""

from __future__ import annotations

import time

import pytest

from twin.cognition.llm import usage as u


@pytest.fixture(autouse=True)
def _clean_sinks():
    u.reset_sinks()
    yield
    u.reset_sinks()


def test_extract_tokens_per_provider():
    assert u.extract_tokens("ollama", {"prompt_eval_count": 800, "eval_count": 120}) == (800, 120, 920)
    assert u.extract_tokens(
        "openai_compatible",
        {"usage": {"prompt_tokens": 1200, "completion_tokens": 300, "total_tokens": 1500}},
    ) == (1200, 300, 1500)
    assert u.extract_tokens(
        "anthropic",
        {"usage": {"input_tokens": 1000, "output_tokens": 250}},
    ) == (1000, 250, 1250)
    assert u.extract_tokens(
        "gemini",
        {"usageMetadata": {"promptTokenCount": 500, "candidatesTokenCount": 90, "totalTokenCount": 590}},
    ) == (500, 90, 590)
    # missing / malformed body → zeros, never raises
    assert u.extract_tokens("openai_compatible", None) == (0, 0, 0)


def test_anthropic_counts_cache_tokens_as_input():
    inp, out, total = u.extract_tokens("anthropic", {"usage": {
        "input_tokens": 100,
        "cache_read_input_tokens": 40,
        "cache_creation_input_tokens": 10,
        "output_tokens": 50,
    }})
    assert inp == 150 and out == 50 and total == 200


def test_cost_estimate_known_model(tmp_path):
    # gpt-4o: 2.50 in / 10.00 out per 1M
    cost, priced = u.estimate_cost("openai_compatible", "gpt-4o", 1_000_000, 1_000_000, home=tmp_path)
    assert priced is True
    assert cost == pytest.approx(12.50, rel=1e-6)


def test_local_is_free_but_priced(tmp_path):
    cost, priced = u.estimate_cost("ollama", "qwen3.6:latest", 5000, 5000, home=tmp_path)
    assert cost == 0.0 and priced is True


def test_unknown_cloud_model_is_unpriced(tmp_path):
    cost, priced = u.estimate_cost("openai_compatible", "some-exotic-model", 1000, 1000, home=tmp_path)
    assert cost == 0.0 and priced is False


def test_longest_prefix_wins(tmp_path):
    # gpt-4o-mini must not be priced as gpt-4o
    mini, _ = u.estimate_cost("openai_compatible", "gpt-4o-mini", 1_000_000, 0, home=tmp_path)
    full, _ = u.estimate_cost("openai_compatible", "gpt-4o", 1_000_000, 0, home=tmp_path)
    assert mini == pytest.approx(0.15) and full == pytest.approx(2.50)


def test_pricing_override_file(tmp_path):
    import json

    (tmp_path / "pricing.json").write_text(
        json.dumps({"my-model": [1.0, 2.0]}), encoding="utf-8",
    )
    # bust the module cache by pointing at a fresh home
    u._pricing_cache = None
    cost, priced = u.estimate_cost("openai_compatible", "acme/my-model", 1_000_000, 1_000_000, home=tmp_path)
    assert priced is True
    assert cost == pytest.approx(3.0)


def test_emit_usage_tags_stage_and_role(tmp_path):
    captured: list[u.LLMUsage] = []
    u.add_sink(captured.append)
    with u.usage_context(stage="reflect", role="analysis", session_id="s1"):
        u.emit_usage(
            kind="openai_compatible", model="gpt-4o",
            body={"usage": {"prompt_tokens": 100, "completion_tokens": 50}},
            started=time.perf_counter() - 0.2, home=tmp_path,
        )
    assert len(captured) == 1
    rec = captured[0]
    assert rec.stage == "reflect" and rec.role == "analysis"
    assert rec.session_id == "s1"
    assert rec.input_tokens == 100 and rec.output_tokens == 50
    assert rec.cost_usd > 0 and rec.priced is True
    assert rec.latency_ms >= 0


def test_emit_usage_stage_override_beats_context(tmp_path):
    # embeddings force stage="embed" even inside a reflect context
    captured: list[u.LLMUsage] = []
    u.add_sink(captured.append)
    with u.usage_context(stage="reflect", role="analysis"):
        u.emit_usage(
            kind="openai_compatible", model="text-embedding-3-small",
            body={"usage": {"prompt_tokens": 1000, "total_tokens": 1000}},
            started=time.perf_counter(), stage="embed", home=tmp_path,
        )
    assert captured[0].stage == "embed"
    # embedding priced on input only: 1M * 0.02 → 0.02 for 1M; here 1000 tok
    assert captured[0].cost_usd == pytest.approx(0.00002, rel=1e-3)


def test_embedding_model_is_priced(tmp_path):
    cost, priced = u.estimate_cost(
        "openai_compatible", "text-embedding-3-small", 1_000_000, 0, home=tmp_path,
    )
    assert priced is True and cost == pytest.approx(0.02)


def test_emit_usage_never_raises_on_failure(tmp_path):
    captured: list[u.LLMUsage] = []
    u.add_sink(captured.append)
    u.emit_usage(kind="anthropic", model="claude-sonnet-4", body=None,
                 started=time.perf_counter(), ok=False, home=tmp_path)
    assert captured and captured[0].ok is False
    assert captured[0].total_tokens == 0


def test_ledger_roundtrip_and_summary(tmp_path):
    u.install_ledger_sink(tmp_path)
    rows_in = [
        ("openai_compatible", "gpt-4o", "reflect", "analysis", 1200, 320),
        ("openai_compatible", "gpt-4o", "reflect", "analysis", 800, 200),
        ("ollama", "qwen3.6:latest", "interpret", "hot", 900, 100),
    ]
    for kind, model, stage, role, i, o in rows_in:
        with u.usage_context(stage=stage, role=role):
            body = (
                {"usage": {"prompt_tokens": i, "completion_tokens": o}}
                if kind != "ollama"
                else {"prompt_eval_count": i, "eval_count": o}
            )
            u.emit_usage(kind=kind, model=model, body=body,
                         started=time.perf_counter(), home=tmp_path)

    ledger = u.JsonlLedger(u.default_ledger_path(tmp_path))
    rows = ledger.read()
    assert len(rows) == 3

    report = u.summarize(rows)
    assert report["totals"]["calls"] == 3
    assert report["totals"]["input_tokens"] == 2900
    # only the two gpt-4o calls cost money
    assert report["by_stage"]["reflect"]["cost_usd"] > 0
    assert report["by_stage"]["interpret"]["cost_usd"] == 0.0
    assert report["by_role"]["analysis"]["calls"] == 2
    assert report["by_role"]["hot"]["calls"] == 1
    assert set(report["by_model"]) == {"gpt-4o", "qwen3.6:latest"}


def test_install_ledger_sink_is_idempotent(tmp_path):
    u.install_ledger_sink(tmp_path)
    u.install_ledger_sink(tmp_path)
    with u.usage_context(stage="interpret"):
        u.emit_usage(kind="ollama", model="qwen3.6:latest",
                     body={"prompt_eval_count": 10, "eval_count": 5},
                     started=time.perf_counter(), home=tmp_path)
    rows = u.JsonlLedger(u.default_ledger_path(tmp_path)).read()
    # one sink, one line — not duplicated
    assert len(rows) == 1
