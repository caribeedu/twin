"""Host-type → HostCapabilities map (adapter frontier only).

The generic ``NativeHostService`` hot path must not branch on provider names.
Adapters should stamp capabilities on ``session_start``; this registry is the
fallback when a known host opens a session without an explicit declaration
(e.g. tests / non-adapter CLI entry). Unknown hosts get fail-closed defaults.
"""

from __future__ import annotations

from ..events import HostCapabilities

# Known host profiles — add new adapters here, never in service.py.
_REGISTRY: dict[str, HostCapabilities] = {
    "claude-code": HostCapabilities.claude_code(),
    "fake-host": HostCapabilities.fake_host(),
}


def capabilities_for_host(host_type: str) -> HostCapabilities:
    """Return declared capabilities for ``host_type``, or fail-closed defaults."""
    key = (host_type or "").strip().lower()
    caps = _REGISTRY.get(key)
    if caps is not None:
        return caps.model_copy(deep=True)
    return HostCapabilities.conservative_default()
