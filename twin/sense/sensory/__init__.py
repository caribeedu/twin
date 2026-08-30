"""Sensory Layer — the system's senses.

Each connector to the external world is a **Sensor**. Sensors capture raw
**Signals** (files, exports, streams) and normalize them into **Percepts**,
the single contract the Cognitive Core consumes. Adding a new source of
context (email, calendar, browser, audio, ...) means writing a new Sensor —
nothing downstream changes.
"""

from .base import Sensor, registry, sense_paths
from .percept import Percept

__all__ = ["Percept", "Sensor", "registry", "sense_paths"]
