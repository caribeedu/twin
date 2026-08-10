"""Cognize services — interpret, episodes, sessions (ex-``twin.cognize.services``).

Folded under Cognize as part of package walls. Prefer ``twin.cognize``
and ``twin.inject`` / ``twin.llm`` for new call sites.
"""
"""Cognitive Core — interpret, packs, episodes (transitional package).

Public walls are Sense → Cognize → Inject. This package is folding into:

- ``twin.cognize`` — narrative pipeline + interpret/reflect services
- ``twin.inject`` — governed packs + Observer slot (target)
- ``twin.llm`` — provider adapters (target)

See docs/ARCHITECTURE.md § Code packages. Prefer Narrative / Stance vocabulary
in product surfaces; do not treat ``Memory*`` as the durable product noun.

Services still hosted here today:

- interpretation: percepts → grounded, act-aware candidates (LLM-or-defer)
- dedupe: duplicate / contradiction detection
- observer / inject_observer: attention slot toward the host conversation
- context_pack: Inject recall — compact, firewall-filtered pack for hosts
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
