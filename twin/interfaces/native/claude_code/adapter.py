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
#
# Provider Stop = end of *agent turn* (fires every reply) → universal
# ``turn_completed``. SessionEnd = chat actually closes → ``session_end``.
# Twin only consolidates on SessionEnd. Never invent cognitive text for
# structural turn boundaries.
_HOOK_KIND = {
    "SessionStart": "session_start",
    "session_start": "session_start",
    "UserPromptSubmit": "user_message",
    "user_prompt_submit": "user_message",
    "PostToolUse": "tool_completed",
    "post_tool_use": "tool_completed",
    "PreToolUse": "tool_requested",
    "pre_tool_use": "tool_requested",
    "Stop": "turn_completed",
    "stop": "turn_completed",
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
        # SessionEnd-style reasons only — do NOT treat Claude's turn-level
        # Stop (or reason=stop) as session close.
        reason = str(data.get("reason") or "").lower()
        if data.get("session_end") or reason in (
            "clear", "logout", "prompt_input_exit", "other",
        ):
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
        or data.get("last_assistant_message")
        or data.get("assistant_message")
        or ""
    )
    # Structural turn end: never invent cognitive text (no "[turn_end]" markers).
    # Provider reply body, if present, stays in metadata for audit only.
    provider_assistant_text = ""
    if kind == "turn_completed":
        provider_assistant_text = text
        text = ""
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
    if name:
        meta["hook_event_name"] = str(name)
    if not known:
        meta["unrecognized_hook"] = str(name) or True
    # Declare capabilities on the session_start event itself so the generic
    # service can gate pack/turn/session behavior without ever branching on
    # Claude hook names. The install snippet is only a hint for humans.
    if kind == "session_start":
        meta.setdefault("host_capabilities", CLAUDE_CODE_CAPABILITIES.model_dump())
    if provider_assistant_text:
        clean_asst, asst_cats = redact_text(provider_assistant_text)
        if asst_cats:
            redacted = True
            for c in asst_cats:
                if c not in redaction_categories:
                    redaction_categories.append(c)
        meta["provider_assistant_text"] = clean_asst[:2000]
        meta["provider_event"] = str(name) or "Stop"
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


# Marker used to find Twin-owned handlers when merging into Claude settings.
TWIN_HOOK_MARKER = "native event --host claude-code"

# Events Twin wires by default. Schema matches Claude Code settings:
#   hooks.<Event> = [ { matcher?, hooks: [ { type, command } ] } ]
# See https://code.claude.com/docs/en/hooks-guide
#
# Observation profiles trade latency/noise for coverage. Lifecycle hooks
# (SessionStart / UserPromptSubmit / Stop / SessionEnd) are always present;
# tool observation grows with the profile:
#   minimal  — lifecycle only (no tool events)
#   standard — + PostToolUse (results that changed state) [default]
#   verbose  — + PreToolUse (every tool request; noisiest)
_LIFECYCLE_HOOK_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "Stop",
    "SessionEnd",
)
OBSERVATION_PROFILES: dict[str, tuple[str, ...]] = {
    "minimal": _LIFECYCLE_HOOK_EVENTS,
    "standard": _LIFECYCLE_HOOK_EVENTS + ("PostToolUse",),
    "verbose": _LIFECYCLE_HOOK_EVENTS + ("PostToolUse", "PreToolUse"),
}
DEFAULT_OBSERVATION_PROFILE = "standard"


def _profile_hook_events(profile: str) -> tuple[str, ...]:
    """Ordered hook events for an observation profile (SessionStart first)."""
    events = OBSERVATION_PROFILES.get(profile)
    if events is None:
        raise ValueError(
            f"unknown observation profile {profile!r} — "
            f"choose from {sorted(OBSERVATION_PROFILES)}"
        )
    order = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
             "Stop", "SessionEnd"]
    return tuple(e for e in order if e in events)


# Back-compat: default install event tuple (standard profile).
_DEFAULT_HOOK_EVENTS = _profile_hook_events(DEFAULT_OBSERVATION_PROFILE)

# Claude Code defaults UserPromptSubmit command hooks to 30s and discards
# stdout on timeout. Pack assembly needs headroom; SessionEnd consolidates
# (Claude's SessionEnd group budget is tight unless timeout is set).
_HOOK_TIMEOUTS_SEC: dict[str, int] = {
    "SessionStart": 120,
    "UserPromptSubmit": 120,
    "PreToolUse": 30,
    "PostToolUse": 30,
    "Stop": 30,
    "SessionEnd": 120,
}


def twin_hook_command(*, twin_bin: str = "twin", home: Optional[str] = None) -> str:
    """Shell command Claude Code runs for every Twin-owned hook handler.

    Event name comes from stdin JSON (``hook_event_name``) — Claude Code does
    not document a ``$CLAUDE_HOOK_EVENT`` env var. ``--fail-open`` keeps Twin
    failures from blocking the host.
    """
    home_flag = f' --home "{home}"' if home else ""
    return (
        f"{twin_bin}{home_flag} native event --host claude-code "
        f"--stdin --fail-open"
    )


