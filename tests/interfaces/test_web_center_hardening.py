"""v2.4.1 Web Center contract + exit-criteria tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from twin.cognize.models import (
    EpistemicState,
    EpistemicStatus,
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
)
from twin import ids
from twin.clock import now_iso
from twin.interfaces.api import create_app
from twin.judgment.models import JudgmentKind, JudgmentProposal, ProposalAction, ProposalStatus
from twin.workspace import Workspace


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_EMBEDDER", "hash")
    monkeypatch.setenv("TWIN_EXTRACTOR", "echo")
    return TestClient(create_app(str(tmp_path / "home")))


def test_empty_entity_lists_are_arrays(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    for path in (
        "/api/situations",
        "/api/reflections?status=all",
        "/api/interpretations?status=all",
        "/api/relations",
        "/api/evidence",
        "/api/traces",
        "/api/stances",
        "/api/stances/proposals",
        "/api/runtime/jobs",
        "/api/narratives",
    ):
        r = client.get(path)
        assert r.status_code == 200, path
        assert isinstance(r.json(), list), path


def test_commit_requires_preview_token(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    missing = client.post("/api/narratives/commit", json={
        "account": "A claim",
        "evidence_ids": ["ev_x"],
        "actor": "tester",
        "domain": "technical",
    })
    assert missing.status_code == 400
    assert "preview_token" in missing.json()["detail"].lower()


def test_narrative_show_enrichment_and_stale_badge(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_EMBEDDER", "hash")
    monkeypatch.setenv("TWIN_EXTRACTOR", "echo")
    home = tmp_path / "home"
    ws = Workspace(str(home))
    vault = "default"
    eps = EpistemicState(status=EpistemicStatus.stale, stale_reason="new percept landed")
    ws.store.upsert_epistemic_state(eps)
    nar = Narrative(
        vault_id=vault,
        account="Feature A blocked launch.",
        status=NarrativeStatus.committed,
        epistemic_state_id=eps.id,
        evidence_ids=["ev_a"],
        domain="technical",
        grain="episode",
        committed_by="tester",
    )
    ws.store.upsert_narrative(nar)
    ref = Reflection(
        vault_id=vault,
        text="Is Feature A still blocking?",
        status=ReflectionStatus.open,
        metadata={"domain": "technical"},
    )
    ws.store.upsert_reflection(ref)
    rel = Relation(
        vault_id=vault,
        type=RelationType.supports,
        from_id="ev_a",
        to_id=nar.id,
        asserted_by=RelationAssertedBy.test,
    )
    ws.store.upsert_relation(rel)
    ws.store.upsert_evidence_anchor(EvidenceAnchor(
        id="ev_a",
        vault_id=vault,
        percept_id="pct_1",
        quote="launch blocked",
        target_kind="narrative",
        target_id=nar.id,
        dissent=True,
    ))
    ws.close()

    client = TestClient(create_app(str(home)))
    show = client.get(f"/api/narratives/{nar.id}").json()
    assert show["epistemic"]["status"] == "stale"
    assert show["epistemic"]["stale_reason"]
    assert show["grain"] == "episode"
    assert "derived_confidence" in show
    assert show["derived_confidence"]["derived"] is True
    assert show["derived_confidence"]["label"] == "uncertain"
    assert show["relations"]
    assert show["evidence"]
    assert any(e.get("dissent") for e in show["evidence"])
    assert any(r["id"] == ref.id for r in show["open_reflections"])

    html = client.get("/").text
    assert 'data-nav="explore"' in html
    assert 'data-nav="memories"' not in html


def test_stance_approve_rejects_bad_token(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_EMBEDDER", "hash")
    monkeypatch.setenv("TWIN_EXTRACTOR", "echo")
    home = tmp_path / "home"
    ws = Workspace(str(home))
    prop = JudgmentProposal(
        id=ids.judgment_proposal_id(),
        action=ProposalAction.create,
        status=ProposalStatus.pending,
        proposed_item={
            "kind": JudgmentKind.preference.value,
            "statement": "Prefer explicit review gates",
            "domain": "technical",
        },
        reason="test",
        created_at=now_iso(),
    )
    ws.store.insert_judgment_proposal(prop)
    ws.close()

    client = TestClient(create_app(str(home)))
    bad = client.post(
        f"/api/stances/proposals/{prop.id}/approve",
        json={"preview_token": ""},
    )
    assert bad.status_code == 400

    missing = client.post(
        f"/api/stances/proposals/{prop.id}/approve",
        json={},
    )
    assert missing.status_code == 422

    mismatch = client.post(
        f"/api/stances/proposals/{prop.id}/approve",
        json={"preview_token": "not-a-real-token"},
    )
    assert mismatch.status_code == 400

    preview = client.post(f"/api/stances/proposals/{prop.id}/preview", json={})
    assert preview.status_code == 200
    token = preview.json()["preview_token"]
    ok = client.post(
        f"/api/stances/proposals/{prop.id}/approve",
        json={"preview_token": token},
    )
    assert ok.status_code == 200


def test_situation_list_show_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_EMBEDDER", "hash")
    monkeypatch.setenv("TWIN_EXTRACTOR", "echo")
    home = tmp_path / "home"
    ws = Workspace(str(home))
    sit = Situation(vault_id="default", summary="Arc", percept_ids=["p1", "p2"])
    ws.store.upsert_situation(sit)
    inter = Interpretation(
        vault_id="default",
        explanation="Candidate",
        status=InterpretationStatus.competing,
    )
    ws.store.upsert_interpretation(inter)
    ws.close()
    client = TestClient(create_app(str(home)))
    listed = client.get("/api/situations").json()
    assert listed and "percept_ids" in listed[0]
    show = client.get(f"/api/situations/{sit.id}").json()
    assert show["percept_ids"] == ["p1", "p2"]
    assert client.get("/api/interpretations").json()
