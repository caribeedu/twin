"""Sensor contract and registry.

A Sensor turns raw external signals into Percepts. The MVP sensors are
file-based (they receive paths); future sensors (email, calendar, browser,
audio) may poll APIs or watch streams — the contract stays ``sense() →
Iterable[Percept]``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable, Optional

from .percept import Percept


class Sensor(ABC):
    """Base class for all sensors."""

    #: unique sensor name, e.g. "document", "meeting", "slack", "email"
    name: str = "abstract"

    @abstractmethod
    def can_handle(self, path: Path) -> bool:
        """Whether this sensor knows how to read the given signal."""

    @abstractmethod
    def sense(self, path: Path) -> Iterable[Percept]:
        """Read the raw signal and emit normalized, sealed Percepts."""


class SensorRegistry:
    def __init__(self) -> None:
        self._sensors: list[Sensor] = []

    def register(self, sensor: Sensor) -> None:
        self._sensors.append(sensor)

    def find(self, path: Path) -> Optional[Sensor]:
        for sensor in self._sensors:
            if sensor.can_handle(path):
                return sensor
        return None

    @property
    def sensors(self) -> list[Sensor]:
        return list(self._sensors)


registry = SensorRegistry()


def _default_registry() -> SensorRegistry:
    """Populate the global registry lazily (avoids import cycles)."""
    if not registry.sensors:
        from .sensors.document import DocumentSensor
        from .sensors.meeting import MeetingSensor
        from .sensors.slack import SlackSensor

        registry.register(MeetingSensor())
        registry.register(SlackSensor())
        registry.register(DocumentSensor())
    return registry


def sense_paths(paths: list[str | Path]) -> tuple[list[Percept], list[str]]:
    """Run every file under the given paths through the first sensor that
    can handle it. Returns (percepts, skipped_paths)."""
    reg = _default_registry()
    percepts: list[Percept] = []
    skipped: list[str] = []
    files: list[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            files.extend(sorted(f for f in p.rglob("*") if f.is_file()))
        elif p.is_file():
            files.append(p)
        else:
            skipped.append(str(p))
    for f in files:
        sensor = reg.find(f)
        if sensor is None:
            skipped.append(str(f))
            continue
        try:
            percepts.extend(sensor.sense(f))
        except Exception as exc:
            skipped.append(f"{f} ({exc})")
    return percepts, skipped
