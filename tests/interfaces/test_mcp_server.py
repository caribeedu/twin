import json
from pathlib import Path

from tests.paths import EXAMPLES

import pytest

from twin.interfaces.mcp_server import create_server

@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_EXTRACTOR", "echo")
    monkeypatch.setenv("TWIN_EMBEDDER", "hash")
    home = tmp_path / "twin-home"
    srv = create_server(str(home))
    # populate through the same workspace path
    from twin.cognition import extract_pending
    from twin.workspace import Workspace

    ws = Workspace(str(home))
    ws.ingest([EXAMPLES])
    extract_pending(ws.store, ws.cfg, ws.embedder)
    ws.close()
    return srv


@pytest.mark.anyio
async def test_tools_are_registered(server):
    tools = {t.name for t in await server.list_tools()}
    assert {
        "memory_search", "memory_get", "memory_related", "memory_project_context",
        "memory_recent_decisions", "memory_user_preferences",
        "memory_judgment_profile", "memory_safe_context_pack", "memory_observe",
        "judgment_applicable", "judgment_simulate", "judgment_proposals",
        "judgment_proposal_preview", "judgment_proposal_approve",
        "judgment_proposal_reject", "judgment_conflicts", "judgment_version",
        "session_start", "session_observe", "session_complete", "session_feedback",
    } <= tools


@pytest.mark.anyio
async def test_safe_context_pack_tool(server):
    result = await server.call_tool(
        "memory_safe_context_pack",
        {"query": "RFC sobre webhooks do Atlas", "target_domain": "technical"},
    )
    payload = json.loads(result[0][0].text)
    assert "context_pack" in payload
    assert "blocked" in payload


@pytest.mark.anyio
async def test_search_tool(server):
    result = await server.call_tool(
        "memory_search", {"query": "FastAPI webhooks", "domain": "technical"}
    )
    payload = json.loads(result[0][0].text)
    assert "hits" in payload


async def _call(server, tool, args):
    result = await server.call_tool(tool, args)
    return json.loads(result[0][0].text)


