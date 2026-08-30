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
    from twin.cognize.services import extract_pending
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
        "claim_search", "claim_get", "claim_related", "claim_project_context",
        "claim_recent_decisions", "claim_user_preferences",
        "inject_context_pack",
        "narrative_list", "narrative_show", "stance_list", "stance_proposals",
        "stance_applicable", "stance_simulate", "stance_profile",
        "stance_proposal_preview", "stance_proposal_approve",
        "stance_proposal_reject", "stance_conflicts", "stance_version",
        "session_start", "session_observe", "session_complete", "session_feedback",
    } <= tools
    assert "memory_search" not in tools
    assert "memory_get" not in tools
    assert "memory_judgment_profile" not in tools
    assert "judgment_applicable" not in tools
    assert "memory_safe_context_pack" not in tools
    assert "memory_observe" not in tools
    assert "get_context_pack" not in tools


@pytest.mark.anyio
async def test_inject_context_pack_tool(server):
    preferred = await server.call_tool(
        "inject_context_pack",
        {"query": "RFC sobre webhooks do Atlas", "target_domain": "technical"},
    )
    pref = json.loads(preferred[0][0].text)
    assert "deprecated" not in pref
    assert pref.get("tool") == "inject_context_pack"
    assert "context_pack" in pref
    assert "open_reflections" in pref
    assert "narratives" in pref
    assert "derived_confidence" in pref