def _matcher_group(
    command: str, *, matcher: str = "", timeout: Optional[int] = None,
) -> dict[str, Any]:
    """One Claude Code matcher group wrapping a single command handler."""
    handler: dict[str, Any] = {"type": "command", "command": command}
    if timeout is not None:
        handler["timeout"] = int(timeout)
    group: dict[str, Any] = {
        "hooks": [handler],
    }
    # Empty matcher = fire on every occurrence (SessionStart sources, all tools, …).
    # Claude silently ignores matcher on events that don't support it.
    if matcher != "":
        group["matcher"] = matcher
    else:
        group["matcher"] = ""
    return group


def build_hooks_object(
    *,
    twin_bin: str = "twin",
    home: Optional[str] = None,
    profile: str = DEFAULT_OBSERVATION_PROFILE,
) -> dict[str, Any]:
    """Claude Code ``hooks`` object (matcher-group schema) for a profile."""
    cmd = twin_hook_command(twin_bin=twin_bin, home=home)
    return {
        event: [_matcher_group(cmd, timeout=_HOOK_TIMEOUTS_SEC.get(event))]
        for event in _profile_hook_events(profile)
    }


def is_twin_hook_handler(handler: Any) -> bool:
    """True when a hook handler object is Twin-owned (safe to replace on reinstall)."""
    if not isinstance(handler, dict):
        return False
    cmd = handler.get("command")
    return isinstance(cmd, str) and TWIN_HOOK_MARKER in cmd


def is_twin_matcher_group(group: Any) -> bool:
    """True when a matcher group contains only Twin handlers (or is Twin-shaped empty)."""
    if not isinstance(group, dict):
        return False
    handlers = group.get("hooks")
    if not isinstance(handlers, list) or not handlers:
        return False
    return all(is_twin_hook_handler(h) for h in handlers)


def merge_hooks_into_settings(
    settings: dict[str, Any],
    twin_hooks: dict[str, Any],
) -> dict[str, Any]:
    """Merge Twin hooks into a Claude Code settings document.

    Idempotent: removes prior Twin-owned matcher groups / flat handlers, then
    inserts the current Twin groups. Never drops unrelated hooks or settings keys.
    """
    out = dict(settings)
    existing = out.get("hooks")
    if not isinstance(existing, dict):
        existing = {}
    merged: dict[str, Any] = {k: list(v) if isinstance(v, list) else v
                              for k, v in existing.items()}

    for event, groups in twin_hooks.items():
        current = merged.get(event)
        kept: list[Any] = []
        if isinstance(current, list):
            for item in current:
                # Current schema: matcher groups with nested hooks[].
                if is_twin_matcher_group(item):
                    continue
                # Legacy flat schema Twin used to write: {type, command} at top level.
                if is_twin_hook_handler(item):
                    continue
                kept.append(item)
        for group in groups:
            kept.append(group)
        merged[event] = kept

    out["hooks"] = merged
    return out


