"""Shared Command Center actions — doctor / health / MCP helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from twin.workspace import Workspace

_MCP_LABELS = {
    "claude-desktop": "Claude Desktop",
    "claude-code": "Claude Code",
    "cursor": "Cursor",
}


def doctor_summary(ws: Workspace) -> dict[str, Any]:
    from twin.interfaces.ops import OK, doctor

    checks = doctor(ws.cfg)
    ok = sum(1 for c in checks if c.status == OK)
    warn = [
        {"name": c.name, "detail": c.detail}
        for c in checks
        if c.status != OK
    ][:8]
    return {
        "home": str(ws.cfg.home),
        "checks_ok": ok,
        "checks_total": len(checks),
        "warnings": warn,
        "extractor": ws.cfg.extractor,
        "embedder": ws.cfg.embedder,
        "llm": getattr(ws.cfg, "normalized_llm_provider", ""),
    }


def _display_path(path: Path) -> str:
    try:
        home = Path.home()
        resolved = path.expanduser()
        if resolved == home / ".claude.json":
            return "~/.claude.json"
        if resolved == home / ".cursor/mcp.json":
            return "~/.cursor/mcp.json"
        try:
            return f"~/{resolved.relative_to(home)}"
        except ValueError:
            return str(resolved)
    except Exception:
        return str(path)


def mcp_client_status() -> list[dict[str, Any]]:
    """Installation status per known MCP host (claude-desktop / claude-code / cursor)."""
    from twin.interfaces.ops import _mcp_config_paths, _twin_entry_installed

    rows: list[dict[str, Any]] = []
    for client, path in _mcp_config_paths().items():
        installed = _twin_entry_installed(path)
        rows.append({
            "id": client,
            "label": _MCP_LABELS.get(client, client),
            "installed": installed,
            "path": _display_path(path),
        })
    return rows
