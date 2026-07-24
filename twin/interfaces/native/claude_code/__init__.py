"""Claude Code Hooks adapter — native proof host."""

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
