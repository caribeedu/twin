"""Host-native observation adapters (v0.6 Phase 8).

Native adapters observe host sessions and call the cognitive core. They do
not assemble Context Packs or create a parallel memory store. MCP remains
available on the same Projects / Sessions / Memories.
"""

from .service import NativeHostService, handle_normalized_event

__all__ = ["NativeHostService", "handle_normalized_event"]
