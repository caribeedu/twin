"""v0.6 Phase 8 — native host adapter review fixes."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from twin import ids
from twin.cognition.host_session import recommend_intervention
from twin.cognition.sessions import start_session
from twin.interfaces.native.claude_code import (
    MissingExternalSessionId,
    normalize_claude_code_hook,
    write_hooks_config,
)
from twin.interfaces.native.events import HostEvent
from twin.interfaces.native.redact import redact_text
from twin.interfaces.native.service import NativeHostService
from twin.memory.models import MemoryItem, MemoryStatus, MemoryType


def test_normalize_requires_session_id():
    with pytest.raises(MissingExternalSessionId):
        normalize_claude_code_hook(
            {"hook_event_name": "SessionStart", "cwd": "/home/edu/twin", "prompt": "x"}
        )


def test_normalize_never_uses_cwd_as_session():
    with pytest.raises(MissingExternalSessionId):
        normalize_claude_code_hook(
            {"hook_event_name": "UserPromptSubmit", "cwd": "/same", "prompt": "hi"},
        )


def test_normalize_tool_phases_and_unknown():
    pre = normalize_claude_code_hook(
        {"hook_event_name": "PreToolUse", "session_id": "s1",
         "tool_name": "Bash", "tool_input": {"command": "ls"}},
    )
    assert pre.kind == "tool_requested"
    assert pre.tool_phase == "before"
    post = normalize_claude_code_hook(
        {"hook_event_name": "PostToolUse", "session_id": "s1",
         "tool_name": "Bash", "tool_response": "ok"},
    )
    assert post.kind == "tool_completed"
    unknown = normalize_claude_code_hook(
        {"hook_event_name": "WeirdHook", "session_id": "s1", "text": "x"},
    )
    assert unknown.kind == "unsupported_host_event"


def test_redact_secrets():
    clean, cats = redact_text("Authorization: Bearer SECRETTOKEN123 api_key=abc")
    assert "SECRETTOKEN123" not in clean
    assert "[REDACTED]" in clean
    assert "bearer" in cats or "authorization" in cats


def test_generation_after_stop(store, cfg, embedder):
    svc = NativeHostService(store, cfg, embedder)
    r1 = svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="reuse_1", text="first", domain="technical",
    ))
    assert r1.ok and r1.binding.occurrence == 1
    ses1 = r1.session_id
    end = svc.handle(HostEvent(
        kind="session_end", host_type="claude-code",
        external_session_id="reuse_1", summary="done",
    ))
    assert end.ok and end.binding.ended_at
    r2 = svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="reuse_1", text="second chat", domain="technical",
    ))
    assert r2.ok
    assert r2.binding.occurrence == 2
    assert r2.session_id != ses1
    # prior binding preserved
    hist = store.list_host_session_bindings(
        host_type="claude-code", external_session_id="reuse_1",
    )
    assert len(hist) == 2
    # events on gen2 do not land on gen1
    svc.handle(HostEvent(
        kind="user_message", host_type="claude-code",
        external_session_id="reuse_1", text="only in second",
        event_id="um1",
    ))
    old = store.get_session(ses1)
    new = store.get_session(r2.session_id)
    assert not any("only in second" in str(a.get("note")) for a in old.artifacts)
    assert any("only in second" in str(a.get("note")) for a in new.artifacts)


def test_duplicate_session_start_reuses_open(store, cfg, embedder):
    svc = NativeHostService(store, cfg, embedder)
    a = svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="dup", text="a", domain="technical",
    ))
    b = svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="dup", text="b", domain="technical",
    ))
    assert a.binding.id == b.binding.id
    assert a.session_id == b.session_id
    assert b.binding.occurrence == 1


def test_same_cwd_different_sessions(store, cfg, embedder):
    svc = NativeHostService(store, cfg, embedder)
    a = svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="chat_a", text="a", domain="technical",
        cwd="/home/edu/twin",
    ))
    b = svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="chat_b", text="b", domain="technical",
        cwd="/home/edu/twin",
    ))
    assert a.binding.id != b.binding.id
    assert a.session_id != b.session_id


def test_reject_missing_external_id(store, cfg, embedder):
    svc = NativeHostService(store, cfg, embedder)
    r = svc.handle(HostEvent(
        kind="user_message", host_type="claude-code",
        external_session_id="", text="hi",
    ))
    assert not r.ok
    assert "external_session_id" in (r.error or "")


def test_orphan_stop_noop(store, cfg, embedder):
    svc = NativeHostService(store, cfg, embedder)
    r = svc.handle(HostEvent(
        kind="session_end", host_type="claude-code",
        external_session_id="never_started", summary="x",
    ))
    assert r.ok
    assert r.extras.get("orphan_session_end") is True


def test_event_after_end_rejected(store, cfg, embedder):
    svc = NativeHostService(store, cfg, embedder)
    svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="e1", text="x", domain="technical",
    ))
    svc.handle(HostEvent(
        kind="session_end", host_type="claude-code",
        external_session_id="e1", summary="bye",
    ))
    r = svc.handle(HostEvent(
        kind="user_message", host_type="claude-code",
        external_session_id="e1", text="late",
    ))
    assert not r.ok
    assert "no active binding" in (r.error or "")


def test_frozen_domain_reject(store, cfg, embedder):
    svc = NativeHostService(store, cfg, embedder)
    svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="frz", text="tech", domain="technical",
    ))
    r = svc.handle(HostEvent(
        kind="pack_request", host_type="claude-code",
        external_session_id="frz", text="personal ask", domain="personal",
    ))
    assert not r.ok
    assert "domain mismatch" in (r.error or "")


def test_idempotent_hook_delivery(store, cfg, embedder):
    svc = NativeHostService(store, cfg, embedder)
    svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="idemp", text="x", domain="technical",
    ))
    a = svc.handle(HostEvent(
        kind="tool_completed", host_type="claude-code",
        external_session_id="idemp", text="ran",
        event_id="hook-99", tool_call_id="tc1", tool_phase="after",
    ))
    b = svc.handle(HostEvent(
        kind="tool_completed", host_type="claude-code",
        external_session_id="idemp", text="ran",
        event_id="hook-99", tool_call_id="tc1", tool_phase="after",
    ))
    assert a.ok and b.ok
    assert b.extras.get("duplicated") is True
    ses = store.get_session(a.session_id)
    tool_arts = [x for x in ses.artifacts if x.get("kind") == "tool_completed"]
    assert len(tool_arts) == 1


def test_tool_input_redacted_in_normalize():
    ev = normalize_claude_code_hook({
        "hook_event_name": "PreToolUse",
        "session_id": "s",
        "tool_name": "Bash",
        "tool_input": {"command": "curl -H 'Authorization: Bearer SUPERSECRET'"},
    })
    assert "SUPERSECRET" not in ev.text
    assert ev.redacted


def test_fail_open_on_store_error(store, cfg, embedder):
    svc = NativeHostService(store, cfg, embedder)
    svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="fo", text="x", domain="technical",
    ))
    with patch.object(store, "append_session_artifact", side_effect=RuntimeError("db locked")):
        r = svc.handle(HostEvent(
            kind="user_message", host_type="claude-code",
            external_session_id="fo", text="hi", event_id="e1",
        ))
    assert not r.ok
    assert r.error == "native observation failed"
    assert r.error_id
    # next valid event still works
    ok = svc.handle(HostEvent(
        kind="user_message", host_type="claude-code",
        external_session_id="fo", text="still ok", event_id="e2",
    ))
    assert ok.ok


def test_no_confirmed_memory_delta(store, cfg, embedder):
    before = {
        m.id for m in store.list_memories(limit=5000)
        if getattr(m.status, "value", m.status) == "confirmed"
    }
    svc = NativeHostService(store, cfg, embedder)
    svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="nm", text="decide postgres", domain="technical",
    ))
    svc.handle(HostEvent(
        kind="assistant_result", host_type="claude-code",
        external_session_id="nm",
        text="We decided to use PostgreSQL for the store.",
        event_id="ar1",
    ))
    svc.handle(HostEvent(
        kind="session_end", host_type="claude-code",
        external_session_id="nm",
        summary="Chose PostgreSQL.",
    ))
    after = {
        m.id for m in store.list_memories(limit=5000)
        if getattr(m.status, "value", m.status) == "confirmed"
    }
    assert after - before == set()


def test_intervention_is_heuristic_display_only(store, cfg, embedder):
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
    assert "Possible decision reversal cue" in recs[0].reason


def test_write_hooks_config_fail_open(tmp_path):
    path = write_hooks_config(tmp_path, twin_bin="twin", home="/tmp/twin-home")
    data = json.loads(path.read_text())
    cmd = data["hooks"]["SessionStart"][0]["command"]
    assert "--fail-open" in cmd
    assert data["twin_native"]["capabilities"]["block_action"] is False
