"""v0.6 Phase 10 — Final Review (§93 completion criteria)."""

from __future__ import annotations

from twin import ids
from twin.clock import now_iso
from twin.cognition.context_pack import build_context_pack
from twin.connectors.completion import (
    CRITERIA,
    check_criterion,
    completion_matrix,
)
from twin.memory.lifecycle import supersede
from twin.memory.models import Evidence, MemoryItem, MemoryStatus
from twin.privacy.models import AccessRequest, PolicyEffect
from twin.privacy.yaml_io import bootstrap_policy_set
from twin.sensory.percept import Percept


def _mem(store, embedder, **kw):
    base = dict(
        id=ids.memory_id(), type="decision", title="t", summary="s",
        domain="work", confidence=0.9, status="confirmed",
        sensitivity="internal", persona="developer",
    )
    base.update(kw)
    mem = MemoryItem(**base)
    store.insert_memory(mem)
    store.store_embedding(
        mem.id, "memory", embedder.name,
        embedder.embed(f"{mem.title}\n{mem.summary}"),
    )
    return mem


def _ensure_work_principal(store, principal_id: str = "tool_work_cli"):
    from twin.privacy.identity import ensure_local_identity
    from twin.privacy.models import Principal, PrincipalType

    ensure_local_identity(store)
    existing = store.get_principal(principal_id)
    if existing:
        return existing
    vaults = ["vault_general", "vault_work"]
    domains = ["technical", "work"]
    caps = (
        ["read_context_pack"]
        + [f"read:domain:{d}" for d in domains]
        + [f"read:vault:{v}" for v in vaults]
    )
    p = Principal(
        id=principal_id,
        type=PrincipalType.tool,
        name=principal_id,
        capabilities=caps,
        allowed_personas=["developer", "employee"],
        allowed_purposes=["*"],
        allowed_audiences=["self", "local"],
        allowed_vaults=vaults,
    )
    store.insert_principal(p)
    return p


def test_completion_matrix_is_evidence_based():
    matrix = completion_matrix()
    assert matrix["phase"] == 10
    assert matrix["section"] == "93"
    assert matrix["count"] == 17
    assert len(CRITERIA) == 17
    assert matrix["ok"] is True
    assert matrix["failed"] == []
    assert matrix["partial"] == []
    for row in matrix["criteria"]:
        assert row["status"] in (
            "pass", "fail", "not_tested", "partial", "not_applicable",
        )
        if row["status"] == "pass":
            assert row["evidence"] or row["eval"]
    assert matrix["out_of_scope"]["section"] == "94"
    assert matrix["thesis"]["section"] == "95"
    assert check_criterion(17)["status"] == "pass"


def test_completion_matrix_demotes_pass_without_evidence(monkeypatch):
    from twin.connectors import completion as mod

    broken = [dict(c) for c in mod.CRITERIA]
    broken[0] = {
        **broken[0],
        "status": "pass",
        "evidence": None,
        "eval": None,
    }
    monkeypatch.setattr(mod, "CRITERIA", broken)
    matrix = mod.completion_matrix()
    assert matrix["criteria"][0]["status"] == "not_tested"
    assert matrix["ok"] is False


def test_meeting_revises_decision_via_supersede(store, embedder):
    """§93.9 — later meeting changes a decision; supersede is explicit.

    Connectors only capture evidence (candidates). Confirmation + supersede
    stay in Memory lifecycle — never auto from ingest (criterion 17).
    """
    pr_percept = Percept(
        id=ids.new_id("pct"),
        percept_type="pull_request",
        source_sensor="github",
        occurred_at="2026-07-10T10:00:00Z",
        ingested_at=now_iso(),
        content="Decision: ship Atlas Friday.",
        source_trust=0.85,
        source_scope="work",
        source_confidentiality="internal",
        source_metadata={"source_owner": "employer", "vault_id": "vault_work"},
    )
    pr_percept.seal()
    store.insert_percept(pr_percept)

    meeting_percept = Percept(
        id=ids.new_id("pct"),
        percept_type="meeting_transcript_chunk",
        source_sensor="fireflies",
        occurred_at="2026-07-11T15:00:00Z",
        ingested_at=now_iso(),
        content="We decided to postpone the Atlas ship to next sprint.",
        source_trust=0.80,
        source_scope="work",
        source_confidentiality="internal",
        source_metadata={"source_owner": "employer", "vault_id": "vault_work"},
    )
    meeting_percept.seal()
    store.insert_percept(meeting_percept)

    # Extraction would propose candidates — never confirmed Memory from connector.
    old = _mem(
        store, embedder,
        title="Ship Atlas Friday",
        summary="Decision: ship Atlas Friday.",
        status="candidate",
        confidence=0.75,
        payload={"source_owner": "employer", "vault_id": "vault_work",
                 "origin": "github_pr"},
    )
    store.insert_evidence(Evidence(
        id=ids.new_id("ev"), memory_id=old.id,
        quote="ship Atlas Friday",
        percept_id=pr_percept.id,
        artifact_id="github:pr:atlas#8",
        independence_group="lineage:github:acme/atlas#8",
    ))

    new = _mem(
        store, embedder,
        title="Postpone Atlas ship",
        summary="Postpone the Atlas ship to next sprint.",
        status="candidate",
        confidence=0.80,
        payload={"source_owner": "employer", "vault_id": "vault_work",
                 "origin": "meeting"},
    )
    store.insert_evidence(Evidence(
        id=ids.new_id("ev"), memory_id=new.id,
        quote="postpone the Atlas ship",
        percept_id=meeting_percept.id,
        artifact_id="fireflies:meeting:m1",
        independence_group="meeting:m1",
    ))

    assert store.get_memory(old.id).status == MemoryStatus.candidate
    assert store.get_memory(new.id).status == MemoryStatus.candidate

    # Review confirms the meeting decision, then supersedes the PR-era one.
    store.update_memory(new.id, status=MemoryStatus.confirmed.value)
    result = supersede(store, new.id, old.id)
    assert result.action == "supersede"
    reloaded_old = store.get_memory(old.id)
    assert reloaded_old.status == MemoryStatus.deprecated
    assert store.get_memory(new.id).status == MemoryStatus.confirmed
    rels = store.relations_for(new.id)
    assert any(r.predicate == "supersedes" and r.object_id == old.id for r in rels)


