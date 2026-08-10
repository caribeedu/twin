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
    OBSERVATION_PROFILES,
    MissingExternalSessionId,
    build_hooks_object,
    claude_hooks_stdout,
    install_claude_code_hooks,
    merge_hooks_into_settings,
    normalize_claude_code_hook,
    uninstall_claude_code_hooks,
    unmerge_hooks_from_settings,
    write_hooks_config,
)
from twin.interfaces.native.events import HostCapabilities, HostEvent
from twin.interfaces.native.redact import redact_text
from twin.interfaces.native.service import NativeHostService
from twin.store.models import MemoryItem, MemoryStatus, MemoryType
from twin.interfaces.runtime.handlers import dispatch
from twin.interfaces.runtime.queue import RuntimeQueue


def _drain_runtime_jobs(store, cfg, embedder, *, limit: int = 10) -> int:
    """Run pending runtime jobs in-process (native SessionEnd / domain resolve)."""
    q = RuntimeQueue(store)
    n = 0
    for i in range(limit):
        job = q.claim(f"test-drain-{i}", lease_seconds=60)
        if job is None:
            break
        result = dispatch(store, cfg, embedder, job)
        assert q.complete(job, result)
        n += 1
    return n


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


def test_normalize_stop_is_turn_end_session_end_closes():
    """Provider Stop = turn_completed; SessionEnd = chat closes."""
    stop = normalize_claude_code_hook({
        "hook_event_name": "Stop",
        "session_id": "s1",
        "last_assistant_message": "Done with Atlas.",
    })
    assert stop.kind == "turn_completed"
    assert stop.text == ""
    assert "Atlas" in (stop.metadata or {}).get("provider_assistant_text", "")
    bare_stop = normalize_claude_code_hook({
        "hook_event_name": "Stop", "session_id": "s1",
    })
    assert bare_stop.kind == "turn_completed"
    assert bare_stop.text == ""
    assert "[turn_end]" not in bare_stop.text
    end = normalize_claude_code_hook({
        "hook_event_name": "SessionEnd",
        "session_id": "s1",
        "reason": "prompt_input_exit",
    })
    assert end.kind == "session_end"
    assert end.summary == "prompt_input_exit"


def test_redact_secrets():
    clean, cats = redact_text("Authorization: Bearer SECRETTOKEN123 api_key=abc")
    assert "SECRETTOKEN123" not in clean
    assert "[REDACTED]" in clean
    assert "bearer" in cats or "authorization" in cats


def test_generation_after_session_end(store, cfg, embedder):
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


