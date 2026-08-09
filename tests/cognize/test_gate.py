"""Tests for Cognize LLM-or-halt gate."""

from __future__ import annotations

from twin.cognize.gate import CognizeHaltReason, require_chat_llm


def test_heuristic_halts():
    r = require_chat_llm(extractor="heuristic")
    assert r.halted
    assert r.halt_reason is CognizeHaltReason.extractor_mode_blocks_cognition


def test_echo_halts_without_flag():
    r = require_chat_llm(extractor="echo")
    assert r.halted
    assert r.halt_reason is CognizeHaltReason.echo_not_allowed


def test_echo_allowed_with_flag():
    r = require_chat_llm(extractor="echo", allow_echo_cognition=True)
    assert r.ok


def test_unreachable_halts():
    r = require_chat_llm(extractor="ollama", chat_reachable=False)
    assert r.halt_reason is CognizeHaltReason.llm_unreachable


def test_reachable_ok():
    r = require_chat_llm(extractor="ollama", chat_reachable=True)
    assert r.ok
