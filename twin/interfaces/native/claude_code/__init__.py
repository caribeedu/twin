"""Claude Code Hooks adapter — native proof host."""

from .adapter import (
    DEFAULT_OBSERVATION_PROFILE,
    OBSERVATION_PROFILES,
    MissingExternalSessionId,
    build_hooks_object,
    claude_hooks_stdout,
    default_claude_settings_path,
    install_claude_code_hooks,
    merge_hooks_into_settings,
    normalize_claude_code_hook,
    normalize_transcript_identity,
    twin_hook_command,
    uninstall_claude_code_hooks,
    unmerge_hooks_from_settings,
    write_hooks_config,
)

__all__ = [
    "DEFAULT_OBSERVATION_PROFILE",
    "OBSERVATION_PROFILES",
    "MissingExternalSessionId",
    "build_hooks_object",
    "claude_hooks_stdout",
    "default_claude_settings_path",
    "install_claude_code_hooks",
    "merge_hooks_into_settings",
    "normalize_claude_code_hook",
    "normalize_transcript_identity",
    "twin_hook_command",
    "uninstall_claude_code_hooks",
    "unmerge_hooks_from_settings",
    "write_hooks_config",
]
