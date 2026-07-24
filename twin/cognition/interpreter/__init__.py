"""Cognitive interpreter — semantic identification and cataloguing.

The interpreter is the production path for deciding what a Percept *means*.
Deterministic governance downstream is unchanged; this package only produces
grounded, act-aware interpretation candidates (or a deferral when no cognitive
model is available)."""

from .schema import (
    CognitiveAct,
    InterpretationResult,
    InterpretationStatus,
    InterpretedItem,
)
from .service import (
    MAX_INTERPRETATION_ATTEMPTS,
    InterpretationRuntime,
    interpreter_available,
    interpreting_mode,
    run_interpreter,
    set_interpreter_override,
)

__all__ = [
    "CognitiveAct",
    "InterpretationResult",
    "InterpretationRuntime",
    "InterpretationStatus",
    "InterpretedItem",
    "MAX_INTERPRETATION_ATTEMPTS",
    "interpreter_available",
    "interpreting_mode",
    "run_interpreter",
    "set_interpreter_override",
]
