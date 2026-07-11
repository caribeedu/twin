"""Memory quality metrics."""

from pathlib import Path

from twin.cognition import extract_percept
from twin.memory.metrics import compute_metrics
from twin.memory.models import MemoryStatus
from twin.sensory import sense_paths

EXAMPLES = Path(__file__).parent.parent / "examples"


def _populate(store, cfg, embedder):
    percepts, _ = sense_paths([EXAMPLES])
    for p in percepts:
        store.insert_percept(p)
        extract_percept(store, cfg, embedder, p)


def test_metrics_empty_store(store):
    metrics = compute_metrics(store)
    assert metrics["memories"]["total"] == 0
    assert metrics["quality"]["approval_rate"] is None
    assert metrics["firewall"]["blocks_logged"] == 0


def test_metrics_after_extraction_and_review(store, cfg, embedder):
    _populate(store, cfg, embedder)
    memories = store.list_memories()
    store.set_status(memories[0].id, MemoryStatus.confirmed)
    store.set_status(memories[1].id, MemoryStatus.rejected)

    metrics = compute_metrics(store)
    assert metrics["percepts"]["total"] == 3
    assert metrics["percepts"]["unprocessed"] == 0
    assert metrics["memories"]["total"] == len(memories)
    assert metrics["memories"]["by_status"]["confirmed"] == 1
    assert metrics["memories"]["by_status"]["rejected"] == 1
    # 1 approved out of 2 human-reviewed → extraction precision proxy
    assert metrics["quality"]["approval_rate"] == 0.5
    assert 0 <= metrics["memories"]["avg_confidence"] <= 1
    assert metrics["quality"]["review_backlog_ratio"] > 0