def test_turn_stop_keeps_binding_open_for_followup(store, cfg, embedder):
    """Claude Stop after first reply must not drop later user messages (Dexter bug)."""
    svc = NativeHostService(store, cfg, embedder)
    start = svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="multi_turn", text="hi", domain="technical",
    ))
    assert start.ok
    svc.handle(HostEvent(
        kind="user_message", host_type="claude-code",
        external_session_id="multi_turn", text="atlas webhooks?",
        event_id="um-atlas",
    ))
    turn = svc.handle(HostEvent(
        kind="turn_completed", host_type="claude-code",
        external_session_id="multi_turn", text="",
        event_id="stop-1",
        metadata={"hook_event_name": "Stop"},
    ))
    assert turn.ok
    assert turn.binding.ended_at is None
    svc.handle(HostEvent(
        kind="tool_requested", host_type="claude-code",
        external_session_id="multi_turn",
        text='Bash: {"command": "grep atlas"}',
        event_id="tool-1", tool_phase="before",
    ))
    dex = svc.handle(HostEvent(
        kind="user_message", host_type="claude-code",
        external_session_id="multi_turn",
        text="I finished Dexter tv serie last week.",
        event_id="um-dexter",
    ))
    assert dex.ok
    assert dex.binding.id == start.binding.id
    close = svc.handle(HostEvent(
        kind="session_end", host_type="claude-code",
        external_session_id="multi_turn", summary="prompt_input_exit",
    ))
    assert close.ok and close.binding.ended_at
    # Consolidation is async (session_complete job) — drain the worker path.
    assert _drain_runtime_jobs(store, cfg, embedder) >= 1
    ses = store.get_session(start.session_id)
    notes = " ".join(str(a.get("note") or "") for a in ses.artifacts)
    assert "Dexter" in notes
    assert "grep atlas" in notes  # still on session
    assert ses.summary_percept_id
    percept = store.get_percept(ses.summary_percept_id)
    assert percept is not None
    assert "Dexter" in percept.content
    assert "grep atlas" not in percept.content
    assert "tool_requested" not in percept.content


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

    from twin.store.store.host_binding_mixin import is_unique_violation

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

    from twin.store.store.host_binding_mixin import is_unique_violation

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
    assert group["hooks"][0]["timeout"] == 120
    assert "--fail-open" in cmd
    assert "--stdin" in cmd
    assert "native event --host claude-code" in cmd
    # undocumented env var must not be required
    assert "CLAUDE_HOOK_EVENT" not in cmd
    assert data["twin_native"]["capabilities"]["block_action"] is False
    for event in ("UserPromptSubmit", "PostToolUse", "Stop", "SessionEnd"):
        assert event in data["hooks"]
        assert data["hooks"][event][0]["hooks"][0]["type"] == "command"
    assert "PreToolUse" not in data["hooks"]  # omitted by default (noise)
    assert data["hooks"]["UserPromptSubmit"][0]["hooks"][0]["timeout"] == 120
    assert data["hooks"]["PostToolUse"][0]["hooks"][0]["timeout"] == 30
    assert data["hooks"]["Stop"][0]["hooks"][0]["timeout"] == 30
    assert data["hooks"]["SessionEnd"][0]["hooks"][0]["timeout"] == 120


def test_observation_profiles_scope_hook_events():
    """minimal ⊂ standard ⊂ verbose; lifecycle hooks always present."""
    minimal = build_hooks_object(profile="minimal")
    standard = build_hooks_object(profile="standard")
    verbose = build_hooks_object(profile="verbose")

    lifecycle = {"SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"}
    for hooks in (minimal, standard, verbose):
        assert lifecycle <= set(hooks)

    assert "PostToolUse" not in minimal
    assert "PreToolUse" not in minimal
    assert "PostToolUse" in standard
    assert "PreToolUse" not in standard  # standard default keeps PreToolUse off
    assert "PostToolUse" in verbose
    assert "PreToolUse" in verbose

    assert set(OBSERVATION_PROFILES) == {"minimal", "standard", "verbose"}


def test_unknown_observation_profile_rejected():
    with pytest.raises(ValueError):
        build_hooks_object(profile="chatty")


def test_install_records_observation_profile(tmp_path):
    result = install_claude_code_hooks(
        twin_bin="twin",
        home="/tmp/h",
        snippet_dir=tmp_path / "snippet",
        merge=False,
        profile="minimal",
    )
    assert result["profile"] == "minimal"
    data = json.loads(Path(result["snippet"]).read_text())
    assert data["twin_native"]["observation_profile"] == "minimal"
    assert "PostToolUse" not in data["hooks"]


def test_uninstall_unmerges_only_twin_hooks(tmp_path):
    settings = tmp_path / "settings.json"
    install_claude_code_hooks(
        twin_bin="twin",
        home="/tmp/h",
        snippet_dir=tmp_path / "snippet",
        settings_path=settings,
        merge=True,
    )
    # Add a foreign hook that uninstall must preserve.
    data = json.loads(settings.read_text())
    data["hooks"].setdefault("Stop", []).append(
        {"matcher": "", "hooks": [{"type": "command", "command": "echo keep"}]}
    )
    settings.write_text(json.dumps(data) + "\n")

    result = uninstall_claude_code_hooks(settings_path=settings)
    assert result["removed"] is True
    cleaned = json.loads(settings.read_text())
    all_cmds = [
        h.get("command", "")
        for groups in cleaned.get("hooks", {}).values()
        for g in groups for h in g.get("hooks", [])
    ]
    assert any("echo keep" in c for c in all_cmds)
    assert not any("native event --host claude-code" in c for c in all_cmds)


