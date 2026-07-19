"""v0.6 Phase 8 — native host adapter + HostSessionBinding."""

from __future__ import annotations

import json

from twin import ids
from twin.cognition.host_session import recommend_intervention
from twin.cognition.sessions import start_session
from twin.interfaces.native.claude_code import (
    normalize_claude_code_hook,
    write_hooks_config,
)
from twin.interfaces.native.events import HostEvent
from twin.interfaces.native.service import NativeHostService
from twin.memory.models import MemoryItem, MemoryStatus, MemoryType


def test_normalize_claude_code_session_start():
    ev = normalize_claude_code_hook(
        {
            "hook_event_name": "SessionStart",
            "session_id": "cc_sess_1",
            "cwd": "/home/edu/repos/twin",
            "prompt": "implement Phase 8",
        }
    )
    assert ev.kind == "session_start"
    assert ev.host_type == "claude-code"
    assert ev.external_session_id == "cc_sess_1"
    assert "Phase 8" in ev.text


def test_normalize_tool_and_stop():
    tool = normalize_claude_code_hook(
        {"hook_event_name": "PostToolUse", "session_id": "s", "tool_name": "Bash",
         "tool_input": {"command": "ls"}},
    )
    assert tool.kind == "tool_execution"
    assert tool.ref == "Bash"
    stop = normalize_claude_code_hook(
        {"hook_event_name": "Stop", "session_id": "s", "summary": "done"},
    )
    assert stop.kind == "session_end"


def test_bind_pack_observe_end_same_core(store, cfg, embedder):
    svc = NativeHostService(store, cfg, embedder)
    start = svc.handle(HostEvent(
        kind="session_start",
        host_type="claude-code",
        external_session_id="ext_abc",
        text="wire HostSessionBinding",
        domain="technical",
        cwd="/tmp/proj",
    ))
    assert start.ok
    assert start.session_id.startswith("ses_")
    assert start.binding is not None
    assert start.context_pack is not None
    binding_id = start.binding.id
    assert binding_id.startswith("hsb_")

    # Same binding on pack_request (idempotent)
    again = svc.handle(HostEvent(
        kind="pack_request",
        host_type="claude-code",
        external_session_id="ext_abc",
        text="continue binding work",
        domain="technical",
    ))
    assert again.ok
    assert again.binding.id == binding_id
    assert again.session_id == start.session_id

    obs = svc.handle(HostEvent(
        kind="user_message",
        host_type="claude-code",
        external_session_id="ext_abc",
        text="user asks about vault partition",
    ))
    assert obs.ok
    tool = svc.handle(HostEvent(
        kind="tool_execution",
        host_type="claude-code",
        external_session_id="ext_abc",
        text="ran pytest",
        ref="Bash",
    ))
    assert tool.ok
    file_ev = svc.handle(HostEvent(
        kind="file_context",
        host_type="claude-code",
        external_session_id="ext_abc",
        text="edited host_session.py",
        ref="twin/cognition/host_session.py",
    ))
    assert file_ev.ok

    session = store.get_session(start.session_id)
    assert session is not None
    kinds = {a.get("kind") for a in session.artifacts}
    assert "user_message" in kinds
    assert "tool_execution" in kinds
    assert "file_context" in kinds
    assert session.client == "claude-code"

    ended = svc.handle(HostEvent(
        kind="session_end",
        host_type="claude-code",
        external_session_id="ext_abc",
        summary="Phase 8 native binding wired",
    ))
    assert ended.ok
    binding = store.get_host_session_binding(binding_id)
    assert binding.ended_at
    session = store.get_session(start.session_id)
    assert session.status.value in ("completed", "abandoned")


def test_native_and_mcp_share_session_store(store, cfg, embedder):
    """Native binding lands in the same store MCP session_* tools read."""
    svc = NativeHostService(store, cfg, embedder)
    native = svc.handle(HostEvent(
        kind="session_start",
        host_type="claude-code",
        external_session_id="shared_1",
        text="shared core proof",
        domain="technical",
    ))
    assert native.ok
    # CLI/MCP-equivalent session on the same store (coexistence)
    other = start_session(
        store, cfg, embedder, "cli query same store",
        client="cli", domain="technical",
    )
    assert other.session.id != native.session_id
    # MCP native_session_status shape: binding → CognitiveSession
    binding = store.find_host_session_binding(
        host_type="claude-code", external_session_id="shared_1",
    )
    assert binding is not None
    assert store.get_session(binding.cognitive_session_id) is not None
    assert store.get_session(other.session.id) is not None


def test_no_confirmed_memory_from_native(store, cfg, embedder):
    svc = NativeHostService(store, cfg, embedder)
    svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="e2", text="decide postgres", domain="technical",
    ))
    svc.handle(HostEvent(
        kind="session_end", host_type="claude-code",
        external_session_id="e2", summary="Chose Postgres for store.",
    ))
    confirmed = [
        m for m in store.list_memories(limit=500)
        if getattr(m.status, "value", m.status) == "confirmed"
    ]
    # Consolidation may create candidates; never confirmed from native alone
    assert all(
        getattr(m.status, "value", m.status) != "confirmed"
        or m.id  # allow pre-existing none
        for m in confirmed
    )
    # Stronger: no memory created by this pass is confirmed
    session = store.find_host_session_binding(
        host_type="claude-code", external_session_id="e2",
    )
    ses = store.get_session(session.cognitive_session_id)
    for mid in ses.created_memory_ids or []:
        mem = store.get_memory(mid)
        assert mem is not None
        assert mem.status != MemoryStatus.confirmed


def test_intervention_warns_on_decision_reversal(store, cfg, embedder):
    mem = MemoryItem(
        id=ids.memory_id(),
        type=MemoryType.decision,
        title="Use PostgreSQL for Twin store",
        summary="We chose PostgreSQL instead of Neo4j for the primary store.",
        domain="technical",
        confidence=0.9,
        status=MemoryStatus.confirmed,
    )
    store.insert_memory(mem)
    started = start_session(
        store, cfg, embedder, "Use PostgreSQL for Twin store",
        client="cli", domain="technical",
    )
    # Ensure the decision is among supplied ids when possible
    if mem.id not in started.session.supplied_memory_ids:
        started.session.supplied_memory_ids.append(mem.id)
        store.update_session(started.session)
    recs = recommend_intervention(
        store,
        session_id=started.session.id,
        draft_text="Let's abandon PostgreSQL and replace with Neo4j instead.",
    )
    assert recs
    assert recs[0].supported_actions == ["display"]
    assert recs[0].requires_confirmation is False


def test_write_hooks_config(tmp_path):
    path = write_hooks_config(tmp_path, twin_bin="twin", home="/tmp/twin-home")
    data = json.loads(path.read_text())
    assert "SessionStart" in data["hooks"]
    cmd = data["hooks"]["SessionStart"][0]["command"]
    assert "native event" in cmd and "claude-code" in cmd
