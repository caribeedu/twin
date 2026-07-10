from pathlib import Path

from twin.extract import extract_source, extract_pending
from twin.ingest import ingest_paths, load_file

EXAMPLES = Path(__file__).parent.parent / "examples"


def test_heuristic_finds_decisions_tasks_preferences(db, cfg, embedder):
    src = load_file(EXAMPLES / "transcripts" / "standup-2026-07-08.txt")
    db.insert_source(src)
    report = extract_source(db, cfg, embedder, src)
    assert report.extractor == "heuristic"
    memories = [db.get_memory(mid) for mid in report.inserted]
    types = {m.type.value for m in memories}
    assert "decision" in types
    assert "task" in types
    assert "preference" in types
    # heuristic output always goes through review
    assert all(m.needs_review for m in memories)
    # evidence is mandatory
    for m in memories:
        assert db.get_evidence(m.id)


def test_extract_pending_processes_each_source_once(db, cfg, embedder):
    ingest_paths(db, [EXAMPLES])
    first = extract_pending(db, cfg, embedder)
    assert len(first) == 3  # md + txt + json
    second = extract_pending(db, cfg, embedder)
    assert second == []


def test_duplicate_memory_becomes_evidence(db, cfg, embedder):
    src = load_file(EXAMPLES / "transcripts" / "standup-2026-07-08.txt")
    db.insert_source(src)
    r1 = extract_source(db, cfg, embedder, src)
    assert r1.inserted
    # same content again → all duplicates, no new memories
    src2 = load_file(EXAMPLES / "transcripts" / "standup-2026-07-08.txt")
    src2.content_hash = "different"
    db.insert_source(src2)
    r2 = extract_source(db, cfg, embedder, src2)
    assert r2.inserted == []
    assert r2.duplicates == len(r1.inserted)
