"""Claude Code Hooks adapter — Phase 8 native proof host."""

from .adapter import (
    MissingExternalSessionId,
    normalize_claude_code_hook,
    normalize_transcript_identity,
    write_hooks_config,
)

__all__ = [
    "MissingExternalSessionId",
    "normalize_claude_code_hook",
    "normalize_transcript_identity",
    "write_hooks_config",
]
