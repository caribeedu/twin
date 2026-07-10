import json
from pathlib import Path

import pytest

from twin.mcp_server import create_server

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_EXTRACTOR", "heuristic")
    home = tmp_path / "twin-home"
    srv = create_server(str(home))
    # populate through the same workspace path
    from twin.extract import extract_pending
    from twin.ingest import ingest_paths
    from twin.workspace import Workspace

    ws = Workspace(str(home))
    ingest_paths(ws.db, [EXAMPLES])
    extract_pending(ws.db, ws.cfg, ws.embedder)
    ws.close()
    return srv


@pytest.mark.anyio
async def test_tools_are_registered(server):
    tools = {t.name for t in await server.list_tools()}
    assert {
        "memory_search", "memory_get", "memory_related", "memory_project_context",
        "memory_recent_decisions", "memory_user_preferences",
        "memory_judgment_profile", "memory_safe_context_pack", "memory_observe",
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


@pytest.fixture
def anyio_backend():
    return "asyncio"