def test_professional_pack_includes_authorized_work_memory(store, cfg, embedder):
    """§93.11 — authorized professional context pack includes employer memory."""
    bootstrap_policy_set(store)
    _ensure_work_principal(store, "tool_work_cli")
    marker = "AUTHORIZED_EMPLOYER_ROADMAP_ATLAS_PHASE10"
    _mem(
        store, embedder,
        title="Atlas roadmap",
        summary=marker,
        domain="work",
        status="confirmed",
        payload={"source_owner": "employer", "vault_id": "vault_work"},
        entities=["Atlas"],
    )
    pack = build_context_pack(
        store, cfg, embedder, "Atlas roadmap",
        target_domain="work",
        access=AccessRequest(
            principal_id="tool_work_cli",
            persona="developer",
            purpose="coding",
            audience="self",
            tool_id="local-cli",
            requested_domains=["work"],
        ),
    )
    assert pack.privacy_decision_id
    assert marker in pack.context_pack


def test_personal_persona_still_denied_employer_pack(store, cfg, embedder):
    """§93.12 companion — personal persona must not see employer content."""
    bootstrap_policy_set(store)
    from twin.privacy.identity import ensure_local_identity
    ensure_local_identity(store)
    marker = "SECRET_EMPLOYER_SPRINT_BOARD_PHASE10"
    mem = _mem(
        store, embedder,
        title="sprint",
        summary=marker,
        domain="work",
        payload={"source_owner": "employer", "vault_id": "vault_work"},
    )
    from twin.privacy.engine import evaluate_access
    req = AccessRequest(
        principal_id="principal_local_cli",
        persona="individual",
        purpose="personal_planning",
        audience="self",
        tool_id="local-cli",
    )
    result = evaluate_access(store, req, [mem], persist=True)
    assert result["decision"].resource_decisions[0].effect == PolicyEffect.deny

    pack = build_context_pack(
        store, cfg, embedder, "sprint board",
        target_domain="work",
        access=AccessRequest(
            principal_id="principal_local_cli",
            persona="individual",
            purpose="personal_planning",
            audience="self",
            tool_id="chatgpt-cloud",
            requested_domains=["work"],
        ),
    )
    assert marker not in pack.context_pack


def test_message_evidence_removed_corroborated_memory_kept(store, embedder):
    """§93.13 — drop one artifact's evidence; multi-source memory survives."""
    from twin.privacy.deletion import execute_deletion, preview_deletion

    mem = _mem(
        store, embedder,
        title="multi-src decision",
        summary="supported by PR discussion and Slack thread",
        domain="technical",
    )
    for pid, aid, quote in (
        ("per_pr", "art_pr", "from PR"),
        ("per_slack", "art_slack", "from Slack"),
    ):
        p = Percept(
            id=pid, percept_type="message", source_sensor="test",
            occurred_at=now_iso(), ingested_at=now_iso(),
            content=quote, source_trust=0.6, source_scope="work",
            source_confidentiality="internal",
        )
        p.seal()
        store.insert_percept(p)
        store.insert_evidence(Evidence(
            id=ids.new_id("ev"), memory_id=mem.id, quote=quote,
            artifact_id=aid, percept_id=pid,
            independence_group=aid,
        ))

    req = preview_deletion(store, {"artifact_id": "art_slack"})
    assert mem.id in req.manifest["memories_recalculate"]
    assert mem.id not in req.manifest["memories_delete"]
    out = execute_deletion(
        store, req.id, confirm=True, preview_token=req.preview_token,
    )
    assert out.status.value in ("completed", "completed_with_residuals")
    still = store.get_memory(mem.id)
    assert still is not None and not still.deleted_at
