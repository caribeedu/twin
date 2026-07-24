"""Normalize Claude Code hook payloads into HostEvent.

Claude Code can invoke Twin via hooks that shell out to:

 twin native event --host claude-code --stdin

Never invents ``external_session_id`` from cwd. Never attributes unknown
hooks to the user. Tool inputs are redacted before persistence.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from ..events import CLAUDE_CODE_CAPABILITIES, HostEvent
from ..redact import redact_payload, redact_text

# Claude Code hook name → HostEvent.kind
_HOOK_KIND = {
    "SessionStart": "session_start",
    "session_start": "session_start",
    "UserPromptSubmit": "user_message",
    "user_prompt_submit": "user_message",
    "PostToolUse": "tool_completed",
    "post_tool_use": "tool_completed",
    "PreToolUse": "tool_requested",
    "pre_tool_use": "tool_requested",
    "Stop": "session_end",
    "stop": "session_end",
    "SessionEnd": "session_end",
    "session_end": "session_end",
    "Notification": "assistant_result",
}


class MissingExternalSessionId(ValueError):
    """Host payload lacked a trustworthy conversation identity."""


def normalize_transcript_identity(path: str) -> str:
    """Stable conversation id from a transcript path (no raw path leakage)."""
    raw = (path or "").strip()
    if not raw:
        raise MissingExternalSessionId("empty transcript_path")
    p = Path(raw).expanduser()
    try:
        p = p.resolve()
    except Exception:
        p = Path(str(p).replace("\\", "/"))
        parts = []
        for part in p.parts:
            if part in ("", "."):
                continue
            if part == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(part)
        p = Path(*parts) if parts else p
    key = str(p).replace("\\", "/").lower()
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return f"transcript:{digest}"


def normalize_claude_code_hook(
    payload: dict[str, Any] | str,
    *,
    hook_name: Optional[str] = None,
    default_cwd: Optional[str] = None,
) -> HostEvent:
    """Map a Claude Code hook JSON blob to a HostEvent.

    Raises ``MissingExternalSessionId`` when the host omits session identity.
    """
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
    known = str(name) in _HOOK_KIND
    kind = _HOOK_KIND.get(str(name), "")
    if not kind:
        # Never invent user_message for unknown hooks.
        if data.get("session_end") or data.get("reason") == "stop":
            kind = "session_end"
        elif data.get("tool_name") or data.get("tool_input"):
            # Ambiguous tool hook without name → unsupported, not completed
            kind = "unsupported_host_event"
        else:
            kind = "unsupported_host_event"

    session_id = str(
        data.get("session_id")
        or data.get("conversation_id")
        or data.get("external_session_id")
        or ""
    ).strip()
    # transcript_path is a fallback identity — normalize to a stable hash key.
    if not session_id and data.get("transcript_path"):
        session_id = normalize_transcript_identity(str(data["transcript_path"]))
    if not session_id:
        raise MissingExternalSessionId(
            "external_session_id required — cwd/project must not identify conversations"
        )

    text = str(
        data.get("prompt")
        or data.get("user_prompt")
        or data.get("message")
        or data.get("text")
        or data.get("content")
        or ""
    )
    tool_phase = None
    tool_call_id = (
        data.get("tool_use_id")
        or data.get("tool_call_id")
        or data.get("toolUseId")
    )
    if kind == "tool_requested":
        tool_phase = "before"
    elif kind == "tool_completed":
        tool_phase = "after"
    elif kind == "tool_failed":
        tool_phase = "failed"

    redacted = False
    redaction_categories: list[str] = []
    if kind in ("tool_requested", "tool_completed", "tool_failed"):
        tool = data.get("tool_name") or data.get("tool") or "tool"
        raw_payload = data.get("tool_response") if kind == "tool_completed" else data.get("tool_input")
        if raw_payload is None:
            raw_payload = data.get("tool_input") or data.get("tool_response") or ""
        if isinstance(raw_payload, (dict, list)):
            clean, cats = redact_payload(raw_payload)
            summary = json.dumps(clean, ensure_ascii=False)[:500]
        else:
            summary, cats = redact_text(str(raw_payload))
            summary = summary[:500]
        if cats:
            redacted = True
            redaction_categories = cats
        if not text:
            text = f"{tool}: {summary}"[:1000]
        else:
            text, more = redact_text(text)
            if more:
                redacted = True
                for c in more:
                    if c not in redaction_categories:
                        redaction_categories.append(c)
    else:
        text, cats = redact_text(text)
        if cats:
            redacted = True
            redaction_categories = cats

    ref = None
    if kind in ("tool_requested", "tool_completed", "tool_failed"):
        ref = str(data.get("tool_name") or data.get("tool") or "") or None
    file_path = data.get("file_path") or data.get("path")
    if file_path and data.get("hook_event_name") in ("FileChanged", "Edit"):
        kind = "file_context"
        ref = str(file_path)
        text = text or str(file_path)

    cwd = data.get("cwd") or default_cwd
    project = data.get("project") or data.get("project_name")
    summary = str(data.get("summary") or data.get("reason") or "")
    event_id = data.get("hook_event_id") or data.get("event_id") or data.get("uuid")

    meta = {
        k: data[k]
        for k in ("permission_mode", "model", "tool_name")
        if k in data
    }
    if not known:
        meta["unrecognized_hook"] = str(name) or True
    if data.get("transcript_path"):
        meta["transcript_identity"] = session_id if session_id.startswith("transcript:") else (
            normalize_transcript_identity(str(data["transcript_path"]))
        )

    delivery_id = data.get("delivery_id") or data.get("hook_delivery_id")
    sequence = data.get("sequence") or data.get("message_index")
    if sequence is not None:
        try:
            sequence = int(sequence)
        except (TypeError, ValueError):
            sequence = None

    return HostEvent(
        kind=kind,
        host_type="claude-code",
        external_session_id=session_id,
        event_id=str(event_id) if event_id else None,
        delivery_id=str(delivery_id) if delivery_id else None,
        sequence=sequence,
        occurred_at=data.get("occurred_at") or data.get("timestamp"),
        tool_call_id=str(tool_call_id) if tool_call_id else None,
        tool_phase=tool_phase,
        text=text,
        ref=ref,
        cwd=str(cwd) if cwd else None,
        project=str(project) if project else None,
        domain=data.get("domain"),
        task_profile=data.get("task_profile"),
        persona=data.get("persona"),
        purpose=data.get("purpose"),
        audience=data.get("audience"),
        summary=summary,
        abandoned=bool(data.get("abandoned") or data.get("reason") == "abort"),
        redacted=redacted,
        redaction_categories=redaction_categories,
        metadata=meta,
    )


def write_hooks_config(
    target_dir: Path,
    *,
    twin_bin: str = "twin",
    home: Optional[str] = None,
) -> Path:
    """Write a Claude Code ``settings`` hooks snippet that calls Twin.

    Observation hooks are fail-open (CLI exits 0 even when Twin fails).
    Context Pack is only emitted for SessionStart.
    """
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    home_flag = f' --home "{home}"' if home else ""
    cmd = (
        f'{twin_bin}{home_flag} native event --host claude-code '
        f'--hook "$CLAUDE_HOOK_EVENT" --stdin --fail-open'
    )
    config = {
        "hooks": {
            "SessionStart": [{"type": "command", "command": cmd}],
            "UserPromptSubmit": [{"type": "command", "command": cmd}],
            "PreToolUse": [{"type": "command", "command": cmd}],
            "PostToolUse": [{"type": "command", "command": cmd}],
            "Stop": [{"type": "command", "command": cmd}],
        },
        "twin_native": {
            "host": "claude-code",
            "capabilities": CLAUDE_CODE_CAPABILITIES.model_dump(),
            "protocol": {
                "stdout": "JSON NativeEventResult; context_pack only for SessionStart/pack_request",
                "stderr": "diagnostics / twin errors (never blocks the host when --fail-open)",
                "external_session_id": "required — cwd is never used as conversation identity",
            },
            "note": (
                "proof adapter. Merge `hooks` into Claude Code "
                "settings. Twin observes via the same cognitive core as MCP."
            ),
        },
    }
    path = target_dir / "twin-claude-code-hooks.json"
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return path
