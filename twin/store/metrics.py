"""Memory quality metrics.

Answers "is the memory layer actually good?" with numbers the README's
success-metrics section asks for: extraction precision proxy, duplicate
rate, review load, confidence distribution and firewall activity.
"""

from __future__ import annotations

from typing import Any

from .store.base import TwinStore


def compute_metrics(store: TwinStore) -> dict[str, Any]:
    memories = store.list_claims(limit=1_000_000)
    percepts = store.list_percepts()
    unprocessed = store.unprocessed_percepts()

    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    confidences: list[float] = []
    needs_review = 0
    for m in memories:
        by_status[m.status.value] = by_status.get(m.status.value, 0) + 1
        by_type[m.type.value] = by_type.get(m.type.value, 0) + 1
        by_domain[m.domain] = by_domain.get(m.domain, 0) + 1
        confidences.append(m.confidence)
        if m.needs_review:
            needs_review += 1

    confirmed = by_status.get("confirmed", 0)
    rejected = by_status.get("rejected", 0)
    reviewed = confirmed + rejected
    evidence_total = store.count_evidence()
    total = len(memories)

    sessions = store.list_sessions(limit=1_000_000)
    feedback: list[dict] = []
    for ses in sessions:
        feedback.extend(ses.feedback)
    by_verdict: dict[str, int] = {}
    for fb in feedback:
        by_verdict[fb["verdict"]] = by_verdict.get(fb["verdict"], 0) + 1
    relevance_rated = sum(by_verdict.get(v, 0) for v in
                          ("useful", "partially_useful", "irrelevant", "incorrect"))
    sessions_with_feedback = [s_ for s_ in sessions if s_.feedback]

    # memory usage is measured in (session, memory) pairs on BOTH sides of
    # the ratio: a memory supplied in ten sessions counts ten times in the
    # denominator and up to ten times in the numerator — never a mix of
    # unique ids against occurrences
    supplied_pairs = sum(len(set(s_.supplied_claim_ids)) for s_ in sessions)
    used_pairs = len({
        (s_.id, fb["claim_id"])
        for s_ in sessions for fb in s_.feedback
        if fb.get("claim_id") and fb["verdict"] in ("useful", "partially_useful")
        and fb["claim_id"] in s_.supplied_claim_ids
    })

    return {
        "percepts": {
            "total": len(percepts),
            "unprocessed": len(unprocessed),
            "by_sensor": _count(percepts, lambda p: p.source_sensor),
        },
        "claims": {
            "total": total,
            "by_status": by_status,
            "by_type": by_type,
            "by_domain": by_domain,
            "needs_review": needs_review,
            "avg_confidence": round(sum(confidences) / total, 3) if total else 0.0,
        },
        "quality": {
            # share of human-reviewed memories that were approved — proxy for
            # extraction precision (README: "precisão de extração")
            "approval_rate": round(confirmed / reviewed, 3) if reviewed else None,
            # evidence rows beyond 1 per memory come from dedupe merging —
            # proxy for duplicate rate (README: "taxa de memórias duplicadas")
            "duplicate_evidence_ratio": round((evidence_total - total) / total, 3) if total else 0.0,
            "review_backlog_ratio": round(needs_review / total, 3) if total else 0.0,
            "duplicate_rate": round(
                sum(1 for m in memories if "exact_duplicate" in m.quality_flags
                    or "near_duplicate" in m.quality_flags) / total, 3
            ) if total else 0.0,
            "conflict_rate": round(
                sum(1 for m in memories if "possible_conflict" in m.quality_flags) / total, 3
            ) if total else 0.0,
            "unsupported_memory_rate": round(
                by_status.get("unsupported", 0) / total, 3
            ) if total else 0.0,
            "stale_memory_rate": round(
                by_status.get("stale", 0) / total, 3
            ) if total else 0.0,
            "merged_rate": round(by_status.get("merged", 0) / total, 3) if total else 0.0,
            "split_rate": round(by_status.get("split", 0) / total, 3) if total else 0.0,
            "avg_evidence_count": round(evidence_total / total, 3) if total else 0.0,
            "evidence_coverage": round(
                sum(1 for m in memories if m.percept_ids) / total, 3
            ) if total else 0.0,
            "avg_review_priority": round(
                sum(m.review_priority for m in memories if m.needs_review)
                / max(needs_review, 1), 3
            ) if needs_review else 0.0,
        },
        "firewall": {
            "blocks_logged": store.count_firewall_blocks(),
        },
        "sessions": {
            "total": len(sessions),
            "by_status": _count(sessions, lambda s_: getattr(s_.status, "value", s_.status)),
            "by_consolidation": _count(
                sessions, lambda s_: getattr(s_.consolidation_status, "value",
                                             s_.consolidation_status)),
            "by_task_profile": _count(sessions, lambda s_: s_.task_profile),
            "avg_pack_tokens": round(
                sum(s_.pack_chars for s_ in sessions) / len(sessions) / 4
            ) if sessions else 0,
            "memories_created": sum(len(s_.created_claim_ids) for s_ in sessions),
        },
        # The central product question: how often did the user need to
        # explain something twin should already have known?
        #
        # Denominators, precisely:
        # - *_relevant_rate: relevance verdicts only (useful, partially_useful,
        #   irrelevant, incorrect); partially_useful counts 0.5 in the weighted
        #   rate, fully in at_least_partially_relevant_rate, and not at all in
        #   fully_relevant_rate.
        # - re_explanation_rate: sessions with any feedback; a session counts
        #   once no matter how many missing_context verdicts it received.
        # - claim_usage_rate: (session, claim) pairs — supplied pairs below,
        #   pairs with a useful/partially_useful claim-scoped verdict above.
        "product": {
            "feedback_by_verdict": by_verdict,
            "context_relevance_rate": round(
                (by_verdict.get("useful", 0)
                 + 0.5 * by_verdict.get("partially_useful", 0)) / relevance_rated, 3
            ) if relevance_rated else None,
            "fully_relevant_rate": round(
                by_verdict.get("useful", 0) / relevance_rated, 3
            ) if relevance_rated else None,
            "at_least_partially_relevant_rate": round(
                (by_verdict.get("useful", 0)
                 + by_verdict.get("partially_useful", 0)) / relevance_rated, 3
            ) if relevance_rated else None,
            "false_claim_rate": round(
                by_verdict.get("incorrect", 0) / relevance_rated, 3
            ) if relevance_rated else None,
            "re_explanation_rate": round(
                sum(1 for s_ in sessions_with_feedback
                    if any(fb["verdict"] == "missing_context" for fb in s_.feedback))
                / len(sessions_with_feedback), 3
            ) if sessions_with_feedback else None,
            "privacy_overblocks": by_verdict.get("privacy_overblock", 0),
            "privacy_underblocks": by_verdict.get("privacy_underblock", 0),
            "claim_usage_rate": round(
                used_pairs / supplied_pairs, 3
            ) if supplied_pairs else None,
        },
        **_connector_block(store),
    }


def _connector_block(store: TwinStore) -> dict[str, Any]:
    """ — connector counters nested under the same metrics payload."""
    try:
        from twin.sense.connectors.metrics import compute_connector_metrics
    except Exception:
        return {"connectors": {"available": False}}
    return compute_connector_metrics(store)


def _count(items, key) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        k = key(item)
        out[k] = out.get(k, 0) + 1
    return out
