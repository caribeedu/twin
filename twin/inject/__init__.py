"""Inject — governed packs and Observer slot toward authorized hosts.

Public architecture wall: Sense → Cognize → Inject.
"""

from .context_pack import PackDeadlineExceeded, build_context_pack
from .inject_observer import (
    InjectObserver,
    InjectObserverDecision,
    NoOpInjectObserver,
    get_inject_observer,
    inject_observer_enabled,
)

__all__ = [
    "PackDeadlineExceeded",
    "build_context_pack",
    "InjectObserver",
    "InjectObserverDecision",
    "NoOpInjectObserver",
    "get_inject_observer",
    "inject_observer_enabled",
]