def test_uninstall_is_symmetric_with_install(tmp_path):
    settings = tmp_path / "settings.json"
    original = {"permissions": {"allow": ["Bash"]}}
    settings.write_text(json.dumps(original) + "\n")

    install_claude_code_hooks(
        twin_bin="twin",
        home="/tmp/h",
        snippet_dir=tmp_path / "snippet",
        settings_path=settings,
        merge=True,
    )
    uninstall_claude_code_hooks(settings_path=settings)
    cleaned = json.loads(settings.read_text())
    assert cleaned.get("permissions") == {"allow": ["Bash"]}
    assert "hooks" not in cleaned  # no residual empty Twin hooks


def test_uninstall_restore_backup(tmp_path):
    settings = tmp_path / "settings.json"
    original = '{"hooks": {"Stop": [{"matcher": "", "hooks": ' \
               '[{"type": "command", "command": "echo keep"}]}]}}\n'
    settings.write_text(original)
    install_claude_code_hooks(
        twin_bin="twin",
        home="/tmp/h",
        snippet_dir=tmp_path / "snippet",
        settings_path=settings,
        merge=True,
    )
    result = uninstall_claude_code_hooks(settings_path=settings, restore_backup=True)
    assert result["restored"] is True
    assert json.loads(settings.read_text()) == json.loads(original)


def test_uninstall_missing_backup_raises(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text('{"hooks": {}}\n')
    with pytest.raises(ValueError):
        uninstall_claude_code_hooks(settings_path=settings, restore_backup=True)


def test_uninstall_noop_when_no_twin_hooks(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text('{"permissions": {"allow": ["Bash"]}}\n')
    result = uninstall_claude_code_hooks(settings_path=settings)
    assert result["removed"] is False
    assert unmerge_hooks_from_settings(json.loads(settings.read_text())) == \
        json.loads(settings.read_text())


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


def test_claude_hooks_stdout_user_prompt_submit_pack():
    out = claude_hooks_stdout(
        hook_event_name="UserPromptSubmit",
        ok=True,
        context_pack="Atlas webhooks use FastAPI",
    )
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "FastAPI" in out["hookSpecificOutput"]["additionalContext"]


def _seed_confirmed_memory(store, embedder, *, title: str, summary: str, domain: str = "technical"):
    mem = MemoryItem(
        id=ids.memory_id(),
        type=MemoryType.decision,
        domain=domain,
        title=title,
        summary=summary,
        status=MemoryStatus.confirmed,
        confidence=0.9,
    )
    store.insert_memory(mem)
    store.store_embedding(
        mem.id, "memory", embedder.name, embedder.embed(f"{title}\n{summary}"),
    )
    return mem


def test_user_message_upgrades_unclassified_and_emits_pack(store, cfg, embedder):
    """SessionStart empty → first prompt search-votes domain + pack (no LLM)."""
    _seed_confirmed_memory(
        store, embedder,
        title="Atlas webhook stack",
        summary="Atlas webhooks run on FastAPI with schema_version.",
    )
    svc = NativeHostService(store, cfg, embedder)
    start = svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="repack1",
        text="native host session",
    ))
    assert start.ok
    assert start.binding.domain == "unclassified"
    # Fail-closed: scope header may appear, but no memories until domain freezes.
    assert not (start.sources or [])
    assert "webhook" not in (start.context_pack or "").lower()

    msg = svc.handle(HostEvent(
        kind="user_message", host_type="claude-code",
        external_session_id="repack1",
        text="What retry strategy did we decide for Atlas webhooks?",
    ))
    assert msg.ok
    assert msg.binding.domain == "technical"
    assert msg.extras.get("emit_pack") is True
    assert msg.extras.get("domain_upgraded_from") == "unclassified"
    assert msg.binding.metadata.get("domain_resolved_via") == "search"
    assert msg.context_pack and "webhook" in msg.context_pack.lower()

    # Domain now frozen — second prompt observes but does not re-emit upgrade pack
    again = svc.handle(HostEvent(
        kind="user_message", host_type="claude-code",
        external_session_id="repack1",
        text="And what about the payload schema?",
    ))
    assert again.ok
    assert again.binding.domain == "technical"
    assert again.extras.get("emit_pack") is not True
    assert again.context_pack is None


