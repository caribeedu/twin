"""Interpreter selection, availability and deferral (v0.7).

Selection follows ``cfg.extractor`` for backward compatibility:

    auto      → cognitive interpreter if the local model is reachable,
                otherwise DEFER (never fabricate conclusions from lexical rules)
    ollama    → cognitive interpreter; DEFER when unreachable
    echo      → non-interpreting offline mock (test/CI stand-in; makes no
                semantic classification — see ``echo.py``)
    heuristic → NOT an interpreter — detection-only mode (see ``pipeline``)

The load-bearing rule of v0.7: in an interpreting mode, an unavailable model
yields a ``deferred`` result, not a heuristic guess. A Percept is understood
only when a cognitive interpreter actually ran.

Availability and the HTTP client are resolved once per batch by an
``InterpretationRuntime``, so a single outage never triggers hundreds of
health checks or hundreds of open connections. A service outage is reported as
``deferred``/``unavailable`` and never consumes a Percept's retry budget; a
reachable-but-failing interpreter is an ``error`` with a specific failure
class (transient/input/schema/permanent).

A module-level override lets tests and evals inject a deterministic
interpreter with no LLM and no network.
"""

from __future__ import annotations

from typing import Callable, Optional

from ...config import Config
from ...sensory.percept import Percept
from . import echo, ollama_interpreter
from .schema import InterpretationResult, InterpretationStatus

# Bound retries for a reachable-but-failing interpreter (a poison input or a
# permanently misconfigured model). A *service outage* is never bounded by this
# — it stays retryable until the model returns.
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
    (rather than the explicit offline heuristic detector). ``heuristic`` is
    always detection-only, even if an override is installed — an explicit
    offline-detection test must never be silently upgraded to interpretation."""
    if cfg.extractor == "heuristic":
        return False
    return cfg.extractor in ("auto", "ollama", "echo") or _OVERRIDE is not None


def _classify_exception(exc: Exception) -> tuple[InterpretationStatus, str]:
    """Map an interpreter failure to (status, failure_class). A connection
    failure is a service outage (deferred, never budget-consuming); a bad body
    is a schema error; anything else is transient."""
    import httpx

    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout,
                        httpx.PoolTimeout)):
        return InterpretationStatus.deferred, "unavailable"
    if isinstance(exc, (httpx.ReadTimeout, httpx.WriteTimeout,
                        httpx.RemoteProtocolError, httpx.NetworkError)):
        return InterpretationStatus.error, "transient"
    name = type(exc).__name__
    if name in ("JSONDecodeError", "ValidationError", "KeyError", "ValueError"):
        return InterpretationStatus.error, "schema"
    return InterpretationStatus.error, "transient"


class InterpretationRuntime:
    """One interpreter binding for a whole batch: availability resolved once,
    HTTP client reused across Percepts, closed at the end."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._client = None
        if _OVERRIDE is not None:
            self.mode = "override"
            self.available = True
        elif cfg.extractor == "echo":
            self.mode = "echo"
            self.available = True
        else:
            self.mode = "ollama"
            # one health check for the batch, not one per Percept
            self.available = ollama_interpreter.available(cfg.ollama_url)

    def _http(self):
        if self._client is None:
            import httpx
            self._client = httpx.Client(
                base_url=self.cfg.ollama_url.rstrip("/"), timeout=600)
        return self._client

    def interpret(self, percept: Percept, masked_text: str) -> InterpretationResult:
        if self.mode == "override":
            try:
                return _OVERRIDE(percept, masked_text, self.cfg)
            except Exception as exc:
                return _deferred(f"interpreter override error: {type(exc).__name__}",
                                 status=InterpretationStatus.error,
                                 failure_class="transient")
        if self.mode == "echo":
            return echo.interpret(percept, masked_text, self.cfg)

        # ollama
        if not self.available:
            return _deferred("cognitive interpreter unavailable (model unreachable)",
                             failure_class="unavailable")
        try:
            return ollama_interpreter.interpret(
                percept, masked_text,
                base_url=self.cfg.ollama_url, model=self.cfg.ollama_model,
                client=self._http(),
            )
        except Exception as exc:
            status, fclass = _classify_exception(exc)
            if fclass == "unavailable":
                # the service went down mid-batch — stop hammering it
                self.available = False
            return _deferred(f"interpreter error: {type(exc).__name__}",
                             status=status, failure_class=fclass)

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None


def interpreter_available(cfg: Config) -> bool:
    if _OVERRIDE is not None or cfg.extractor == "echo":
        return True
    return ollama_interpreter.available(cfg.ollama_url)


def run_interpreter(cfg: Config, percept: Percept,
                    masked_text: str) -> InterpretationResult:
    """Single-Percept convenience: build a one-shot runtime, interpret, close.
    Batch callers should use :class:`InterpretationRuntime` directly so the
    availability check and HTTP client are shared."""
    runtime = InterpretationRuntime(cfg)
    try:
        return runtime.interpret(percept, masked_text)
    finally:
        runtime.close()


def _deferred(detail: str,
              status: InterpretationStatus = InterpretationStatus.deferred,
              failure_class: str = "unavailable") -> InterpretationResult:
    return InterpretationResult(
        items=[], status=status, failure_class=failure_class,
        interpreter="cognitive-interpreter",
        prompt_version=ollama_interpreter.PROMPT_VERSION,
        schema_version=ollama_interpreter.SCHEMA_VERSION,
        detail=detail,
    )
