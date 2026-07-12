from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from twin.interfaces.api import create_app

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_EXTRACTOR", "heuristic")
    monkeypatch.setenv("TWIN_EMBEDDER", "hash")
    app = create_app(home=str(tmp_path / "twin-home"))
    return TestClient(app)


def test_full_flow_over_api(client):
    # ingest (sensory layer)
    r = client.post("/api/ingest", json={"paths": [str(EXAMPLES)]})
    assert r.status_code == 200
    assert len(r.json()["ingested"]) == 3

    # percepts are visible
    percepts = client.get("/api/percepts").json()
    assert {p["percept_type"] for p in percepts} == {"document", "meeting_transcript", "meeting"}

    # extract
    r = client.post("/api/extract")
    assert r.status_code == 200
    inserted = [mid for rep in r.json() for mid in rep["inserted"]]
    assert inserted

    # review queue lists candidates
    r = client.get("/api/memories", params={"status": "candidate"})
    memories = r.json()
    assert memories

    # approve one, fixing its domain
    mem_id = memories[0]["id"]
    r = client.post(f"/api/memories/{mem_id}/review",
                    params={"action": "approve", "domain": "technical"})
    assert r.json()["status"] == "confirmed"
    assert r.json()["domain"] == "technical"

    # reject another
    mem_id2 = memories[1]["id"]
    r = client.post(f"/api/memories/{mem_id2}/review", params={"action": "reject"})
    assert r.json()["status"] == "rejected"

    # search
    r = client.get("/api/search", params={"q": "FastAPI webhooks", "domain": "technical"})
    assert r.status_code == 200
    assert "hits" in r.json()

    # context pack
    r = client.post("/api/context_pack", json={"query": "RFC webhooks Atlas"})
    assert r.status_code == 200
    assert "context_pack" in r.json()

    # observer
    r = client.post("/api/observer", json={"current_text": "arquitetura dos webhooks"})
    assert r.status_code == 200
    assert r.json()["inferred_domain"] == "technical"

    # judgment + export
    assert client.get("/api/judgment").json()["principles"]
    export = client.get("/api/export").json()
    assert export["memories"] and export["entities"]

    # UI renders
    assert "twin" in client.get("/").text
    assert client.get("/all").status_code == 200


def test_projects_over_api(client):
    r = client.post("/api/projects", json={"name": "Atlas", "repos": ["atlas-api"],
                                           "aliases": ["atlas"]})
    assert r.status_code == 200
    project = r.json()
    assert project["id"].startswith("proj_")

    assert [p["id"] for p in client.get("/api/projects").json()] == [project["id"]]
    assert client.get(f"/api/projects/{project['id']}").json()["name"] == "Atlas"
    assert client.get("/api/projects/atlas").json()["id"] == project["id"]  # alias
    assert client.get("/api/projects/nope").status_code == 404

    # idempotent by name
    again = client.post("/api/projects", json={"name": "Atlas"}).json()
    assert again["id"] == project["id"]


def test_session_lifecycle_over_api(client):
    project = client.post("/api/projects", json={"name": "Atlas",
                                                 "repos": ["atlas-api"]}).json()

    r = client.post("/api/sessions", json={
        "query": "implement the webhook retry endpoint",
        "client": "test", "cwd": "/home/edu/atlas-api",
    })
    assert r.status_code == 200
    started = r.json()
    session_id = started["session"]["id"]
    assert started["session"]["project_id"] == project["id"]
    assert started["session"]["task_profile"] == "coding"
    assert started["observer_mode"] in ("fast", "deep")
    assert "context_pack" in started["context_pack"]

    r = client.post(f"/api/sessions/{session_id}/observe",
                    json={"kind": "commit", "ref": "abc123", "note": "retry logic"})
    assert len(r.json()["artifacts"]) == 1

    r = client.post(f"/api/sessions/{session_id}/complete",
                    json={"summary": "We decided to use exponential backoff for retries."})
    assert r.json()["status"] == "completed"
    assert r.json()["created_memory_ids"]

    r = client.post(f"/api/sessions/{session_id}/feedback",
                    json={"verdict": "useful", "note": "had the right decisions"})
    assert len(r.json()["feedback"]) == 1
    assert client.post(f"/api/sessions/{session_id}/feedback",
                       json={"verdict": "amazing"}).status_code == 400

    # listings and filters
    assert client.get(f"/api/sessions/{session_id}").json()["status"] == "completed"
    assert len(client.get("/api/sessions", params={"status": "completed"}).json()) == 1
    assert client.get("/api/sessions/ses_missing").status_code == 404
    # double-complete is rejected
    assert client.post(f"/api/sessions/{session_id}/complete",
                       json={}).status_code == 400

    # session activity shows up in metrics
    metrics = client.get("/api/metrics").json()
    assert metrics["sessions"]["total"] == 1
    assert metrics["product"]["feedback_by_verdict"] == {"useful": 1}


def test_context_pack_accepts_profile_and_project(client):
    project = client.post("/api/projects", json={"name": "Atlas"}).json()
    r = client.post("/api/context_pack", json={
        "query": "design the queue architecture",
        "task_profile": "architecture", "project": "Atlas",
    })
    assert r.status_code == 200
    assert r.json()["task_profile"] == "architecture"
    assert r.json()["project_id"] == project["id"]
    assert client.post("/api/context_pack", json={
        "query": "x", "project": "missing-project",
    }).status_code == 404


def test_review_ui_form_roundtrip(client):
    client.post("/api/ingest", json={"paths": [str(EXAMPLES / "docs")]})
    client.post("/api/extract")
    memories = client.get("/api/memories", params={"status": "candidate"}).json()
    mem_id = memories[0]["id"]
    r = client.post(f"/review/{mem_id}",
                    data={"action": "approve", "domain": "work", "sensitivity": "internal"},
                    follow_redirects=False)
    assert r.status_code == 303
    updated = client.get(f"/api/memories/{mem_id}").json()
    assert updated["status"] == "confirmed"
    assert updated["domain"] == "work"