def test_caps_without_user_message_injection_hold_pack(store, cfg, embedder):
    """Host that can't inject on user_message: domain upgrades, pack is held."""
    _seed_confirmed_memory(
        store, embedder,
        title="Atlas webhook stack",
        summary="Atlas webhooks run on FastAPI with schema_version.",
    )
    caps = HostCapabilities.claude_code().model_copy(update={
        "context_injection_events": ["session_start"],
    }).model_dump()
    svc = NativeHostService(store, cfg, embedder)
    start = svc.handle(HostEvent(
        kind="session_start", host_type="native",
        external_session_id="caps-noinject",
        text="native host session",
        metadata={"host_capabilities": caps},
    ))
    assert start.ok
    msg = svc.handle(HostEvent(
        kind="user_message", host_type="native",
        external_session_id="caps-noinject",
        text="What retry strategy did we decide for Atlas webhooks?",
    ))
    assert msg.ok
    # Domain still upgraded (binding scope is host-independent)…
    assert msg.binding.domain == "technical"
    # …but no pack is emitted where the host cannot surface it.
    assert msg.context_pack is None
    assert msg.extras.get("emit_pack") is not True
    assert msg.extras.get("pack_held_no_injection_point") is True
    assert msg.binding.metadata.get("pending_context_pack") is True
    assert msg.binding.metadata.get("pending_context_reason") == "no_injection_point"


def test_caps_display_intervention_false_suppresses(store, cfg, embedder):
    caps = HostCapabilities.claude_code().model_copy(update={
        "display_intervention": False,
    }).model_dump()
    svc = NativeHostService(store, cfg, embedder)
    svc.handle(HostEvent(
        kind="session_start", host_type="native",
        external_session_id="caps-nointervene",
        text="hi", domain="technical",
        metadata={"host_capabilities": caps},
    ))
    res = svc.handle(HostEvent(
        kind="intervene_check", host_type="native",
        external_session_id="caps-nointervene",
        text="I think we should ship without the migration.",
    ))
    assert res.ok
    assert res.interventions == []
    assert res.extras.get("intervention_suppressed") == "display_intervention"


def test_caps_turn_end_unsupported_rejects_turn_completed(store, cfg, embedder):
    caps = HostCapabilities.claude_code().model_copy(update={
        "supports_turn_end": False,
    }).model_dump()
    svc = NativeHostService(store, cfg, embedder)
    svc.handle(HostEvent(
        kind="session_start", host_type="native",
        external_session_id="caps-noturn",
        text="hi", domain="technical",
        metadata={"host_capabilities": caps},
    ))
    res = svc.handle(HostEvent(
        kind="turn_completed", host_type="native",
        external_session_id="caps-noturn", text="", event_id="tc1",
    ))
    assert res.ok is False
    assert res.extras.get("rejected") is True
    assert res.extras.get("capability") == "supports_turn_end"


def test_caps_session_end_unsupported_rejects(store, cfg, embedder):
    caps = HostCapabilities.claude_code().model_copy(update={
        "supports_session_end": False,
    }).model_dump()
    svc = NativeHostService(store, cfg, embedder)
    svc.handle(HostEvent(
        kind="session_start", host_type="native",
        external_session_id="caps-noend",
        text="hi", domain="technical",
        metadata={"host_capabilities": caps},
    ))
    res = svc.handle(HostEvent(
        kind="session_end", host_type="native",
        external_session_id="caps-noend", summary="done",
    ))
    assert res.ok is False
    assert res.extras.get("capability") == "supports_session_end"


