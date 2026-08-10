"""CLI smoke and pack stale-withhold tests."""

from __future__ import annotations

from twin.cognize.commit import commit_narrative
from twin.inject.context_pack import build_context_pack
from twin.store.embeddings import HashEmbedder
from twin.interfaces.sovereignty.export import collect_export
from twin.interfaces.sovereignty.integrity import run_integrity_checks
from twin.interfaces.sovereignty.manifest import SCHEMA_VERSION


def test_cli_cognize_help():
    from twin.interfaces.cli import main
    import sys
    from io import StringIO

    buf = StringIO()
    old = sys.stdout
    try:
        sys.stdout = buf
        try:
            main(["cognize", "--help"])
        except SystemExit as e:
            assert e.code in (0, None)
    finally:
        sys.stdout = old
    out = buf.getvalue()
    assert "status" in out
    assert "review" in out


def test_cli_narrative_commit_preview_help():
    from twin.interfaces.cli import main
    import sys
    from io import StringIO

    buf = StringIO()
    old = sys.stdout
    try:
        sys.stdout = buf
        try:
            main(["narrative", "--help"])
        except SystemExit as e:
            assert e.code in (0, None)
    finally:
        sys.stdout = old
    out = buf.getvalue()
    assert "commit" in out
    assert "commit-preview" in out


def test_pack_refuses_forcing_stale_account_as_fresh(store, cfg):
    nar = commit_narrative(
        store,
        account="SECRET_STALE_ACCOUNT_TEXT",
        vault_id="default",
        evidence_ids=["ev_1"],
        committed_by="edu",
        domain="technical",
    )
    store.mark_epistemic_stale(
        nar.epistemic_state_id, reason="forced", unseen_percept_id="p_x"
    )
    pack = build_context_pack(
        store, cfg, HashEmbedder(), query="status", target_domain="technical",
    )
    entry = next(n for n in pack.narratives if n["narrative_id"] == nar.id)
    assert entry["epistemic_status"] == "stale"
    assert entry["account"] is None
    if "## Narratives" in (pack.context_pack or ""):
        fresh = (pack.context_pack or "").split("## Narratives")[-1].split("## Stale")[0]
        assert "SECRET_STALE_ACCOUNT_TEXT" not in fresh


def test_export_includes_cognize_sections(store):
    nar = commit_narrative(
        store,
        account="exported",
        vault_id="default",
        evidence_ids=["ev_1"],
        committed_by="edu",
    )
    data = collect_export(store)
    assert "cognize_narratives" in data
    assert any(n.id == nar.id for n in data["cognize_narratives"])
    assert SCHEMA_VERSION.startswith("twin-sovereignty-2")


def test_integrity_flags_narrative_without_evidence(store):
    from twin.cognize.models import Narrative

    bad = Narrative(vault_id="default", account="no evidence", evidence_ids=[], committed_by="u")
    store.upsert_narrative(bad)
    report = run_integrity_checks(store)
    assert report["stats"].get("narratives_without_evidence", 0) >= 1
    assert any("no evidence_ids" in p for p in report["problems"])
