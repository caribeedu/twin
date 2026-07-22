"""v0.7 Blocker 1: heuristic mode is detection-only.

Lexical rules may flag that a span *looks like* it could carry a decision or
task, but they must never establish a memory type, domain, entity or cognitive
confidence. In ``TWIN_EXTRACTOR=heuristic`` the pipeline records
``DetectionSignal``s and creates no ``MemoryItem`` at all.
"""

from tests.paths import EXAMPLES

from twin.cognition import extract_pending, extract_percept
from twin.sensory import sense_paths


def _percept(store, subpath):
    percepts, _ = sense_paths([EXAMPLES / subpath])
    store.insert_percept(percepts[0])
    return percepts[0]


def _heuristic_cfg(cfg):
    cfg.extractor = "heuristic"
    return cfg


def test_heuristic_mode_never_creates_semantic_memory(store, cfg, embedder):
    cfg = _heuristic_cfg(cfg)
    percept = _percept(store, "transcripts/standup-2026-07-08.txt")
    report = extract_percept(store, cfg, embedder, percept)

    # no cognitive memory is established by lexical rules
    assert store.list_memories() == []
    assert report.inserted == []
    assert report.interpretation_status == "heuristic_detection"

    # but conservative detection signals ARE recorded (routing hints only)
    signals = store.list_detection_signals(percept.id)
    assert signals
    kinds = {s.kind for s in signals}
    assert kinds & {"decision", "task", "preference", "constraint",
                    "rejected_alternative"}
    # a signal carries a span and a detection confidence, never a memory type
    assert all(s.span and 0 <= s.confidence <= 1 for s in signals)


def test_heuristic_detection_is_terminal_not_reinterpreted(store, cfg, embedder):
    cfg = _heuristic_cfg(cfg)
    percept = _percept(store, "transcripts/standup-2026-07-08.txt")
    extract_percept(store, cfg, embedder, percept)
    state = store.get_interpretation(percept.id)
    assert state.status == "heuristic_detection"
    assert state.interpretation_attempted is False   # it was NOT interpreted
    assert state.terminal is True
    # not selected again while content is unchanged
    assert store.percepts_pending_interpretation(max_attempts=6) == []


def test_scan_detects_rejected_alternatives():
    """The rejected-alternative detector still fires — as a hint, not a memory."""
    from twin.cognition.extractors.heuristic import scan

    hits = scan("Instead of Redis we will use PostgreSQL advisory locks. "
                "We also decided against MongoDB because of licensing.")
    rejected = [h for h in hits if h.kind == "rejected_alternative"]
    assert len(rejected) == 2
    assert all(h.span for h in rejected)


# -- the echo mock (non-interpreting offline stand-in used by the suite) --------


def test_echo_mock_makes_no_semantic_classification(store, cfg, embedder):
    """The default offline mock (echo) grounds content as neutral facts but
    classifies nothing — every item is a review-bound 'fact'/'statement', so no
    lexical rule establishes a decision/preference/etc. Meaning comes only from
    a real (or scripted) interpreter."""
    percept = _percept(store, "transcripts/standup-2026-07-08.txt")
    report = extract_percept(store, cfg, embedder, percept)   # cfg.extractor == "echo"
    assert report.extractor == "echo"
    memories = [store.get_memory(mid) for mid in report.inserted]
    assert memories
    # NO semantic categories are invented — everything is the null 'fact'
    assert {m.type.value for m in memories} == {"fact"}
    assert all(m.payload.get("cognitive_act") == "statement" for m in memories)
    assert all(m.needs_review for m in memories)          # mock is never trusted
    for m in memories:
        evidence = store.get_evidence(m.id)
        assert evidence and evidence[0].percept_id == percept.id
        # the span is a verbatim slice of the source (grounded)
        assert evidence[0].quote in percept.content


def test_extract_pending_processes_each_percept_once(store, cfg, embedder):
    percepts, _ = sense_paths([EXAMPLES])
    for p in percepts:
        store.insert_percept(p)
    first = extract_pending(store, cfg, embedder)
    assert len(first) == 3  # md + txt + json
    second = extract_pending(store, cfg, embedder)
    assert second == []
