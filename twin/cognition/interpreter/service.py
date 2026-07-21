"""Interpreter selection, availability and deferral (v0.7).

Selection follows ``cfg.extractor`` for backward compatibility:

    auto      → cognitive interpreter if the local model is reachable,
                otherwise DEFER (never fabricate conclusions from lexical rules)
    ollama    → cognitive interpreter; DEFER when unreachable
    heuristic → explicit offline detection mode (see ``pipeline``); the
                interpreter is not used

The load-bearing rule of v0.7: in an interpreting mode, an unavailable model
yields a ``deferred`` result, not a heuristic guess. A Percept is understood
only when a cognitive interpreter actually ran.

A module-level override lets tests and evals inject a deterministic
interpreter with no LLM and no network — the same shape as the ``hash``
embedder used elsewhere in the suite.
"""

from __future__ import annotations

from typing import Callable, Optional

from ...config import Config
from ...sensory.percept import Percept
from . import ollama_interpreter
from .schema import InterpretationResult, InterpretationStatus

# Retries stop after this many failed/deferred attempts so a poison input or a
# permanently misconfigured model never loops forever; the percept is left in
# its last non-terminal state for an operator to inspect.
MAX_INTERPRETATION_ATTEMPTS = 6

InterpreterFn = Callable[[Percept, str, Config], InterpretationResult]

_OVERRIDE: Optional[InterpreterFn] = None


def set_interpreter_override(fn: Optional[InterpreterFn]) -> None:
    """Inject a deterministic interpreter (tests/evals). Pass ``None`` to
    restore the real, model-backed path."""
    global _OVERRIDE
    _OVERRIDE = fn


def interpreting_mode(cfg: Config) -> bool:
    """True when the configured mode should run the cognitive interpreter
    (rather than the explicit offline heuristic detector)."""
    return cfg.extractor in ("auto", "ollama") or _OVERRIDE is not None


def interpreter_available(cfg: Config) -> bool:
    if _OVERRIDE is not None:
        return True
    return ollama_interpreter.available(cfg.ollama_url)


def run_interpreter(cfg: Config, percept: Percept,
                    masked_text: str) -> InterpretationResult:
    """Run the cognitive interpreter on one Percept.

    Returns a ``deferred`` result (no items) when the interpreter is
    unavailable or errors — the caller must NOT treat this as "understood and
    empty". Errors are sanitized; raw provider text never surfaces."""
    if _OVERRIDE is not None:
        try:
            return _OVERRIDE(percept, masked_text, cfg)
        except Exception as exc:  # a test/eval stub blew up
            return _deferred(f"interpreter override error: {type(exc).__name__}",
                             status=InterpretationStatus.error)

    if not interpreter_available(cfg):
        return _deferred("cognitive interpreter unavailable (model unreachable)")
    try:
        return ollama_interpreter.interpret(
            percept, masked_text,
            base_url=cfg.ollama_url, model=cfg.ollama_model,
        )
    except Exception as exc:
        # reached-but-failed on this input; retryable but bounded by attempts
        return _deferred(f"interpreter error: {type(exc).__name__}",
                         status=InterpretationStatus.error)


def _deferred(detail: str,
              status: InterpretationStatus = InterpretationStatus.deferred
              ) -> InterpretationResult:
    return InterpretationResult(
        items=[], status=status, interpreter="cognitive-interpreter",
        prompt_version=ollama_interpreter.PROMPT_VERSION,
        schema_version=ollama_interpreter.SCHEMA_VERSION,
        detail=detail,
    )