def test_claude_session_start_declares_capabilities(store, cfg, embedder):
    """Claude adapter stamps host_capabilities onto the session_start event."""
    event = normalize_claude_code_hook({
        "hook_event_name": "SessionStart",
        "session_id": "caps-decl",
        "prompt": "hi",
    })
    assert event.kind == "session_start"
    assert "host_capabilities" in (event.metadata or {})
    svc = NativeHostService(store, cfg, embedder)
    start = svc.handle(event)
    assert start.ok
    assert start.binding.metadata.get("host_capabilities")


def test_session_start_pack_skipped_over_budget(store, cfg, embedder, monkeypatch):
    """Blown SessionStart budget drops the pack but keeps the binding."""
    from twin.interfaces.native import service as native_service

    monkeypatch.setattr(
        native_service, "_PACK_BUDGET_MS",
        {"session_start": 0.0001, "user_message": 0.0001},
    )
    svc = NativeHostService(store, cfg, embedder)
    start = svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="budget-start", text="hi", domain="technical",
    ))
    assert start.ok
    assert start.binding is not None  # session/binding persisted
    assert start.context_pack is None
    assert start.extras.get("pack_skipped_budget") is True
    assert start.extras.get("emit_pack") is not True
    assert start.binding.metadata.get("pending_context_pack") is True
    assert start.binding.metadata.get("pending_context_reason") == "latency_budget"


def test_user_message_pack_skipped_over_budget(store, cfg, embedder, monkeypatch):
    """Blown user_message budget keeps the domain upgrade, drops the pack."""
    from twin.interfaces.native import service as native_service

    _seed_confirmed_memory(
        store, embedder,
        title="Atlas webhook stack",
        summary="Atlas webhooks run on FastAPI with schema_version.",
    )
    svc = NativeHostService(store, cfg, embedder)
    svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="budget-msg", text="native host session",
    ))
    monkeypatch.setattr(
        native_service, "_PACK_BUDGET_MS",
        {"session_start": 300.0, "user_message": 0.0001},
    )
    msg = svc.handle(HostEvent(
        kind="user_message", host_type="claude-code",
        external_session_id="budget-msg",
        text="What retry strategy did we decide for Atlas webhooks?",
    ))
    assert msg.ok
    assert msg.binding.domain == "technical"  # upgrade persisted
    assert msg.context_pack is None
    assert msg.extras.get("pack_skipped_budget") is True
    assert msg.extras.get("emit_pack") is not True
    assert msg.binding.metadata.get("pending_context_pack") is True
    assert msg.binding.metadata.get("pending_context_reason") == "latency_budget"


def test_session_start_stamps_stable_host_instance(store, cfg, embedder):
    """host_instance is stable per (home, host, user) and never a raw path."""
    from twin.cognition.host_session import host_instance_id

    svc = NativeHostService(store, cfg, embedder)
    start = svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="hostid-1", text="hi", domain="technical",
    ))
    assert start.ok
    hi = start.binding.metadata.get("host_instance")
    assert hi and hi.startswith("host:")
    assert hi == host_instance_id(cfg, "claude-code")
    # No raw home path leaks into the identifier.
    assert str(cfg.home) not in hi

    # New occurrence on the same install → same host_instance.
    svc.handle(HostEvent(
        kind="session_end", host_type="claude-code",
        external_session_id="hostid-1", summary="done",
    ))
    again = svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="hostid-1", text="hi2", domain="technical",
    ))
    assert again.binding.metadata.get("host_instance") == hi


def test_user_message_keeps_unclassified_without_signal(store, cfg, embedder):
    svc = NativeHostService(store, cfg, embedder)
    svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="repack2", text="hi",
    ))
    msg = svc.handle(HostEvent(
        kind="user_message", host_type="claude-code",
        external_session_id="repack2",
        text="hey there",  # no domain keywords / no search vote
    ))
    assert msg.ok
    assert msg.binding.domain == "unclassified"
    assert msg.context_pack is None
    assert msg.extras.get("emit_pack") is not True
    # Background LLM resolve is enqueued — never sync on the hook.
    assert msg.extras.get("domain_resolve_job_id")
    assert msg.extras.get("needs_domain_confirmation") is True


