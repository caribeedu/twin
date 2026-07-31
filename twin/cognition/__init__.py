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
from .episode_pipeline import (
    BrainStage,
    CognitionReport,
    clear_stage_overrides,
    run_episode_cognition,
    set_stage_override,
)
from .pipeline import ExtractReport, extract_pending, extract_percept

__all__ = [
    "BrainStage",
    "CognitionReport",
    "CognitiveAct",
    "ExtractReport",
    "InterpretationResult",
    "InterpretationStatus",
    "InterpretedItem",
    "ReflectResult",
    "clear_stage_overrides",
    "extract_pending",
    "extract_percept",
    "reflect_episode",
    "run_episode_cognition",
    "set_interpreter_override",
    "set_reflect_override",
    "set_stage_override",
]