def unmerge_hooks_from_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Strip Twin-owned hooks from a Claude Code settings document.

    Idempotent inverse of :func:`merge_hooks_into_settings`: drops Twin matcher
    groups (and legacy flat handlers) while keeping third-party hooks and all
    other settings keys. Empty hook-event lists are pruned; an empty ``hooks``
    object is removed entirely.
    """
    out = dict(settings)
    existing = out.get("hooks")
    if not isinstance(existing, dict):
        return out
    cleaned: dict[str, Any] = {}
    for event, current in existing.items():
        if not isinstance(current, list):
            cleaned[event] = current
            continue
        kept = [
            item for item in current
            if not is_twin_matcher_group(item) and not is_twin_hook_handler(item)
        ]
        if kept:
            cleaned[event] = kept
    if cleaned:
        out["hooks"] = cleaned
    else:
        out.pop("hooks", None)
    return out


def default_claude_settings_path() -> Path:
    """User-scoped Claude Code settings (all projects on this machine)."""
    return Path.home() / ".claude" / "settings.json"


def _latest_twin_backup(settings_path: Path) -> Optional[Path]:
    """Most recent ``.twin-bak`` sibling for a settings file, if any."""
    backup = settings_path.with_suffix(settings_path.suffix + ".twin-bak")
    return backup if backup.exists() else None


def uninstall_claude_code_hooks(
    *,
    settings_path: Optional[Path] = None,
    restore_backup: bool = False,
) -> dict[str, Any]:
    """Remove Twin hooks from Claude Code settings (inverse of install).

    - default: unmerge only Twin-owned handlers, preserving third-party hooks;
    - ``restore_backup``: overwrite settings with the newest ``.twin-bak``.

    Returns paths + a ``removed`` / ``restored`` flag for the CLI to report.
    """
    path = Path(settings_path) if settings_path else default_claude_settings_path()
    result: dict[str, Any] = {
        "settings": str(path),
        "removed": False,
        "restored": False,
        "backup": None,
    }
    if not path.exists():
        return result

    if restore_backup:
        backup = _latest_twin_backup(path)
        if backup is None:
            raise ValueError(
                f"no {path.name}.twin-bak backup found next to {path} — "
                "re-run without --restore-backup to unmerge Twin hooks instead"
            )
        path.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
        result["restored"] = True
        result["removed"] = True
        result["backup"] = str(backup)
        return result

    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return result
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path} is not valid JSON — fix it manually before uninstalling ({exc})"
        ) from exc
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must be a JSON object")

    cleaned = unmerge_hooks_from_settings(loaded)
    if cleaned != loaded:
        backup = path.with_suffix(path.suffix + ".twin-bak")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        result["backup"] = str(backup)
        path.write_text(json.dumps(cleaned, indent=2) + "\n", encoding="utf-8")
        result["removed"] = True
    return result


def install_claude_code_hooks(
    *,
    twin_bin: str = "twin",
    home: Optional[str] = None,
    snippet_dir: Optional[Path] = None,
    settings_path: Optional[Path] = None,
    merge: bool = True,
    profile: str = DEFAULT_OBSERVATION_PROFILE,
) -> dict[str, Any]:
    """Write the snippet and optionally merge into Claude Code settings.

    Returns paths + merged flag for the CLI to report.
    """
    twin_hooks = build_hooks_object(twin_bin=twin_bin, home=home, profile=profile)
    snippet_dir = Path(snippet_dir) if snippet_dir else None
    if snippet_dir is None:
        raise ValueError("snippet_dir is required")
    snippet_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "hooks": twin_hooks,
        "twin_native": {
            "host": "claude-code",
            "observation_profile": profile,
            "capabilities": CLAUDE_CODE_CAPABILITIES.model_dump(),
            "protocol": {
                "stdout": (
                    "with --fail-open: Claude hook JSON "
                    "(SessionStart → hookSpecificOutput.additionalContext); "
                    "otherwise NativeEventResult JSON"
                ),
                "stderr": "diagnostics / twin errors (never blocks the host when --fail-open)",
                "external_session_id": "required — cwd is never used as conversation identity",
                "hook_event_name": "read from stdin JSON (Claude Code sets hook_event_name)",
            },
            "note": (
                "hooks use Claude Code matcher-group schema. "
                "`twin native install` merges into ~/.claude/settings.json by default."
            ),
        },
    }
    snippet_path = snippet_dir / "twin-claude-code-hooks.json"
    snippet_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    result: dict[str, Any] = {
        "snippet": str(snippet_path),
        "merged": False,
        "settings": None,
        "backup": None,
        "profile": profile,
    }
    if not merge:
        return result

    path = Path(settings_path) if settings_path else default_claude_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    settings: dict[str, Any] = {}
    if path.exists():
        raw = path.read_text(encoding="utf-8").strip()
        if raw:
            try:
                loaded = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path} is not valid JSON — fix it manually before re-running "
                    f"twin native install ({exc})"
                ) from exc
            if not isinstance(loaded, dict):
                raise ValueError(f"{path} must be a JSON object")
            settings = loaded
            backup = path.with_suffix(path.suffix + ".twin-bak")
            backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            result["backup"] = str(backup)

    merged = merge_hooks_into_settings(settings, twin_hooks)
    path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    result["merged"] = True
    result["settings"] = str(path)
    return result


def write_hooks_config(
    target_dir: Path,
    *,
    twin_bin: str = "twin",
    home: Optional[str] = None,
    profile: str = DEFAULT_OBSERVATION_PROFILE,
) -> Path:
    """Write a Claude Code hooks snippet that calls Twin (snippet only, no merge).

    Observation hooks are fail-open (CLI exits 0 even when Twin fails).
    Context Pack is only emitted for SessionStart (as additionalContext).
    """
    result = install_claude_code_hooks(
        twin_bin=twin_bin,
        home=home,
        snippet_dir=Path(target_dir),
        merge=False,
        profile=profile,
    )
    return Path(result["snippet"])


def claude_hooks_stdout(
    *,
    hook_event_name: str,
    ok: bool,
    context_pack: Optional[str] = None,
    error: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Stdout payload Claude Code understands when Twin runs as a hook.

    - SessionStart / UserPromptSubmit with a pack →
      ``hookSpecificOutput.additionalContext`` (UserPromptSubmit is how Twin
      recovers when SessionStart had no domain signal)
    - Other events → ``None`` (silent success; observation already persisted)
    - Failures under ``--fail-open`` → ``None`` (stderr carries diagnostics)
    """
    if not ok:
        return None
    if not context_pack:
        return None
    name = str(hook_event_name or "")
    if name in ("SessionStart", "session_start"):
        claude_event = "SessionStart"
    elif name in ("UserPromptSubmit", "user_prompt_submit", "user_message"):
        claude_event = "UserPromptSubmit"
    else:
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": claude_event,
            "additionalContext": context_pack,
        },
        "suppressOutput": True,
    }