def test_domain_upgrade_does_not_widen_auth_identity(store, cfg, embedder):
    """Semantic domain resolve must not rewrite persona/vault/principal."""
    _seed_confirmed_memory(
        store, embedder,
        title="Atlas webhook stack",
        summary="Atlas webhooks run on FastAPI with schema_version.",
    )
    svc = NativeHostService(store, cfg, embedder)
    start = svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="auth-freeze",
        text="native host session",
        persona="individual",
        purpose="task_execution",
        audience="self",
    ))
    assert start.ok
    b0 = start.binding
    persona0, purpose0, audience0 = b0.persona, b0.purpose, b0.audience
    principal0, vault0 = b0.principal_id, b0.vault_id
    ses0 = store.get_session(start.session_id)
    assert ses0 is not None
    assert ses0.tool_id == "native-host"
    assert ses0.client == "claude-code"

    msg = svc.handle(HostEvent(
        kind="user_message", host_type="claude-code",
        external_session_id="auth-freeze",
        text="What retry strategy did we decide for Atlas webhooks?",
    ))
    assert msg.ok
    assert msg.binding.domain == "technical"
    assert msg.binding.persona == persona0
    assert msg.binding.purpose == purpose0
    assert msg.binding.audience == audience0
    assert msg.binding.principal_id == principal0
    assert msg.binding.vault_id == vault0


def test_turn_completed_never_enters_session_summary(store, cfg, embedder):
    svc = NativeHostService(store, cfg, embedder)
    start = svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="turn-clean",
        text="hi", domain="technical",
    ))
    svc.handle(HostEvent(
        kind="user_message", host_type="claude-code",
        external_session_id="turn-clean",
        text="i like pineapple juice", event_id="um1",
    ))
    svc.handle(HostEvent(
        kind="turn_completed", host_type="claude-code",
        external_session_id="turn-clean", text="", event_id="tc1",
        metadata={"provider_assistant_text": "Noted.", "provider_event": "Stop"},
    ))
    end = svc.handle(HostEvent(
        kind="session_end", host_type="claude-code",
        external_session_id="turn-clean", summary="done",
    ))
    assert end.ok
    assert _drain_runtime_jobs(store, cfg, embedder) >= 1
    ses = store.get_session(start.session_id)
    assert ses.summary_percept_id
    content = store.get_percept(ses.summary_percept_id).content
    assert "pineapple" in content.lower()
    assert "[turn_end]" not in content
    assert "turn_completed" not in content


def test_hot_path_user_message_never_calls_llm(store, cfg, embedder, monkeypatch):
    """Search-vote / observe must not call read_context on the hook path."""
    calls = {"n": 0}

    def boom(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("read_context must not run on native hot path")

    monkeypatch.setattr("twin.cognition.observer.read_context", boom)
    svc = NativeHostService(store, cfg, embedder)
    svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="no-llm-hot", text="hi",
    ))
    msg = svc.handle(HostEvent(
        kind="user_message", host_type="claude-code",
        external_session_id="no-llm-hot",
        text="hey there random chatter",
    ))
    assert msg.ok
    assert calls["n"] == 0


