"""Authored (recorded) interpretations for the example corpus.

A test double for the LLM interpreter must supply *authored ground truth* —
what a good model would return for a known input — never derive meaning with
lexical rules. This module records such interpretations for the standard
``examples/`` corpus, keyed to exact spans of the source text, and delegates
to the non-interpreting ``echo`` mock for anything it does not recognize.

Tests that assert semantic structure (a Decisions section, a specific type)
install ``corpus_interpreter`` via ``set_interpreter_override``; tests that
only need "some grounded memory" can rely on the default ``echo`` mode.
"""

from __future__ import annotations

from twin.cognize.services.interpreter import echo
from twin.cognize.services.interpreter.schema import (
    CognitiveAct,
    InterpretationResult,
    InterpretationStatus,
    InterpretedItem,
)

# (verbatim span from the corpus, memory_type, cognitive_act, domain)
_CORPUS: list[tuple[str, str, str, str]] = [
    # standup-2026-07-08.txt
    ("vamos usar FastAPI no backend do serviço de webhooks",
     "decision", "decision", "technical"),
    ("Action item: Edu vai fazer o setup do repositório do serviço de webhooks até sexta.",
     "task", "statement", "work"),
    ("prefiro que a gente documente as decisões de arquitetura em ADRs no próprio repo",
     "preference", "opinion", "assistant_preferences"),
    ("o ambiente de staging não pode receber dados reais de clientes",
     "constraint", "statement", "technical"),
    # rfc-webhooks.md
    ("We decided to use an outbox pattern with a `webhook_outbox` table in Postgres",
     "decision", "decision", "technical"),
    ("we must not deliver payloads containing card data",
     "constraint", "statement", "technical"),
    # atlas-kickoff.json
    ("Postgres outbox mais worker dedicado",
     "decision", "decision", "technical"),
    ("prefiro manter o payload dos webhooks versionado desde o dia um",
     "preference", "opinion", "technical"),
]


def corpus_interpreter(percept, masked_text, cfg) -> InterpretationResult:
    items = [
        InterpretedItem(
            claim_type=mtype, cognitive_act=CognitiveAct(act),
            title=span[:80], summary=span, domain=domain, confidence=0.9,
            evidence_span=span)
        for span, mtype, act, domain in _CORPUS if span in (masked_text or "")
    ]
    if items:
        return InterpretationResult(
            items=items, status=InterpretationStatus.interpreted,
            interpreter="authored-corpus", model="authored",
            prompt_version="test", schema_version="1")
    # nothing authored for this content → the neutral, non-interpreting mock
    return echo.interpret(percept, masked_text, cfg)
