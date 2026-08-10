"""Operational ergonomics (twin.interfaces.ops): doctor + setup."""

import json

from twin.interfaces.ops import doctor, setup_mcp, setup_postgres


def test_doctor_reports_all_areas(cfg):
    checks = doctor(cfg)
    names = {c.name for c in checks}
    by_name = {c.name: c for c in checks}
    assert "store:sqlite" in names
    assert "store:migrations" in names
    assert "embedder" in names
    assert "config:policies" in names and "config:judgment" in names
    assert by_name["config:policies"].status == "ok"
    assert by_name["embedder"].detail  # resolved embedder name
    # no ollama server in tests → warn, never fail
    ollama = [c for c in checks if c.name.startswith("ollama")]
    assert ollama and all(c.status == "warn" for c in ollama)
    assert all(c.status in ("ok", "warn", "fail") for c in checks)


def test_doctor_flags_review_backlog(cfg, store, embedder):
    from tests.paths import EXAMPLES
    from twin.cognition import extract_pending
    from twin.sense.sensory import sense_paths

    percepts, _ = sense_paths([EXAMPLES])
    for p in percepts:
        store.insert_percept(p)
    extract_pending(store, cfg, embedder)
    queue = {c.name: c for c in doctor(cfg)}["review:queue"]
    assert queue.status == "warn"
    assert "awaiting review" in queue.detail


def test_doctor_runtime_queue_ok_when_empty(cfg):
    check = {c.name: c for c in doctor(cfg)}["runtime:queue"]
    assert check.status == "ok"
    assert "no pending" in check.detail


def test_doctor_flags_pending_runtime_jobs(cfg, store):
    from twin.runtime.models import JobKind
    from twin.runtime.queue import RuntimeQueue

    RuntimeQueue(store).enqueue(JobKind.session_domain_resolve, payload={"x": 1})
    checks = {c.name: c for c in doctor(cfg)}
    assert checks["runtime:queue"].status == "warn"
    assert "twin runtime start" in checks["runtime:queue"].detail


def test_setup_mcp_writes_and_merges_config(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    lines = setup_mcp(cfg, "cursor")
    path = tmp_path / ".cursor/mcp.json"
    assert path.exists() and str(path) in lines[0]
    config = json.loads(path.read_text())
    assert config["mcpServers"]["twin"]["args"] == ["mcp"]

    # merging preserves other servers
    config["mcpServers"]["other"] = {"command": "x"}
    path.write_text(json.dumps(config))
    setup_mcp(cfg, "cursor")
    merged = json.loads(path.read_text())
    assert set(merged["mcpServers"]) == {"twin", "other"}

    assert "unknown client" in setup_mcp(cfg, "vim")[0]


def test_setup_postgres_explains_when_not_postgres(cfg):
    lines = setup_postgres(cfg)
    assert "does not point at Postgres" in lines[0]