def test_pending_context_pack_emitted_on_next_user_message(store, cfg, embedder, monkeypatch):
    from twin.cognition.observer import ObserverReading
    from twin.interfaces.runtime.handlers import handle_session_domain_resolve
    from twin.interfaces.runtime.models import JobKind, RuntimeJob

    svc = NativeHostService(store, cfg, embedder)
    start = svc.handle(HostEvent(
        kind="session_start", host_type="claude-code",
        external_session_id="pending-pack",
        text="native host session",
    ))
    assert start.binding.domain == "unclassified"
    msg = svc.handle(HostEvent(
        kind="user_message", host_type="claude-code",
        external_session_id="pending-pack",
        text="hey", event_id="um0",
    ))
    assert msg.extras.get("domain_resolve_job_id")
    monkeypatch.setattr(
        "twin.cognition.observer.read_context",
        lambda *_a, **_k: ObserverReading(
            domain="technical", task_profile="coding", mode="llm",
            confidences={"domain": 0.9, "task_profile": 0.8, "project": 0.0},
        ),
    )
    job = RuntimeJob(
        kind=JobKind.session_domain_resolve,
        payload={"binding_id": start.binding.id},
    )
    result = handle_session_domain_resolve(store, cfg, embedder, job)
    assert result["ok"] is True
    binding = store.get_host_session_binding(start.binding.id)
    assert binding.domain == "technical"
    assert binding.metadata.get("pending_context_pack") is True

    nxt = svc.handle(HostEvent(
        kind="user_message", host_type="claude-code",
        external_session_id="pending-pack",
        text="continue with Atlas", event_id="um1",
    ))
    assert nxt.ok
    assert nxt.extras.get("pending_context_pack_emitted") is True
    assert nxt.extras.get("emit_pack") is True
    assert nxt.context_pack is not None
    refreshed = store.get_host_session_binding(start.binding.id)
    assert refreshed.metadata.get("pending_context_pack") is not True


def test_fake_host_adapter_uses_universal_events_only(store, cfg, embedder):
    """A host that never imports claude_code still drives the same core."""
    # Local fake adapter — only HostEvent, no provider module.
    def fake_normalize(payload: dict) -> HostEvent:
        return HostEvent(
            kind=payload["kind"],
            host_type="fake-host",
            external_session_id=payload["session_id"],
            text=payload.get("text", ""),
            event_id=payload.get("event_id"),
            domain=payload.get("domain"),
            metadata={
                "host_capabilities": HostCapabilities.fake_host().model_dump(),
            },
        )

    svc = NativeHostService(store, cfg, embedder)
    start = svc.handle(fake_normalize({
        "kind": "session_start", "session_id": "fake-1",
        "text": "build the queue", "domain": "technical",
    }))
    assert start.ok
    assert start.binding.host_type == "fake-host"
    ses = store.get_session(start.session_id)
    assert ses.client == "fake-host"
    assert ses.tool_id == "native-host"
    turn = svc.handle(fake_normalize({
        "kind": "turn_completed", "session_id": "fake-1", "event_id": "t1",
    }))
    assert turn.ok and turn.binding.ended_at is None
    end = svc.handle(fake_normalize({
        "kind": "session_end", "session_id": "fake-1", "text": "done",
    }))
    assert end.ok and end.binding.ended_at
    import twin.interfaces.native.service as ns
    src = Path(ns.__file__).read_text(encoding="utf-8")
    assert "from .claude_code" not in src
    assert "from twin.interfaces.native.claude_code" not in src
    assert "claude-code" not in src


def test_host_capabilities_default_is_fail_closed():
    caps = HostCapabilities.conservative_default()
    assert caps.supports_session_start is True
    assert caps.supports_session_end is False
    assert caps.supports_turn_end is False
    assert caps.supports_user_message is False
    assert caps.supports_tool_events is False
    assert caps.supports_context_injection is False
    assert caps.context_injection_events == []
    assert caps.display_intervention is False


def test_capabilities_registry_is_adapter_frontier_only():
    from twin.interfaces.native.adapters.registry import capabilities_for_host

    unknown = capabilities_for_host("unknown-host-xyz")
    assert unknown.supports_context_injection is False
    claude = capabilities_for_host("claude-code")
    assert claude.supports_context_injection is True
    assert "user_message" in claude.context_injection_events


def test_pack_deadline_aborts_before_retrieve(store, cfg, embedder):
    """Deadline already past → PackDeadlineExceeded at before_retrieve."""
    import time

    from twin.inject.context_pack import PackDeadlineExceeded, build_context_pack

    with pytest.raises(PackDeadlineExceeded) as exc:
        build_context_pack(
            store, cfg, embedder, "anything",
            target_domain="technical",
            deadline_monotonic=time.monotonic() - 1.0,
        )
    assert exc.value.stage == "before_retrieve"
