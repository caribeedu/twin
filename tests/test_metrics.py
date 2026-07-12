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


def test_session_and_product_metrics(store, cfg, embedder):
    from twin.cognition.sessions import (
        complete_session,
        record_feedback,
        start_session,
    )

    s1 = start_session(store, cfg, embedder, "escrever a rfc de arquitetura",
                       domain="technical").session
    s2 = start_session(store, cfg, embedder, "investigate the bug stacktrace",
                       domain="technical").session
    complete_session(store, cfg, embedder, s1.id,
                     summary="We decided to use RabbitMQ for the queue.")
    record_feedback(store, s1.id, "useful")
    record_feedback(store, s2.id, "missing_context",
                    note="had to re-explain the queue decision")
    record_feedback(store, s2.id, "privacy_overblock")

    metrics = compute_metrics(store)
    sessions = metrics["sessions"]
    assert sessions["total"] == 2
    assert sessions["by_status"] == {"completed": 1, "active": 1}
    assert sessions["by_task_profile"]["architecture"] == 1
    assert sessions["by_task_profile"]["debugging"] == 1
    assert sessions["memories_created"] >= 1

    product = metrics["product"]
    assert product["feedback_by_verdict"] == {
        "useful": 1, "missing_context": 1, "privacy_overblock": 1,
    }
    # 1 useful out of 1 relevance-rated verdict
    assert product["context_relevance_rate"] == 1.0
    assert product["false_memory_rate"] == 0.0
    # 1 of the 2 sessions with feedback needed re-explanation
    assert product["re_explanation_rate"] == 0.5
    assert product["privacy_overblocks"] == 1


def test_product_metrics_empty(store):
    metrics = compute_metrics(store)
    assert metrics["sessions"]["total"] == 0
    assert metrics["product"]["context_relevance_rate"] is None
    assert metrics["product"]["re_explanation_rate"] is None


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