@pytest.mark.anyio
async def test_operational_workflow_end_to_end(tmp_path, monkeypatch):
    """The complete MCP loop: session opens with project-aware
    context, work happens, completion turns it into reviewable candidates,
    review confirms, feedback lands, and a second MCP client sees the new
    context."""
    monkeypatch.setenv("TWIN_EXTRACTOR", "echo")
    monkeypatch.setenv("TWIN_EMBEDDER", "hash")
    home = tmp_path / "twin-home"

    # existing state: a known project and one confirmed prior decision
    from twin import ids
    from twin.cognition.sessions import ensure_project
    from twin.memory.models import MemoryItem, MemoryStatus
    from twin.workspace import Workspace

    ws = Workspace(str(home))
    project = ensure_project(ws.store, "Atlas", repos=["atlas-api"])
    prior = MemoryItem(id=ids.memory_id(), type="decision",
                       title="Use FastAPI for webhooks",
                       summary="Decision: the webhook backend runs on FastAPI.",
                       domain="technical", confidence=0.9, status="confirmed",
                       project_id=project.id)
    ws.store.insert_memory(prior)
    ws.store.store_embedding(prior.id, "memory", ws.embedder.name,
                             ws.embedder.embed(f"{prior.title}\n{prior.summary}"))
    # Authenticated Cursor binding required — tool name alone is not enough
    from twin.privacy.identity import ensure_local_identity, register_client_binding
    from twin.privacy.models import Principal, PrincipalType
    from twin.privacy.yaml_io import bootstrap_policy_set
    bootstrap_policy_set(ws.store)
    ensure_local_identity(ws.store)
    ws.store.insert_principal(Principal(
        id="principal_cursor", type=PrincipalType.tool, name="cursor",
        capabilities=["read_context_pack", "read:domain:technical", "read:vault:vault_general"],
        allowed_personas=["individual", "developer"],
        allowed_vaults=["vault_general", "vault_work"],
    ))
    register_client_binding(
        ws.store, client_id="cursor", tool_id="cursor",
        principal_id="principal_cursor",
        credential="test-cursor-secret",
        capabilities=["read_context_pack", "read:domain:technical", "read:vault:vault_general"],
        allowed_personas=["individual", "developer"],
        allowed_vaults=["vault_general", "vault_work"],
    )
    ws.close()

    ide = create_server(str(home))  # e.g. Cursor / Claude Code

    # 1-4: task starts in the project's working copy; twin identifies the
    # project and task profile and supplies prior decisions without re-asking
    started = await _call(ide, "session_start", {
        "query": "implement retry handling in the webhook endpoint code",
        "client": "cursor", "client_token": "test-cursor-secret",
        "cwd": "/home/edu/code/atlas-api",
    })
    assert started["project_id"] == project.id
    assert started["task_profile"] == "coding"
    assert "FastAPI" in started["context_pack"]
    assert any(s["memory_id"] == prior.id for s in started["sources"])
    session_id = started["session_id"]

    # explicit-but-unknown project is an error, never silently re-inferred
    bad = await _call(ide, "session_start", {
        "query": "implement retry handling code", "project": "payments",
    })
    assert "not found" in bad["error"]

    # an unclassifiable task supplies nothing and asks for the domain
    vague = await _call(ide, "session_start", {"query": "resolve aquilo de ontem"})
    assert vague["needs_domain_confirmation"] is True
    assert vague["sources"] == []

    # 5: work happens — artifacts observed along the way
    observed = await _call(ide, "session_observe", {
        "session_id": session_id, "kind": "commit", "ref": "abc123",
        "note": "added retry with backoff",
    })
    assert observed["artifacts"] == 1

    # 6-7: completion turns the session into percepts → candidate memories
    # (the summary is the assistant's own account → moderate trust)
    completed = await _call(ide, "session_complete", {
        "session_id": session_id,
        "summary": "We decided to use exponential backoff for webhook retries.",
    })
    assert completed["status"] == "completed"
    assert completed["consolidation_status"] == "completed"
    assert completed["created_memory_ids"]

    # 8: the human reviews and confirms the new candidate(s)
    ws = Workspace(str(home))
    created = completed["created_memory_ids"]
    new_id = created[0]
    assert ws.store.get_memory(new_id).status.value == "candidate"
    for mid in created:
        ws.store.set_status(mid, MemoryStatus.confirmed)
        # ensure confirmed memories clear the firewall confidence gate
        mem = ws.store.get_memory(mid)
        if mem and mem.confidence < 0.5:
            ws.store.update_memory(mid, confidence=0.85)
    ws.close()

    # 9: feedback is recorded against the session; a memory that was not
    # part of the session is rejected
    feedback = await _call(ide, "session_feedback", {
        "session_id": session_id, "verdict": "useful",
        "memory_id": prior.id, "note": "pack had the FastAPI decision",
    })
    assert feedback["feedback_count"] == 1
    rejected = await _call(ide, "session_feedback", {
        "session_id": session_id, "verdict": "useful", "memory_id": "mem_ghost",
    })
    assert "not found" in rejected["error"]

    # 10: another MCP client sees the confirmed context from this session
    # (must have registered client binding — name alone is not enough)
    from twin.privacy.identity import ensure_local_identity, register_client_binding
    from twin.privacy.models import Principal, PrincipalType
    from twin.privacy.yaml_io import bootstrap_policy_set
    from twin.workspace import Workspace as WS
    ws_bind = WS(str(home))
    bootstrap_policy_set(ws_bind.store)
    ensure_local_identity(ws_bind.store)
    if ws_bind.store.get_principal("principal_cursor") is None:
        ws_bind.store.insert_principal(Principal(
            id="principal_cursor", type=PrincipalType.tool, name="cursor",
            capabilities=["read_context_pack", "read:domain:technical", "read:vault:vault_general"],
            allowed_personas=["individual", "developer"],
            allowed_vaults=["vault_general", "vault_work"],
        ))
    if ws_bind.store.get_client_binding_by_client("cursor") is None:
        register_client_binding(
            ws_bind.store, client_id="cursor", tool_id="cursor",
            principal_id="principal_cursor",
            credential="test-cursor-secret",
            capabilities=["read_context_pack", "read:domain:technical", "read:vault:vault_general"],
            allowed_personas=["individual", "developer"],
            allowed_vaults=["vault_general", "vault_work"],
        )
    ws_bind.close()

    other = create_server(str(home))
    pack = await _call(other, "memory_safe_context_pack", {
        "query": "webhook retries backoff", "project": "Atlas",
        "client": "cursor", "client_token": "test-cursor-secret",
    })
    pack_ids = {s["memory_id"] for s in pack["sources"]}
    assert set(created) & pack_ids, f"expected one of {created} in pack {pack_ids}"
    assert pack["project_id"] == project.id

    # omitting client identity must not inherit local-cli / must not leak
    restricted = await _call(other, "memory_safe_context_pack", {
        "query": "webhook retries backoff", "project": "Atlas",
    })
    assert not (set(created) & {s["memory_id"] for s in restricted.get("sources") or []})


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _bootstrap_connector_reader(store):
    from twin.privacy.identity import ensure_local_identity, register_client_binding
    from twin.privacy.models import Principal, PrincipalType
    from twin.privacy.yaml_io import bootstrap_policy_set

    bootstrap_policy_set(store)
    ensure_local_identity(store)
    store.insert_principal(Principal(
        id="principal_conn_reader", type=PrincipalType.tool, name="reader",
        capabilities=["connector:read", "read_context_pack"],
        allowed_personas=["individual", "developer"],
        allowed_vaults=["vault_general", "vault_personal"],
    ))
    register_client_binding(
        store, client_id="conn-reader", tool_id="conn-reader",
        principal_id="principal_conn_reader", credential="tok-reader",
        capabilities=["connector:read"],
        allowed_personas=["individual", "developer"],
        allowed_vaults=["vault_general", "vault_personal"],
    )


