"""extract --auto-approve confirms newly inserted candidates."""

from __future__ import annotations

from tests.paths import EXAMPLES

from fastapi.testclient import TestClient

from twin.interfaces.api import create_app


def test_extract_auto_approve_confirms_candidates(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_EXTRACTOR", "echo")
    monkeypatch.setenv("TWIN_EMBEDDER", "hash")
    client = TestClient(create_app(home=str(tmp_path / "twin-home")))
    client.post("/api/ingest", json={"paths": [str(EXAMPLES / "docs")]})
    r = client.post("/api/extract", params={"auto_approve": True})
    assert r.status_code == 200
    body = r.json()
    inserted = [mid for rep in body for mid in rep["inserted"]]
    approved = [mid for rep in body for mid in rep.get("auto_approved", [])]
    assert inserted
    assert set(approved) == set(inserted)
    assert client.get("/api/memories", params={"status": "candidate"}).json() == []
    confirmed = client.get("/api/memories", params={"status": "confirmed"}).json()
    assert {m["id"] for m in confirmed} >= set(inserted)
