"""Cognitive Core — turns percepts into memory and memory into context.

- interpretation: percepts → grounded, act-aware candidate memories
 via a local LLM cognitive interpreter; when no interpreter is available the
 percept is deferred and retried, never guessed at by lexical rules. An
 explicit heuristic mode remains for fully offline detection.
- dedupe: duplicate / contradiction detection
- observer: attention — suggests memories for the current task
- context_pack: recall — compact, firewall-filtered context for external LLMs
"""

from .interpreter import (
    CognitiveAct,
    InterpretationResult,
    InterpretationStatus,
    InterpretedItem,
    set_interpreter_override,
)
from .episode_reflect import (
    ReflectResult,
    reflect_episode,
    set_reflect_override,
)
from .pipeline import ExtractReport, extract_pending, extract_percept

__all__ = [
    "CognitiveAct",
    "ExtractReport",
    "InterpretationResult",
    "InterpretationStatus",
    "InterpretedItem",
    "ReflectResult",
    "extract_pending",
    "extract_percept",
    "reflect_episode",
    "set_interpreter_override",
    "set_reflect_override",
]
