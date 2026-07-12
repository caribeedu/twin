import json
from pathlib import Path

import pytest

from twin.interfaces.mcp_server import create_server

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_EXTRACTOR", "heuristic")
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
    """The complete v0.2 loop over MCP: session opens with project-aware
    context, work happens, completion turns it into reviewable candidates,
    review confirms, feedback lands, and a second MCP client sees the new
    context."""
    monkeypatch.setenv("TWIN_EXTRACTOR", "heuristic")
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
    ws.close()

    ide = create_server(str(home))  # e.g. Cursor / Claude Code

    # 1-4: task starts in the project's working copy; twin identifies the
    # project and task profile and supplies prior decisions without re-asking
    started = await _call(ide, "session_start", {
        "query": "implement retry handling in the webhook endpoint code",
        "client": "cursor", "cwd": "/home/edu/code/atlas-api",
    })
    assert started["project_id"] == project.id
    assert started["task_profile"] == "coding"
    assert "FastAPI" in started["context_pack"]
    assert any(s["memory_id"] == prior.id for s in started["sources"])
    session_id = started["session_id"]

    # 5: work happens — artifacts observed along the way
    observed = await _call(ide, "session_observe", {
        "session_id": session_id, "kind": "commit", "ref": "abc123",
        "note": "added retry with backoff",
    })
    assert observed["artifacts"] == 1

    # 6-7: completion turns the session into percepts → candidate memories
    completed = await _call(ide, "session_complete", {
        "session_id": session_id,
        "summary": "We decided to use exponential backoff for webhook retries.",
    })
    assert completed["status"] == "completed"
    assert completed["created_memory_ids"]

    # 8: the human reviews and confirms the new candidate
    ws = Workspace(str(home))
    new_id = completed["created_memory_ids"][0]
    assert ws.store.get_memory(new_id).status.value == "candidate"
    ws.store.set_status(new_id, MemoryStatus.confirmed)
    ws.close()

    # 9: feedback is recorded against the session
    feedback = await _call(ide, "session_feedback", {
        "session_id": session_id, "verdict": "useful",
        "note": "pack had the FastAPI decision",
    })
    assert feedback["feedback_count"] == 1

    # 10: another MCP client sees the confirmed context from this session
    other = create_server(str(home))
    pack = await _call(other, "memory_safe_context_pack", {
        "query": "webhook retries backoff", "project": "Atlas",
    })
    assert new_id in {s["memory_id"] for s in pack["sources"]}
    assert pack["project_id"] == project.id


@pytest.fixture
def anyio_backend():
    return "asyncio"
