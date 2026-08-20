"""Command Center actions — health/doctor helpers."""

from __future__ import annotations

from types import SimpleNamespace

from twin.interfaces.center import actions


def test_doctor_summary_shape(store, cfg, embedder, tmp_path):
    ws = SimpleNamespace(store=store, cfg=cfg, embedder=embedder, home=tmp_path)
    out = actions.doctor_summary(ws)
    assert "checks_ok" in out
    assert "checks_total" in out
    assert "warnings" in out
    assert out["checks_total"] >= out["checks_ok"]
    assert out["home"]


def test_mcp_client_status_lists_providers(tmp_path, monkeypatch):
    from pathlib import Path

    paths = {
        "cursor": tmp_path / "cursor.json",
        "claude-code": tmp_path / "code.json",
        "claude-desktop": tmp_path / "desktop.json",
    }
    paths["cursor"].write_text(
        '{"mcpServers": {"twin": {}}}', encoding="utf-8",
    )
    monkeypatch.setattr(
        "twin.interfaces.ops._mcp_config_paths",
        lambda: {k: Path(v) for k, v in paths.items()},
    )
    rows = actions.mcp_client_status()
    by_id = {r["id"]: r for r in rows}
    assert by_id["cursor"]["installed"] is True
    assert by_id["claude-code"]["installed"] is False
    assert by_id["claude-desktop"]["label"] == "Claude Desktop"
    assert "path" in by_id["cursor"]