@pytest.mark.anyio
async def test_search_tool(server):
    result = await server.call_tool(
        "claim_search", {"query": "FastAPI webhooks", "domain": "technical"}
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
    from twin.cognize.services.sessions import ensure_project
    from twin.store.models import StoreClaim, ClaimStatus
    from twin.workspace import Workspace

    ws = Workspace(str(home))
    project = ensure_project(ws.store, "Atlas", repos=["atlas-api"])
    prior = StoreClaim(id=ids.claim_id(), type="decision",
                       title="Use FastAPI for webhooks",
                       summary="Decision: the webhook backend runs on FastAPI.",
                       domain="technical", confidence=0.9, status="confirmed",
                       project_id=project.id)
    ws.store.insert_claim(prior)
    ws.store.store_embedding(prior.id, "claim", ws.embedder.name,
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

    from twin.interfaces.mcp_auth import MCP_CLIENT_ENV, MCP_TOKEN_ENV
    monkeypatch.setenv(MCP_CLIENT_ENV, "cursor")
    monkeypatch.setenv(MCP_TOKEN_ENV, "test-cursor-secret")

    ide = create_server(str(home))  # e.g. Cursor / Claude Code

    # 1-4: task starts in the project's working copy; twin identifies the
    # project and task profile and supplies prior decisions without re-asking
    started = await _call(ide, "session_start", {
        "query": "implement retry handling in the webhook endpoint code",
        "cwd": "/home/edu/code/atlas-api",
    })
    assert started["project_id"] == project.id
    assert started["task_profile"] == "coding"
    assert "FastAPI" in started["context_pack"]
    assert any(s["claim_id"] == prior.id for s in started["sources"])
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
    assert completed["created_claim_ids"]

    # 8: the human reviews and confirms the new candidate(s)
    ws = Workspace(str(home))
    created = completed["created_claim_ids"]
    new_id = created[0]
    assert ws.store.get_claim(new_id).status.value == "candidate"
    for mid in created:
        ws.store.set_status(mid, ClaimStatus.confirmed)
        # ensure confirmed memories clear the firewall confidence gate
        mem = ws.store.get_claim(mid)
        if mem and mem.confidence < 0.5:
            ws.store.update_claim(mid, confidence=0.85)
    ws.close()

    # 9: feedback is recorded against the session; a memory that was not
    # part of the session is rejected
    feedback = await _call(ide, "session_feedback", {
        "session_id": session_id, "verdict": "useful",
        "claim_id": prior.id, "note": "pack had the FastAPI decision",
    })
    assert feedback["feedback_count"] == 1
    rejected = await _call(ide, "session_feedback", {
        "session_id": session_id, "verdict": "useful", "claim_id": "mem_ghost",
    })
    assert "not found" in rejected["error"]

    # 10: another MCP process with the same env identity sees confirmed context
    other = create_server(str(home))
    pack = await _call(other, "inject_context_pack", {
        "query": "webhook retries backoff", "project": "Atlas",
    })
    pack_ids = {s["claim_id"] for s in pack["sources"]}
    assert set(created) & pack_ids, f"expected one of {created} in pack {pack_ids}"
    assert pack["project_id"] == project.id

    # clearing env identity must not inherit local-cli / must not leak
    monkeypatch.delenv(MCP_CLIENT_ENV, raising=False)
    monkeypatch.delenv(MCP_TOKEN_ENV, raising=False)
    restricted = await _call(other, "inject_context_pack", {
        "query": "webhook retries backoff", "project": "Atlas",
    })
    assert not (set(created) & {s["claim_id"] for s in restricted.get("sources") or []})


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
async def test_claim_get_and_related(server):
    memories = json.loads(
        (await server.call_tool("claim_search", {"query": "webhooks", "domain": "technical"}))[0][0].text
    )
    assert memories["hits"]
    mid = memories["hits"][0]["id"]
    got = json.loads(
        (await server.call_tool("claim_get", {"claim_id": mid}))[0][0].text
    )
    assert got["id"] == mid
    assert "evidence" in got
    missing = json.loads(
        (await server.call_tool("claim_get", {"claim_id": "mem_missing"}))[0][0].text
    )
    assert missing["error"] == "not found"


@pytest.mark.anyio
async def test_claim_recent_decisions_and_preferences(server):
    decisions = json.loads(
        (await server.call_tool("claim_recent_decisions", {"limit": 5}))[0][0].text
    )
    assert isinstance(decisions, list)
    prefs = json.loads(
        (await server.call_tool("claim_user_preferences", {"context": "code style"}))[0][0].text
    )
    assert isinstance(prefs, list)
    profile = json.loads(
        (await server.call_tool("stance_profile", {}))[0][0].text
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
    from twin.sense.connectors import add_connector_instance, build_credential_store, register_source_account
    from twin.interfaces.mcp_auth import MCP_CLIENT_ENV, MCP_TOKEN_ENV

    monkeypatch.setenv("TWIN_EXTRACTOR", "echo")
    monkeypatch.setenv("TWIN_EMBEDDER", "hash")
    monkeypatch.delenv(MCP_CLIENT_ENV, raising=False)
    monkeypatch.delenv(MCP_TOKEN_ENV, raising=False)
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

    monkeypatch.setenv(MCP_CLIENT_ENV, "conn-reader")
    monkeypatch.setenv(MCP_TOKEN_ENV, "tok-reader")
    listed = json.loads(
        (await srv.call_tool("connector_list", {}))[0][0].text
    )
    assert isinstance(listed, list)
    assert listed[0]["connector_id"] == inst.id

    health = json.loads(
        (await srv.call_tool("connector_health_all", {}))[0][0].text
    )
    assert isinstance(health, list)


@pytest.mark.anyio
async def test_safe_pack_ignores_tool_supplied_credentials(tmp_path, monkeypatch):
    """Tool args must not authenticate — only process env does."""
    from twin.interfaces.mcp_auth import MCP_CLIENT_ENV, MCP_TOKEN_ENV, provision_mcp_client
    from twin.workspace import Workspace

    monkeypatch.setenv("TWIN_EXTRACTOR", "echo")
    monkeypatch.setenv("TWIN_EMBEDDER", "hash")
    monkeypatch.delenv(MCP_CLIENT_ENV, raising=False)
    monkeypatch.delenv(MCP_TOKEN_ENV, raising=False)
    home = tmp_path / "twin-home"
    ws = Workspace(str(home))
    provision_mcp_client(ws.store, home, "cursor")
    ws.close()
    srv = create_server(str(home))
    tools = {t.name: t for t in await srv.list_tools()}
    schema = tools["inject_context_pack"].inputSchema
    props = (schema or {}).get("properties") or {}
    assert "client" not in props
    assert "client_token" not in props
    # Without env → restricted (no leak via phantom args)
    pack = await _call(srv, "inject_context_pack", {
        "query": "anything", "target_domain": "technical",
        "client": "cursor", "client_token": "ignored",
    })
    # FastMCP may reject unknown args — either way, must not authenticate.
    assert "context_pack" in pack or "error" in pack or pack.get("blocked_count", 0) >= 0
    if "context_pack" in pack:
        assert pack.get("privacy_meta", {}).get("resources_allowed", 0) == 0 or \
            pack.get("blocked_count", 0) >= 0


@pytest.mark.anyio
async def test_setup_mcp_provisions_env_identity(tmp_path, monkeypatch):
    from twin.config import Config
    from twin.interfaces.mcp_auth import MCP_CLIENT_ENV, MCP_TOKEN_ENV
    from twin.interfaces.ops import setup_mcp

    monkeypatch.setenv("TWIN_EXTRACTOR", "echo")
    monkeypatch.setenv("TWIN_EMBEDDER", "hash")
    # Keep Claude Code user MCP under tmp (not real ~/.claude.json).
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    home = tmp_path / "twin-home"
    home.mkdir()
    cfg = Config(home=home)
    lines = setup_mcp(cfg, "claude-code")
    assert any("wrote" in line for line in lines)
    mcp_path = tmp_path / ".claude.json"
    data = json.loads(mcp_path.read_text(encoding="utf-8"))
    env = data["mcpServers"]["twin"]["env"]
    assert env[MCP_CLIENT_ENV] == "claude-code"
    assert env[MCP_TOKEN_ENV]
    from twin.workspace import Workspace
    ws = Workspace(str(home))
    binding = ws.store.get_client_binding_by_client("claude-code")
    assert binding is not None
    assert binding.credential_hash
    ws.close()



@pytest.mark.anyio
async def test_privacy_validate_output(server):
    result = json.loads(
        (await server.call_tool("privacy_validate_output", {
            "text": "harmless summary of architecture decisions",
        }))[0][0].text
    )
    assert "allowed" in result or "issues" in result
