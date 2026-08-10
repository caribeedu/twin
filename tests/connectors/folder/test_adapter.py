"""Local folder / shared documents connector."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from twin.sense.connectors import (
    add_connector_instance,
    build_credential_store,
    register_source_account,
    sync_connector,
)
from twin.sense.connectors.folder.scanner import FolderScanner, validate_roots
from twin.sense.connectors.protocol import ConnectorError


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


def test_base_stream_strips_backfill_namespace():
    from twin.sense.connectors.folder.adapter import _base_stream

    assert _base_stream("folder:eng-docs") == "folder:eng-docs"
    assert _base_stream(
        "backfill:backfill_x:2016-09:folder:eng-docs") == "folder:eng-docs"
    with pytest.raises(ConnectorError):
        _base_stream("backfill:onlyjob")  # too few parts to be a partition


def test_parse_stream_accepts_backfill_namespace(store, creds, tmp_path):
    root = tmp_path / "shared"
    root.mkdir()
    _acc, inst = _mk(store, creds, roots=[{
        "id": "eng-docs", "label": "eng-docs", "path": str(root),
    }])
    from twin.sense.connectors.folder.adapter import FolderConnector

    account = store.get_source_account(inst.account_id)
    adapter = FolderConnector(inst, account, None)
    assert adapter._parse_stream("folder:eng-docs") == "eng-docs"
    assert adapter._parse_stream(
        "backfill:backfill_x:2016-09:folder:eng-docs") == "eng-docs"
    with pytest.raises(ConnectorError):
        adapter._parse_stream("bogus:eng-docs")


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
    assert result.percepts == 2  # manifest + chunk
    recs = store.list_connector_records(inst.id)
    types = {r.external_type for r in recs}
    assert types == {"document_manifest", "document_revision_chunk"}
    chunk = next(r for r in recs if r.external_type == "document_revision_chunk")
    assert chunk.external_id == "folder:eng-docs:rfc-webhooks.md:chunk:0"
    assert chunk.thread_key.startswith("document:folder:")
    assert chunk.source_metadata["document_id"] == "folder:eng-docs:rfc-webhooks.md"
    assert chunk.source_metadata["revision_id"]
    assert chunk.source_metadata["content_hash"]
    assert chunk.source_metadata["identity_stability"] == "path_stable"
    assert "outbox" in chunk.content
    # Author label must not become a global person actor.
    assert chunk.actor_ids == []
    assert chunk.source_metadata["author"]["author_label"] == "Edu"
    assert chunk.source_metadata["author"]["actor_id"] is None
    ckpt = store.get_connector_checkpoint(inst.id, "folder:eng-docs")
    assert ckpt is not None
    assert "rfc-webhooks.md" in (ckpt.cursor.get("known_files") or {})
    assert (ckpt.cursor.get("scan_stats") or {}).get("mode") == "full_scan"
    percepts = store.list_percepts()
    assert all(p.metadata.get("vault_id") == "vault_work_acme" for p in percepts)


def test_idempotent_resync(store, creds, tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "a.md").write_text("# A\n", encoding="utf-8")
    _acc, inst = _mk(store, creds, roots=[{
        "id": "d", "path": str(root),
    }])
    assert sync_connector(store, creds, inst.id).percepts == 2
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
    chunks = store.list_connector_records_for_object(
        inst.id, "document_revision_chunk", "folder:d:note.md:chunk:0",
    )
    assert len(chunks) == 2
    assert any("v1" in r.content for r in chunks)
    assert any("v2" in r.content for r in chunks)
    assert len({r.thread_key for r in chunks}) == 1


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
    assert any(e.affected_percept_ids for e in events)
    latest_chunk = store.list_connector_records_for_object(
        inst.id, "document_revision_chunk", "folder:d:gone.md:chunk:0",
    )[-1]
    assert latest_chunk.deleted
    latest_doc = store.list_connector_records_for_object(
        inst.id, "document_revision", "folder:d:gone.md",
    )[-1]
    assert latest_doc.deleted


def test_large_document_chunked_without_loss(store, creds, tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    sections = []
    for i in range(60):
        sections.append(f"## Section-{i}-END\n\n" + (f"uniq-{i}-x " * 600))
    body = "\n".join(sections)
    assert len(body.encode("utf-8")) > 120_000
    (root / "big.md").write_text(body, encoding="utf-8")
    _acc, inst = _mk(store, creds, roots=[{"id": "d", "path": str(root)}])
    sync_connector(store, creds, inst.id)
    chunks = [
        r for r in store.list_connector_records(inst.id)
        if r.external_type == "document_revision_chunk" and not r.deleted
    ]
    assert len(chunks) > 1
    assert all(r.source_metadata["document_id"] == "folder:d:big.md" for r in chunks)
    assert len({r.source_metadata["revision_id"] for r in chunks}) == 1
    joined = "\n".join(r.content for r in chunks)
    for i in range(60):
        assert joined.count(f"## Section-{i}-END") == 1
        assert joined.count(f"uniq-{i}-x ") == body.count(f"uniq-{i}-x ")


def test_oversized_file_manifest_only(store, creds, tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "huge.md").write_text("x" * 5000, encoding="utf-8")
    _acc, inst = _mk(
        store, creds, roots=[{"id": "d", "path": str(root)}],
        extra={"max_file_bytes": 100},
    )
    sync_connector(store, creds, inst.id)
    recs = [r for r in store.list_connector_records(inst.id) if not r.deleted]
    assert len(recs) == 1
    assert recs[0].external_type == "document_manifest"
    assert recs[0].source_metadata["content_available"] is False
    assert recs[0].source_metadata["evidence_role"] == "artifact_metadata"
    assert "xxxxx" not in recs[0].content  # body not presented as primary text


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
    ids = {r.source_metadata.get("document_id") for r in store.list_connector_records(inst.id)}
    assert "folder:d:keep/ok.md" in ids
    assert "folder:d:root.md" in ids
    assert "folder:d:skip/no.md" not in ids
    assert "folder:d:.git/config" not in ids


def test_match_any_does_not_treat_starstar_as_basename():
    from twin.sense.connectors.folder.scanner import _match_any

    assert _match_any("rfc.md", ("**/*.md",))
    assert not _match_any("rfc.md", ("**/.git/**", "**/node_modules/**"))
    assert _match_any(".git/config", ("**/.git/**",))
    assert _match_any("vendor/node_modules/pkg/index.js", ("**/node_modules/**",))


def test_list_roots_reports_readability(store, creds, tmp_path):
    from twin.sense.connectors.registry import build_adapter
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


def test_symlink_outside_root_rejected(store, creds, tmp_path):
    root = tmp_path / "shared"
    outside = tmp_path / "secret.md"
    root.mkdir()
    outside.write_text("# SECRET outside\n", encoding="utf-8")
    link = root / "leak.md"
    link.symlink_to(outside)
    (root / "ok.md").write_text("# ok\n", encoding="utf-8")
    _acc, inst = _mk(store, creds, roots=[{"id": "d", "path": str(root)}])
    sync_connector(store, creds, inst.id)
    docs = {
        r.source_metadata.get("document_id")
        for r in store.list_connector_records(inst.id)
    }
    assert "folder:d:ok.md" in docs
    assert "folder:d:leak.md" not in docs
    for raw in store.list_connector_raw_items(inst.id):
        assert "SECRET outside" not in str(raw.payload)
    for r in store.list_connector_records(inst.id):
        assert "SECRET outside" not in (r.content or "")


def test_symlink_inside_root_with_follow(store, creds, tmp_path):
    root = tmp_path / "shared"
    root.mkdir()
    target = root / "real.md"
    target.write_text("# inside target\n", encoding="utf-8")
    (root / "alias.md").symlink_to(target)
    _acc, inst = _mk(
        store, creds, roots=[{"id": "d", "path": str(root)}],
        extra={"follow_symlinks": True},
    )
    sync_connector(store, creds, inst.id)
    docs = {
        r.source_metadata.get("document_id")
        for r in store.list_connector_records(inst.id)
    }
    assert "folder:d:real.md" in docs
    assert "folder:d:alias.md" in docs


def test_symlink_broken_and_default_skip(tmp_path):
    root = tmp_path / "shared"
    root.mkdir()
    (root / "ok.md").write_text("# ok\n", encoding="utf-8")
    (root / "broken.md").symlink_to(root / "missing.md")
    (root / "loop.md").symlink_to(root / "loop.md")
    sc = FolderScanner([{"id": "d", "path": str(root)}], follow_symlinks=False)
    docs, _, _ = sc.scan("d")
    ids = {d.external_id for d in docs}
    assert ids == {"folder:d:ok.md"}
    assert sc.symlink_skips >= 1


def test_duplicate_root_ids_fail():
    with pytest.raises(ConnectorError) as ei:
        validate_roots([
            {"id": "docs", "path": "/a"},
            {"id": "docs", "path": "/b"},
        ])
    assert ei.value.failure_class.value == "configuration"
    assert ei.value.human_action_required is True


def test_empty_root_id_fails():
    with pytest.raises(ConnectorError):
        validate_roots([{"id": "", "path": "/a"}])


def test_overlapping_roots_fail_by_default(tmp_path):
    a = tmp_path / "workspace"
    b = a / "docs"
    b.mkdir(parents=True)
    with pytest.raises(ConnectorError) as ei:
        validate_roots([
            {"id": "A", "path": str(a)},
            {"id": "B", "path": str(b)},
        ])
    assert "overlapping" in str(ei.value).lower()


def test_overlapping_roots_allowed_when_configured(tmp_path):
    a = tmp_path / "workspace"
    b = a / "docs"
    b.mkdir(parents=True)
    validate_roots(
        [{"id": "A", "path": str(a)}, {"id": "B", "path": str(b)}],
        allow_overlapping_roots=True,
    )


def test_permissions_reflect_world_readable(tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    path = root / "open.md"
    path.write_text("# open\n", encoding="utf-8")
    os.chmod(path, 0o644)
    sc = FolderScanner([{"id": "d", "path": str(root)}])
    docs, _, _ = sc.scan("d")
    assert len(docs) == 1
    perms = docs[0].permissions
    if os.name != "nt":
        assert perms.get("permission_inspection") == "posix_stat"
        assert perms.get("world_readable") is True
        assert perms.get("group_readable") is True
    else:
        assert perms.get("permission_inspection") == "not_evaluated"


def test_permissions_private_file(tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    path = root / "private.md"
    path.write_text("# private\n", encoding="utf-8")
    os.chmod(path, 0o600)
    sc = FolderScanner([{"id": "d", "path": str(root)}])
    docs, _, _ = sc.scan("d")
    if os.name != "nt":
        assert docs[0].permissions.get("world_readable") is False
        assert docs[0].permissions.get("group_readable") is False
