"""Extraction upgrades: self-contained claims and prompt discriminators."""
from __future__ import annotations

import twin.cognition.llm as llm_mod
from twin.cognition.interpreter import ollama_interpreter as oi
from twin.cognition.interpreter.service import InterpretationRuntime
from twin.sensory.percept import Percept


def _gh_percept() -> Percept:
    return Percept(
        percept_type="connector_pull_request",
        source_sensor="github",
        content="Add role and preset management",
        ingested_at="2026-01-01T00:00:00Z",
        project_id="proj_abc",
        metadata={
            "external_type": "pull_request",
            "external_id": "caribeedu/dogwalker#14",
            "source_metadata": {
                "repo": "caribeedu/dogwalker",
                "html_url": "https://github.com/caribeedu/dogwalker/pull/14",
                "merge_commit_sha": "abc1234",
            },
        },
    ).seal()


def test_user_content_embeds_source_identity():
    body = oi._user_content(_gh_percept(), "Add role and preset management")
    assert "Source identity" in body
    assert "caribeedu/dogwalker#14" in body
    assert "caribeedu/dogwalker" in body
    assert "pull_request" in body
    assert "proj_abc" in body


def test_source_identity_empty_when_no_metadata():
    p = Percept(
        percept_type="document", source_sensor="document",
        content="hello", ingested_at="2026-01-01T00:00:00Z",
    ).seal()
    assert oi._source_identity(p) == ""
    assert "Source identity" not in oi._user_content(p, "hello")


def test_prompt_defines_task_and_procedure_discriminators():
    sys = oi.SYSTEM_PROMPT
    assert "ALREADY done is never a task" in sys
    assert "repeatable how-to" in sys
    assert "landed commit / PR / merge is an event" in sys
    assert "this commit" in sys and "without naming" in sys
    assert oi.PROMPT_VERSION == "interpret-v3"


class _FakeChat:
    name = "fake:llm"

    def available(self) -> bool:
        return True

    def close(self) -> None:  # pragma: no cover - trivial
        pass


def test_runtime_uses_single_chat_client(cfg, monkeypatch):
    cfg.extractor = "auto"
    seen = {"n": 0}

    def fake_hot(c, **kw):
        seen["n"] += 1
        return _FakeChat()

    monkeypatch.setattr(llm_mod, "get_chat_client", fake_hot)
    runtime = InterpretationRuntime(cfg)
    try:
        assert seen["n"] == 1
        assert runtime.available is True
    finally:
        runtime.close()
