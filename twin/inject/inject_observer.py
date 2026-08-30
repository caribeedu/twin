"""Inject Observer — reserved slot for conversation-turn injection decisions.

Default is a no-op stub. Must not raise Reflections or commit Narratives.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class InjectObserverDecision:
    inject: bool = False
    reason: str = "stub"
    query: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class InjectObserver:
    """Decide whether/what to inject from committed substrate during a turn."""

    def observe_turn(
        self,
        store: Any,
        *,
        text: str = "",
        session_id: str = "",
        **_: Any,
    ) -> InjectObserverDecision:
        raise NotImplementedError


class NoOpInjectObserver(InjectObserver):
    def observe_turn(
        self,
        store: Any,
        *,
        text: str = "",
        session_id: str = "",
        **_: Any,
    ) -> InjectObserverDecision:
        return InjectObserverDecision(inject=False, reason="noop")


def inject_observer_enabled() -> bool:
    return os.environ.get("TWIN_INJECT_OBSERVER", "0") == "1"


def get_inject_observer() -> InjectObserver:
    if not inject_observer_enabled():
        return NoOpInjectObserver()
    return NoOpInjectObserver()
