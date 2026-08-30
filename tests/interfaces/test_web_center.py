"""Web Command Center entity REST + shell smoke."""

from __future__ import annotations

from fastapi.testclient import TestClient

from twin.cognize.models import (
    EvidenceAnchor,
    Interpretation,
    InterpretationStatus,
    Narrative,
    NarrativeStatus,
    Reflection,
    ReflectionStatus,
    Relation,
    RelationAssertedBy,
    RelationType,
    Situation,
    Trace,
)
from twin.interfaces.api import create_app
from twin.workspace import Workspace


def test_center_shell_has_no_memories_nav(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_EMBEDDER", "hash")
    monkeypatch.setenv("TWIN_EXTRACTOR", "echo")
    client = TestClient(create_app(str(tmp_path / "home")))
    html = client.get("/").text
    assert "Command Center" in html
    assert 'data-nav="explore"' in html
    assert 'data-nav="cognize"' in html
    assert 'data-nav="connectors"' in html
    assert 'data-nav="inject"' in html
    assert 'data-nav="ops"' in html
    assert 'data-nav="sense"' not in html
    assert "Memories" not in html
    assert 'data-nav="memories"' not in html


def test_center_connectors_list(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_EMBEDDER", "hash")
    monkeypatch.setenv("TWIN_EXTRACTOR", "echo")
    client = TestClient(create_app(str(tmp_path / "home")))
    r = client.get("/api/center/connectors")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_entity_list_show_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_EMBEDDER", "hash")
    monkeypatch.setenv("TWIN_EXTRACTOR", "echo")
    home = tmp_path / "home"
    ws = Workspace(str(home))
    store = ws.store
    vault = "default"

    sit = Situation(vault_id=vault, summary="Launch thread")
    store.upsert_situation(sit)
    ref = Reflection(
        vault_id=vault,
        text="Is Feature A still blocking launch?",
        status=ReflectionStatus.open,
    )
    store.upsert_reflection(ref)
    inter = Interpretation(
        vault_id=vault,
        explanation="Feature A remains the blocker until PR merges.",
        status=InterpretationStatus.competing,
    )
    store.upsert_interpretation(inter)
    nar = Narrative(
        vault_id=vault,
        account="Feature A blocked launch until PR #15 merged.",
        status=NarrativeStatus.committed,
        evidence_ids=["ev1"],
        committed_by="tester",
    )
    store.upsert_narrative(nar)
    rel = Relation(
        vault_id=vault,
        type=RelationType.supports,
        from_id=inter.id,
        to_id=nar.id,
        asserted_by=RelationAssertedBy.test,
    )
    store.upsert_relation(rel)
    ev = EvidenceAnchor(
        vault_id=vault,
        percept_id="pct_test",
        source_id="src1",
        target_kind="narrative",
        target_id=nar.id,
        quote="PR #15 merged",
    )
    store.upsert_evidence_anchor(ev)
    tr = Trace(vault_id=vault, event_kind="pack_serve", resource_id=nar.id)
    store.append_trace(tr)
    ws.close()

    client = TestClient(create_app(str(home)))

    assert client.get("/api/center/summary").status_code == 200
    assert client.get("/api/situations").json()
    assert client.get(f"/api/situations/{sit.id}").status_code == 200
    assert client.get("/api/reflections?status=all").json()
    assert client.get(f"/api/reflections/{ref.id}").status_code == 200
    assert client.get("/api/interpretations?status=all").json()
    assert client.get(f"/api/interpretations/{inter.id}").status_code == 200
    assert client.get("/api/relations").json()
    assert client.get(f"/api/relations/{rel.id}").status_code == 200
    assert client.get("/api/evidence").json()
    assert client.get(f"/api/evidence/{ev.id}").status_code == 200
    assert client.get("/api/traces").json()
    assert client.get(f"/api/traces/{tr.id}").status_code == 200
    assert client.get("/api/stances").status_code == 200
    assert client.get("/api/stances/proposals").status_code == 200
    assert client.get("/api/runtime/jobs").status_code == 200
    assert client.get("/api/narratives").status_code == 200
