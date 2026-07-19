"""Normalize Claude Code hook payloads into HostEvent.

Claude Code can invoke Twin via hooks that shell out to:

    twin native event --host claude-code --stdin

Hook names (common): SessionStart, UserPromptSubmit, PostToolUse, Stop.
Payload shapes vary by version — this adapter is defensive and only maps
fields Twin needs. It never treats the hook payload as Memory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from ..events import HostEvent

# Claude Code hook name → HostEvent.kind
_HOOK_KIND = {
    "SessionStart": "session_start",
    "session_start": "session_start",
    "UserPromptSubmit": "user_message",
    "user_prompt_submit": "user_message",
    "PostToolUse": "tool_execution",
    "post_tool_use": "tool_execution",
    "Stop": "session_end",
    "stop": "session_end",
    "SessionEnd": "session_end",
    "session_end": "session_end",
    "Notification": "assistant_result",
    "PreToolUse": "tool_execution",
}


def normalize_claude_code_hook(
    payload: dict[str, Any] | str,
    *,
    hook_name: Optional[str] = None,
    default_cwd: Optional[str] = None,
) -> HostEvent:
    """Map a Claude Code hook JSON blob to a HostEvent."""
    if isinstance(payload, str):
        data = json.loads(payload) if payload.strip() else {}
    else:
        data = dict(payload or {})

    name = (
        hook_name
        or data.get("hook_event_name")
        or data.get("hook_name")
        or data.get("event")
        or data.get("type")
        or ""
    )
    kind = _HOOK_KIND.get(str(name), "")
    if not kind:
        # Infer from fields when the host omits the hook name
        if data.get("prompt") or data.get("user_prompt"):
            kind = "user_message"
        elif data.get("tool_name") or data.get("tool_input"):
            kind = "tool_execution"
        elif data.get("session_end") or data.get("reason") == "stop":
            kind = "session_end"
        else:
            kind = "user_message"

    session_id = str(
        data.get("session_id")
        or data.get("conversation_id")
        or data.get("transcript_path")
        or data.get("external_session_id")
        or ""
    )
    if not session_id:
        # Last resort: stable-ish id from cwd so bind still works
        cwd = data.get("cwd") or default_cwd or ""
        session_id = f"claude-code:{cwd or 'default'}"

    text = str(
        data.get("prompt")
        or data.get("user_prompt")
        or data.get("message")
        or data.get("text")
        or data.get("content")
        or ""
    )
    if kind == "tool_execution" and not text:
        tool = data.get("tool_name") or data.get("tool") or "tool"
        summary = data.get("tool_response") or data.get("tool_input") or ""
        if isinstance(summary, dict):
            summary = json.dumps(summary, ensure_ascii=False)[:500]
        text = f"{tool}: {summary}"[:1000]

    ref = None
    if kind == "tool_execution":
        ref = str(data.get("tool_name") or data.get("tool") or "") or None
    file_path = data.get("file_path") or data.get("path")
    if file_path and kind in ("user_message", "tool_execution"):
        # Promote path-bearing hooks to file_context when appropriate
        if data.get("hook_event_name") in ("FileChanged", "Edit"):
            kind = "file_context"
            ref = str(file_path)
            text = text or str(file_path)

    cwd = data.get("cwd") or default_cwd
    project = data.get("project") or data.get("project_name")
    summary = str(data.get("summary") or data.get("reason") or "")

    meta = {
        k: data[k]
        for k in ("transcript_path", "permission_mode", "model", "tool_name")
        if k in data
    }
    return HostEvent(
        kind=kind,
        host_type="claude-code",
        external_session_id=session_id,
        text=text,
        ref=ref,
        cwd=str(cwd) if cwd else None,
        project=str(project) if project else None,
        domain=data.get("domain"),
        task_profile=data.get("task_profile"),
        summary=summary,
        abandoned=bool(data.get("abandoned") or data.get("reason") == "abort"),
        metadata=meta,
    )


def write_hooks_config(
    target_dir: Path,
    *,
    twin_bin: str = "twin",
    home: Optional[str] = None,
) -> Path:
    """Write a Claude Code ``settings`` hooks snippet that calls Twin.

    Returns the path of the written JSON file. The user (or ``twin native
    install``) merges it into Claude Code settings.
    """
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    home_flag = f' --home "{home}"' if home else ""
    cmd = (
        f'{twin_bin}{home_flag} native event --host claude-code '
        f'--hook "$CLAUDE_HOOK_EVENT" --stdin'
    )
    config = {
        "hooks": {
            "SessionStart": [{"type": "command", "command": cmd}],
            "UserPromptSubmit": [{"type": "command", "command": cmd}],
            "PostToolUse": [{"type": "command", "command": cmd}],
            "Stop": [{"type": "command", "command": cmd}],
        },
        "twin_native": {
            "host": "claude-code",
            "note": (
                "Phase 8 proof adapter. Merge `hooks` into Claude Code "
                "settings. Twin observes via the same cognitive core as MCP."
            ),
        },
    }
    path = target_dir / "twin-claude-code-hooks.json"
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return path
