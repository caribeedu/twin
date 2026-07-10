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
