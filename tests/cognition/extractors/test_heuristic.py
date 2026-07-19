from pathlib import Path

from tests.paths import EXAMPLES

from twin.cognition import extract_pending, extract_percept
from twin.sensory import sense_paths

def _percept(store, subpath):
    percepts, _ = sense_paths([EXAMPLES / subpath])
    store.insert_percept(percepts[0])
    return percepts[0]


def test_heuristic_finds_decisions_tasks_preferences(store, cfg, embedder):
    percept = _percept(store, "transcripts/standup-2026-07-08.txt")
    report = extract_percept(store, cfg, embedder, percept)
    assert report.extractor == "heuristic"
    memories = [store.get_memory(mid) for mid in report.inserted]
    types = {m.type.value for m in memories}
    assert "decision" in types
    assert "task" in types
    assert "preference" in types
    # heuristic output always goes through review
    assert all(m.needs_review for m in memories)
    # evidence is mandatory and points at the percept
    for m in memories:
        evidence = store.get_evidence(m.id)
        assert evidence
        assert evidence[0].percept_id == percept.id


def test_extract_pending_processes_each_percept_once(store, cfg, embedder):
    percepts, _ = sense_paths([EXAMPLES])
    for p in percepts:
        store.insert_percept(p)
    first = extract_pending(store, cfg, embedder)
    assert len(first) == 3  # md + txt + json
    second = extract_pending(store, cfg, embedder)
    assert second == []


def test_duplicate_memory_becomes_evidence(store, cfg, embedder):
    percept = _percept(store, "transcripts/standup-2026-07-08.txt")
    r1 = extract_percept(store, cfg, embedder, percept)
    assert r1.inserted
    # same content again (different percept) → all duplicates, no new memories
    percepts, _ = sense_paths([EXAMPLES / "transcripts"])
    clone = percepts[0]
    clone.integrity = {"content_hash": "different"}
    clone.seal()
    store.insert_percept(clone)
    r2 = extract_percept(store, cfg, embedder, clone)
    assert r2.inserted == []
    assert r2.duplicates == len(r1.inserted)


def test_source_trust_scales_confidence_and_floors_sensitivity(store, cfg, embedder):
    import pytest

    from twin.memory.calibration import calibrated_confidence
    from twin.sensory.percept import Percept

    percept = Percept(percept_type="slack_thread", source_sensor="slack",
                      content="Marina: decidimos usar FastAPI no backend.",
                      source_trust=0.5, source_scope="work",
                      source_confidentiality="private").seal()
    store.insert_percept(percept)
    report = extract_percept(store, cfg, embedder, percept)
    mem = store.get_memory(report.inserted[0])
    # soft calibration still reduces confidence under low source trust
    assert mem.confidence < 0.5
    assert mem.confidence == pytest.approx(
        calibrated_confidence("slack", mem.type.value, 0.5, source_trust=0.5,
                              extractor_reliability=0.95),
        abs=0.02,
    )
    assert mem.sensitivity.value == "private"           # floor from source
    assert mem.needs_review