@pytest.mark.anyio
async def test_memory_get_and_related(server):
    memories = json.loads(
        (await server.call_tool("memory_search", {"query": "webhooks", "domain": "technical"}))[0][0].text
    )
    assert memories["hits"]
    mid = memories["hits"][0]["id"]
    got = json.loads(
        (await server.call_tool("memory_get", {"memory_id": mid}))[0][0].text
    )
    assert got["id"] == mid
    assert "evidence" in got
    missing = json.loads(
        (await server.call_tool("memory_get", {"memory_id": "mem_missing"}))[0][0].text
    )
    assert missing["error"] == "not found"


@pytest.mark.anyio
async def test_memory_recent_decisions_and_preferences(server):
    decisions = json.loads(
        (await server.call_tool("memory_recent_decisions", {"limit": 5}))[0][0].text
    )
    assert isinstance(decisions, list)
    prefs = json.loads(
        (await server.call_tool("memory_user_preferences", {"context": "code style"}))[0][0].text
    )
    assert isinstance(prefs, list)
    profile = json.loads(
        (await server.call_tool("memory_judgment_profile", {}))[0][0].text
    )
    assert "principles" in profile or "items" in profile


@pytest.mark.anyio
async def test_capabilities_and_health(server):
    caps = json.loads((await server.call_tool("capabilities", {}))[0][0].text)
    assert "session_start" in caps["tools"]
    health = json.loads((await server.call_tool("health", {}))[0][0].text)
    assert health.get("ok") is True


@pytest.mark.anyio
async def test_session_tools_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_EXTRACTOR", "echo")
    monkeypatch.setenv("TWIN_EMBEDDER", "hash")
    home = tmp_path / "twin-home"
    srv = create_server(str(home))

    started = await _call(srv, "session_start", {
        "query": "implement webhook retries", "domain": "technical",
    })
    sid = started["session_id"]
    active = await _call(srv, "get_active_session", {"session_id": sid})
    assert active["id"] == sid

    observed = await _call(srv, "session_observe", {
        "session_id": sid, "kind": "note", "note": "sketched backoff",
    })
    assert observed["artifacts"] == 1

    attention = await _call(srv, "get_attention", {"session_id": sid})
    assert attention["session_id"] == sid

    completed = await _call(srv, "session_complete", {
        "session_id": sid, "summary": "Decided on exponential backoff.",
    })
    assert completed["status"] == "completed"


@pytest.mark.anyio
async def test_connector_list_dry_run(tmp_path, monkeypatch):
    from twin.connectors import add_connector_instance, build_credential_store, register_source_account

    monkeypatch.setenv("TWIN_EXTRACTOR", "echo")
    monkeypatch.setenv("TWIN_EMBEDDER", "hash")
    home = tmp_path / "twin-home"
    from twin.workspace import Workspace

    ws = Workspace(str(home))
    _bootstrap_connector_reader(ws.store)
    creds = build_credential_store(home)
    acc = register_source_account(
        ws.store, connector_type="fake", source_owner="personal",
        owner_principal_id="principal_conn_reader",
    )
    inst = add_connector_instance(ws.store, creds, account_id=acc.id, secret="tok")
    ws.close()

    srv = create_server(str(home))
    denied = json.loads(
        (await srv.call_tool("connector_list", {}))[0][0].text
    )
    assert denied.get("error") == "not_authorized"

    listed = json.loads(
        (await srv.call_tool("connector_list", {
            "client": "conn-reader", "client_token": "tok-reader",
        }))[0][0].text
    )
    assert isinstance(listed, list)
    assert listed[0]["connector_id"] == inst.id

    health = json.loads(
        (await srv.call_tool("connector_health_all", {
            "client": "conn-reader", "client_token": "tok-reader",
        }))[0][0].text
    )
    assert isinstance(health, list)


@pytest.mark.anyio
async def test_privacy_validate_output(server):
    result = json.loads(
        (await server.call_tool("privacy_validate_output", {
            "text": "harmless summary of architecture decisions",
        }))[0][0].text
    )
    assert "allowed" in result or "issues" in result
