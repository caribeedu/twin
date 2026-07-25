"""Native host adapter — bindings, observations, fail-open hooks."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from twin import ids
from twin.cognition.host_session import recommend_intervention
from twin.cognition.sessions import start_session
from twin.interfaces.native.claude_code import (
    MissingExternalSessionId,
    build_hooks_object,
    claude_hooks_stdout,
    install_claude_code_hooks,
    merge_hooks_into_settings,
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


def test_identical_text_without_event_id_preserved(store, cfg, embedder):
    """Same content ≠ same delivery — do not fingerprint-collapse."""
    svc = NativeHostService(store, cfg, embedder)
    svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="dup_txt", text="x", domain="technical",
    ))
    a = svc.handle(HostEvent(
        kind="user_message", host_type="claude-code",
        external_session_id="dup_txt", text="sim",
    ))
    b = svc.handle(HostEvent(
        kind="user_message", host_type="claude-code",
        external_session_id="dup_txt", text="sim",
    ))
    assert a.ok and b.ok
    assert not b.extras.get("duplicated")
    ses = store.get_session(a.session_id)
    sims = [x for x in ses.artifacts if x.get("note") == "sim"]
    assert len(sims) == 2


def test_same_tool_text_different_call_ids_preserved(store, cfg, embedder):
    svc = NativeHostService(store, cfg, embedder)
    svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="tools", text="x", domain="technical",
    ))
    a = svc.handle(HostEvent(
        kind="tool_completed", host_type="claude-code",
        external_session_id="tools", text="Bash: pytest passed",
        tool_call_id="call_a", tool_phase="after",
    ))
    b = svc.handle(HostEvent(
        kind="tool_completed", host_type="claude-code",
        external_session_id="tools", text="Bash: pytest passed",
        tool_call_id="call_b", tool_phase="after",
    ))
    assert a.ok and b.ok
    assert not b.extras.get("duplicated")
    # Same tool_call_id+phase retries collapse
    c = svc.handle(HostEvent(
        kind="tool_completed", host_type="claude-code",
        external_session_id="tools", text="Bash: pytest passed",
        tool_call_id="call_a", tool_phase="after",
    ))
    assert c.extras.get("duplicated") is True


def test_fail_open_protocol_hides_traceback(store, cfg, embedder):
    svc = NativeHostService(store, cfg, embedder)
    svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="tb", text="x", domain="technical",
    ))
    with patch.object(store, "append_session_artifact", side_effect=RuntimeError("boom")):
        r = svc.handle(HostEvent(
            kind="user_message", host_type="claude-code",
            external_session_id="tb", text="hi",
        ))
    payload = r.to_dict(include_pack=False)
    assert payload["ok"] is False
    assert payload["error"] == "native observation failed"
    assert "error_id" in payload
    assert "traceback" not in json.dumps(payload).lower()
    assert "error_class" not in payload


def test_transcript_path_normalized():
    from twin.interfaces.native.claude_code import normalize_transcript_identity
    a = normalize_transcript_identity("/home/edu/.claude/./session.jsonl")
    b = normalize_transcript_identity("/home/edu/.claude/session.jsonl")
    assert a == b
    assert a.startswith("transcript:")
    assert "/home/edu" not in a


def test_frozen_vault_on_binding(store, cfg, embedder):
    svc = NativeHostService(store, cfg, embedder)
    r = svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="vault1", text="tech work", domain="technical",
        metadata={"vault_id": "vault_work_acme", "host_capabilities": {"observe_session": True}},
    ))
    assert r.ok
    assert r.binding.vault_id == "vault_work_acme"
    # Capabilities live on binding metadata from SessionStart path
    svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="vault2", text="other", domain="technical",
    ))
    b2 = store.find_active_host_session_binding(
        host_type="claude-code", external_session_id="vault2",
    )
    assert b2 is not None
    assert b2.metadata.get("host_capabilities")
    # Capabilities not repeated on observation artifacts
    svc.handle(HostEvent(
        kind="user_message", host_type="claude-code",
        external_session_id="vault2", text="hi",
    ))
    ses = store.get_session(b2.cognitive_session_id)
    user_arts = [a for a in ses.artifacts if a.get("kind") == "user_message"]
    assert user_arts
    host_meta = (user_arts[0].get("host") or {})
    assert "host_capabilities" not in host_meta


def test_is_unique_violation_narrow():
    import sqlite3

    from twin.memory.store.host_binding_mixin import is_unique_violation

    unique = sqlite3.IntegrityError("UNIQUE constraint failed: host_observed_events.event_id")
    assert is_unique_violation(unique)

    not_null = sqlite3.IntegrityError("NOT NULL constraint failed: host_observed_events.event_id")
    assert not is_unique_violation(not_null)

    fk = sqlite3.IntegrityError("FOREIGN KEY constraint failed")
    assert not is_unique_violation(fk)

    check = sqlite3.IntegrityError("CHECK constraint failed: occurrence")
    assert not is_unique_violation(check)

    class UniqueViolation(Exception):
        pgcode = "23505"

    assert is_unique_violation(UniqueViolation("duplicate key"))

    class Wrapped(Exception):
        pass

    wrapped = Wrapped("outer")
    wrapped.__cause__ = unique
    assert is_unique_violation(wrapped)


def test_not_null_observed_event_not_silent_duplicate(store, cfg, embedder):
    """Integrity errors unrelated to unique must propagate, not become duplicates."""
    import sqlite3

    from twin.memory.store.host_binding_mixin import is_unique_violation

    svc = NativeHostService(store, cfg, embedder)
    start = svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="nn1", text="x", domain="technical",
    ))
    assert start.ok

    def _boom(*_a, **_k):
        raise sqlite3.IntegrityError(
            "NOT NULL constraint failed: host_observed_events.event_id"
        )

    with patch.object(store, "_c_insert", side_effect=_boom):
        r = svc.handle(HostEvent(
            kind="user_message", host_type="claude-code",
            external_session_id="nn1", text="hi", event_id="e1",
        ))
    # Fail-open at service boundary — but must NOT claim duplicated.
    assert not r.ok
    assert r.extras.get("duplicated") is not True
    assert r.error == "native observation failed"
    # Classifier itself must reject NOT NULL
    assert not is_unique_violation(
        sqlite3.IntegrityError("NOT NULL constraint failed: host_observed_events.event_id")
    )


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


def test_write_hooks_config_matcher_group_schema(tmp_path):
    """Claude Code expects matcher groups with nested hooks[], not flat handlers."""
    path = write_hooks_config(tmp_path, twin_bin="twin", home="/tmp/twin-home")
    data = json.loads(path.read_text())
    group = data["hooks"]["SessionStart"][0]
    assert "hooks" in group
    assert group["matcher"] == ""
    cmd = group["hooks"][0]["command"]
    assert group["hooks"][0]["type"] == "command"
    assert "--fail-open" in cmd
    assert "--stdin" in cmd
    assert "native event --host claude-code" in cmd
    # undocumented env var must not be required
    assert "CLAUDE_HOOK_EVENT" not in cmd
    assert data["twin_native"]["capabilities"]["block_action"] is False
    for event in ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"):
        assert event in data["hooks"]
        assert data["hooks"][event][0]["hooks"][0]["type"] == "command"


def test_merge_hooks_preserves_foreign_and_replaces_twin(tmp_path):
    twin = build_hooks_object(twin_bin="twin", home="/tmp/h")
    existing = {
        "permissions": {"allow": ["Bash"]},
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup",
                    "hooks": [{"type": "command", "command": "echo other"}],
                },
                # legacy flat Twin handler must be removed
                {"type": "command", "command": "twin native event --host claude-code --stdin --fail-open"},
            ],
            "Notification": [
                {
                    "matcher": "",
                    "hooks": [{"type": "command", "command": "notify-send hi"}],
                }
            ],
        },
    }
    merged = merge_hooks_into_settings(existing, twin)
    assert merged["permissions"] == {"allow": ["Bash"]}
    starts = merged["hooks"]["SessionStart"]
    assert any(
        g.get("hooks", [{}])[0].get("command") == "echo other" for g in starts
    )
    twin_groups = [
        g for g in starts
        if "native event --host claude-code" in str(g.get("hooks", [{}])[0].get("command"))
    ]
    assert len(twin_groups) == 1
    assert merged["hooks"]["Notification"][0]["hooks"][0]["command"] == "notify-send hi"

    # idempotent reinstall
    again = merge_hooks_into_settings(merged, twin)
    twin_again = [
        g for g in again["hooks"]["SessionStart"]
        if "native event --host claude-code" in str(g.get("hooks", [{}])[0].get("command"))
    ]
    assert len(twin_again) == 1


def test_install_merges_into_settings_with_backup(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text('{"hooks": {"Stop": [{"matcher": "", "hooks": '
                        '[{"type": "command", "command": "echo keep"}]}]}}\n')
    result = install_claude_code_hooks(
        twin_bin="twin",
        home="/tmp/h",
        snippet_dir=tmp_path / "snippet",
        settings_path=settings,
        merge=True,
    )
    assert result["merged"] is True
    assert Path(result["backup"]).exists()
    data = json.loads(settings.read_text())
    assert any(
        h.get("command") == "echo keep"
        for g in data["hooks"]["Stop"] for h in g.get("hooks", [])
    )
    assert any(
        "native event --host claude-code" in h.get("command", "")
        for g in data["hooks"]["SessionStart"] for h in g.get("hooks", [])
    )


def test_claude_hooks_stdout_session_start_pack():
    out = claude_hooks_stdout(
        hook_event_name="SessionStart",
        ok=True,
        context_pack="remember the Atlas webhook decision",
    )
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "Atlas" in out["hookSpecificOutput"]["additionalContext"]
    assert out["suppressOutput"] is True
    assert claude_hooks_stdout(
        hook_event_name="PreToolUse", ok=True, context_pack=None,
    ) is None
    assert claude_hooks_stdout(
        hook_event_name="SessionStart", ok=False, error="boom",
    ) is None
