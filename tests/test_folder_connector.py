"""v0.6 Phase 6 — local folder / shared documents connector."""

from __future__ import annotations

from pathlib import Path

import pytest

from twin.connectors import (
    add_connector_instance,
    build_credential_store,
    register_source_account,
    sync_connector,
)


@pytest.fixture()
def creds(tmp_path):
    return build_credential_store(tmp_path / "creds-home")


def _mk(store, creds, roots, *, extra=None):
    acc = register_source_account(
        store, connector_type="folder", source_owner="employer", org_key="acme",
        owner_principal_id="principal_test",
        external_account_id="local-docs",
    )
    inst = add_connector_instance(
        store, creds, account_id=acc.id, secret=None,
        configuration={"roots": list(roots), **(extra or {})},
    )
    return acc, inst


def test_empty_roots_await_configuration(store, creds):
    _acc, inst = _mk(store, creds, roots=[])
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "awaiting_configuration"


def test_sync_ingests_markdown_with_revision_and_ownership(store, creds, tmp_path):
    root = tmp_path / "shared"
    root.mkdir()
    doc = root / "rfc-webhooks.md"
    doc.write_text(
        "---\nauthor: Edu\ndate: 2026-06-20\n---\n\n"
        "# RFC\n\nWe decided to use an outbox pattern.\n",
        encoding="utf-8",
    )
    _acc, inst = _mk(store, creds, roots=[{
        "id": "eng-docs", "label": "eng-docs", "path": str(root),
    }])
    result = sync_connector(store, creds, inst.id)
    assert result.health.value == "healthy"
    assert result.percepts == 1
    rec = store.list_connector_records(inst.id)[0]
    assert rec.external_type == "document_revision"
    assert rec.external_id == "folder:eng-docs:rfc-webhooks.md"
    assert rec.thread_key.startswith("document:folder:")
    assert rec.source_metadata["document_id"] == rec.external_id
    assert rec.source_metadata["revision_id"]
    assert rec.source_metadata["content_hash"]
    assert "outbox" in rec.content
    assert any(a.startswith("document:folder:person:") or a.startswith("mail:")
               for a in rec.actor_ids)
    ckpt = store.get_connector_checkpoint(inst.id, "folder:eng-docs")
    assert ckpt is not None
    assert "rfc-webhooks.md" in (ckpt.cursor.get("known_files") or {})
    percepts = store.list_percepts()
    assert all(p.metadata.get("vault_id") == "vault_work_acme" for p in percepts)


def test_idempotent_resync(store, creds, tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "a.md").write_text("# A\n", encoding="utf-8")
    _acc, inst = _mk(store, creds, roots=[{
        "id": "d", "path": str(root),
    }])
    assert sync_connector(store, creds, inst.id).percepts == 1
    assert sync_connector(store, creds, inst.id).percepts == 0


def test_edit_creates_new_revision(store, creds, tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    path = root / "note.md"
    path.write_text("# v1\n", encoding="utf-8")
    _acc, inst = _mk(store, creds, roots=[{"id": "d", "path": str(root)}])
    sync_connector(store, creds, inst.id)
    path.write_text("# v2 — edited\n", encoding="utf-8")
    sync_connector(store, creds, inst.id)
    revs = store.list_connector_records_for_object(
        inst.id, "document_revision", "folder:d:note.md",
    )
    assert len(revs) == 2
    assert any("v1" in r.content for r in revs)
    assert any("v2" in r.content for r in revs)
    # Same document lineage / thread.
    assert len({r.thread_key for r in revs}) == 1


def test_delete_emits_tombstone(store, creds, tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    path = root / "gone.md"
    path.write_text("# bye\n", encoding="utf-8")
    _acc, inst = _mk(store, creds, roots=[{"id": "d", "path": str(root)}])
    sync_connector(store, creds, inst.id)
    path.unlink()
    result = sync_connector(store, creds, inst.id)
    assert result.streams[0].deletion_events >= 1
    events = store.list_connector_deletion_events(inst.id)
    assert events
    assert events[0].external_id == "folder:d:gone.md"
    assert events[0].affected_percept_ids
    latest = store.list_connector_records_for_object(
        inst.id, "document_revision", "folder:d:gone.md",
    )[-1]
    assert latest.deleted


def test_exclude_globs(store, creds, tmp_path):
    root = tmp_path / "docs"
    (root / "keep").mkdir(parents=True)
    (root / "skip").mkdir(parents=True)
    (root / ".git").mkdir(parents=True)
    (root / "keep" / "ok.md").write_text("# ok\n", encoding="utf-8")
    (root / "skip" / "no.md").write_text("# no\n", encoding="utf-8")
    (root / "root.md").write_text("# root\n", encoding="utf-8")
    (root / ".git" / "config").write_text("x", encoding="utf-8")
    _acc, inst = _mk(store, creds, roots=[{"id": "d", "path": str(root)}], extra={
        "exclude_globs": ["skip/**"],
    })
    sync_connector(store, creds, inst.id)
    ids = {r.external_id for r in store.list_connector_records(inst.id)}
    assert "folder:d:keep/ok.md" in ids
    assert "folder:d:root.md" in ids
    assert "folder:d:skip/no.md" not in ids
    assert "folder:d:.git/config" not in ids


def test_match_any_does_not_treat_starstar_as_basename():
    from twin.connectors.folder.scanner import _match_any

    assert _match_any("rfc.md", ("**/*.md",))
    assert not _match_any("rfc.md", ("**/.git/**", "**/node_modules/**"))
    assert _match_any(".git/config", ("**/.git/**",))
    assert _match_any("vendor/node_modules/pkg/index.js", ("**/node_modules/**",))


def test_list_roots_reports_readability(store, creds, tmp_path):
    from twin.connectors.registry import build_adapter
    root = tmp_path / "docs"
    root.mkdir()
    _acc, inst = _mk(store, creds, roots=[
        {"id": "ok", "path": str(root)},
        {"id": "missing", "path": str(tmp_path / "nope")},
    ])
    adapter = build_adapter(inst, _acc, None)
    roots = {r["id"]: r for r in adapter.list_roots()}
    assert roots["ok"]["readable"] is True
    assert roots["missing"]["exists"] is False
