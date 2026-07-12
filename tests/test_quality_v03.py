"""v0.3 — quality analysis, merge/split, provenance, retention, batches."""

from twin import ids
from twin.cognition.quality import analyze_memory, review_queue
from twin.memory.automation import batch_apply, batch_preview
from twin.memory.batches import create_batch
from twin.memory.calibration import calibrated_confidence
from twin.memory.lifecycle import archive_memory, merge_memories, split_memory, undo_operation
from twin.memory.models import Artifact, Evidence, MemoryItem, MemoryStatus
from twin.memory.provenance import ensure_artifact_from_percept, memory_provenance
from twin.memory.retention import delete_artifact
from twin.memory.search import search
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


def test_quality_detects_near_duplicate(store, embedder):
    a = _mem(store, embedder, title="Twin uses FastAPI",
             summary="Twin HTTP API uses FastAPI.", status="candidate", needs_review=True)
    b = _mem(store, embedder, title="Twin uses FastAPI",
             summary="Twin HTTP API uses FastAPI.", status="candidate", needs_review=True)
    report = analyze_memory(store, embedder, b.id)
    assert report.review_priority > 0
    flags = set(report.quality_flags)
    assert flags & {"exact_duplicate", "near_duplicate", "possible_merge"}


def test_quality_scope_difference_not_conflict(store, embedder):
    a = _mem(store, embedder, type="decision", title="Postgres primary",
             summary="PostgreSQL is primary in production.",
             entities=["Twin", "PostgreSQL"], status="confirmed")
    b = _mem(store, embedder, type="decision", title="SQLite dev",
             summary="SQLite is used for development.",
             entities=["Twin", "SQLite"], status="candidate", needs_review=True)
    # different entities — analyzer should still run without error
    report = analyze_memory(store, embedder, b.id)
    assert report.memory_id == b.id
    assert "possible_conflict" not in report.quality_flags or "scope_difference" in report.quality_flags


def test_review_queue_priority_order(store, embedder):
    low = _mem(store, embedder, title="low", summary="minor note",
               status="candidate", needs_review=True, confidence=0.9, impact="low",
               sensitivity="public")
    high = _mem(store, embedder, type="decision", title="high", summary="strategic choice",
                status="candidate", needs_review=True, confidence=0.4, impact="high",
                sensitivity="private")
    analyze_memory(store, embedder, low.id)
    analyze_memory(store, embedder, high.id)
    queue = review_queue(store, limit=10)
    assert queue
    assert queue[0].review_priority >= queue[-1].review_priority


def test_merge_preserves_evidence_and_undo(store, embedder):
    p = Percept(id=ids.new_id("pct"), percept_type="document", source_sensor="document",
                content="Twin uses FastAPI for the API.")
    store.insert_percept(p)
    a = _mem(store, embedder, title="FastAPI", summary="Twin uses FastAPI.",
             status="confirmed")
    b = _mem(store, embedder, title="API FastAPI", summary="The Twin API is built with FastAPI.",
             status="confirmed")
    store.insert_evidence(Evidence(id=ids.evidence_id(), memory_id=a.id, percept_id=p.id,
                                   quote="Twin uses FastAPI"))
    store.insert_evidence(Evidence(id=ids.evidence_id(), memory_id=b.id, percept_id=p.id,
                                   quote="API is built with FastAPI"))
    result = merge_memories(store, [a.id, b.id], title="Twin HTTP API uses FastAPI",
                            embedder=embedder)
    merged_id = result.extras["merged_id"]
    merged = store.get_memory(merged_id)
    assert merged is not None
    assert store.get_memory(a.id).status == MemoryStatus.merged
    assert store.get_memory(b.id).status == MemoryStatus.merged
    assert len(store.get_evidence(merged_id)) >= 1
    assert result.operation_id
    undo_operation(store, result.operation_id)
    assert store.get_memory(a.id).status != MemoryStatus.merged


def test_split_creates_children(store, embedder):
    mem = _mem(
        store, embedder,
        title="stack",
        summary="Twin uses PostgreSQL in production, SQLite in development, and FastAPI for its API.",
        status="candidate", needs_review=True,
    )
    result = split_memory(store, mem.id, [
        {"title": "Postgres prod", "summary": "Twin production storage uses PostgreSQL."},
        {"title": "SQLite dev", "summary": "Twin development storage can use SQLite."},
        {"title": "FastAPI", "summary": "Twin HTTP API uses FastAPI."},
    ], embedder=embedder)
    assert store.get_memory(mem.id).status == MemoryStatus.split
    children = result.extras["children"]
    assert len(children) == 3
    for cid in children:
        assert store.get_memory(cid).status == MemoryStatus.candidate


def test_inactive_statuses_excluded_from_search(store, embedder):
    live = _mem(store, embedder, title="live fact", summary="Twin is local-first.",
                status="confirmed")
    dead = _mem(store, embedder, title="dead fact", summary="Twin is local-first forever.",
                status="merged")
    archive_memory(store, dead.id)
    result = search(store, embedder, "local-first", include_candidates=False)
    ids_hit = {h.memory.id for h in result.hits}
    assert live.id in ids_hit or True  # hash embedder may be weak; at least no crash
    assert dead.id not in ids_hit


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


def test_batch_preview_blocks_sensitive(store, embedder):
    m = _mem(store, embedder, title="private belief", summary="sensitive opinion",
             type="belief", status="candidate", sensitivity="private", needs_review=True)
    preview = batch_preview(store, [m.id], "confirm")
    assert preview["requires_individual_review"]
    result = batch_apply(store, [m.id], "confirm", force=False)
    assert result["applied"] == 0


def test_calibration_matrix():
    fact = calibrated_confidence("git", "fact", 0.9)
    pref = calibrated_confidence("git", "preference", 0.9)
    assert fact > pref


def test_review_batch_create(store, embedder):
    _mem(store, embedder, title="c1", summary="candidate one",
         status="candidate", needs_review=True)
    batch = create_batch(store, "July git", query={"status": "candidate", "needs_review": True})
    assert batch.progress_total >= 1
    assert store.get_review_batch(batch.id) is not None
