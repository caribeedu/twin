"""Host-native observation adapters.

Native adapters observe host sessions and call the cognitive core. They do
not assemble Context Packs or create a parallel memory store. MCP remains
available on the same Projects / Sessions / Memories.

Contract: trustworthy ``external_session_id`` required; cwd is never a
conversation identity; hooks are fail-open; security scope freezes at bind.
"""

from .service import NativeHostService, handle_normalized_event

__all__ = ["NativeHostService", "handle_normalized_event"]
