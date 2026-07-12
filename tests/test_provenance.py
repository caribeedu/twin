"""Artifact provenance and retention propagation (twin.memory.provenance/retention)."""

from twin import ids
from twin.clock import now_iso
from twin.memory.models import Artifact, Evidence, MemoryItem, MemoryStatus
from twin.memory.provenance import ensure_artifact_from_percept, memory_provenance
from twin.memory.retention import delete_artifact
from twin.sensory.percept import Percept


def _mem(store, embedder, **kw):
    base = dict(
        id=ids.memory_id(), type="fact", title="t", summary="s",
        domain="technical", confidence=0.9, status="confirmed",
        entities=["Twin"],
    )
    base.update(kw)
    mem = MemoryItem(**base)
    store.insert_memory(mem)
    store.store_embedding(
        mem.id, "memory", embedder.name,
        embedder.embed(f"{mem.title}\n{mem.summary}"),
    )
    return mem


def test_artifact_provenance_and_deletion(store, embedder):
    p = Percept(
        id=ids.new_id("pct"), percept_type="git_commit", source_sensor="git",
        content="feat: switch primary store to postgres",
        content_refs=[{"path": "commit", "sha": "abc123"}],
        metadata={"sha": "abc123", "artifact_kind": "git_commit"},
    )
    store.insert_percept(p)
    art_id = ensure_artifact_from_percept(store, p)
    assert art_id
    mem = _mem(store, embedder, title="Postgres", summary="Primary store is PostgreSQL.",
               status="confirmed")
    store.insert_evidence(Evidence(
        id=ids.evidence_id(), memory_id=mem.id, percept_id=p.id,
        quote="switch primary store to postgres", artifact_id=art_id,
    ))
    prov = memory_provenance(store, mem.id)
    assert prov["artifacts"]
    plan = delete_artifact(store, art_id, dry_run=False)
    assert mem.id in plan["memories_unsupported"] or mem.id in plan["memories_recalculated"]
    reloaded = store.get_memory(mem.id)
    assert reloaded.status in (MemoryStatus.unsupported, MemoryStatus.confirmed)


def test_delete_artifact_does_not_cascade_by_hash(store, embedder):
    p1 = Percept(id=ids.new_id("pct"), percept_type="document", source_sensor="git",
                 content="readme from git commit abc", metadata={"sha": "aaa"})
    p2 = Percept(id=ids.new_id("pct"), percept_type="document", source_sensor="document",
                 content="readme local copy distinct bytes", metadata={"path": "local-copy"})
    assert store.insert_percept(p1)
    assert store.insert_percept(p2)
    # Artifact A intentionally carries the same content_hash as percept B.
    # Explicit lineage still points only at percept A — hash must not cascade.
    art1 = Artifact(id=ids.artifact_id(), kind="git_commit", source_system="git",
                    content_hash=p2.content_hash, created_at=now_iso(),
                    metadata={"percept_id": p1.id})
    art2 = Artifact(id=ids.artifact_id(), kind="document", source_system="document",
                    content_hash=p2.content_hash, created_at=now_iso(),
                    metadata={"percept_id": p2.id})
    store.insert_artifact(art1)
    store.insert_artifact(art2)
    store.link_artifact_percept(art1.id, p1.id)
    store.link_artifact_percept(art2.id, p2.id)

    m1 = _mem(store, embedder, title="from git", summary="README decision from git.")
    m2 = _mem(store, embedder, title="from local", summary="README decision from local copy.")
    store.insert_evidence(Evidence(
        id=ids.evidence_id(), memory_id=m1.id, percept_id=p1.id,
        quote="README", artifact_id=art1.id,
    ))
    store.insert_evidence(Evidence(
        id=ids.evidence_id(), memory_id=m2.id, percept_id=p2.id,
        quote="README", artifact_id=art2.id,
    ))

    plan = delete_artifact(store, art1.id, dry_run=False)
    assert p2.id not in plan["percepts"]
    assert "[content destroyed]" not in store.get_percept(p2.id).content
    assert store.get_memory(m2.id).status == MemoryStatus.confirmed
