"""Integrity checks for sovereignty / runtime integrity_check job."""

from __future__ import annotations

from typing import Any

from twin.store.store.base import TwinStore
from twin.privacy.vault import FALLBACK_VAULT, iter_vault_ids, vault_read_ids


def run_integrity_checks(store: TwinStore) -> dict[str, Any]:
    problems: list[str] = []
    stats: dict[str, int] = {}

    claims = []
    for status in ("candidate", "confirmed", "rejected"):
        claims.extend(store.list_claims(status=status, limit=5_000))
    stats["claims"] = len(claims)

    orphan_evidence = 0
    missing_evidence = 0
    for mem in claims:
        evs = store.get_evidence(mem.id)
        if not evs and mem.status.value == "confirmed":
            missing_evidence += 1
            problems.append(f"confirmed memory {mem.id} has no evidence")
        for ev in evs:
            if hasattr(store, "get_percept") and store.get_percept(ev.percept_id) is None:
                orphan_evidence += 1
                problems.append(
                    f"evidence {ev.id} references missing percept {ev.percept_id}"
                )
    stats["orphan_evidence"] = orphan_evidence
    stats["confirmed_without_evidence"] = missing_evidence

    nar_without_evidence = 0
    if hasattr(store, "list_narratives"):
        partitions: list[str] = []
        seen_vid: set[str] = set()
        for seed in list(iter_vault_ids(store) or [FALLBACK_VAULT]) + ["default", FALLBACK_VAULT]:
            for vid in vault_read_ids(seed):
                if vid in seen_vid:
                    continue
                seen_vid.add(vid)
                partitions.append(vid)
        seen_nar: set[str] = set()
        for vault in partitions:
            for nar in store.list_narratives(vault):
                if nar.id in seen_nar:
                    continue
                seen_nar.add(nar.id)
                if not (nar.evidence_ids or []):
                    nar_without_evidence += 1
                    problems.append(f"narrative {nar.id} has no evidence_ids")
                if nar.epistemic_state_id and hasattr(store, "get_epistemic_state"):
                    eps = store.get_epistemic_state(nar.epistemic_state_id)
                    if eps is None:
                        problems.append(
                            f"narrative {nar.id} missing epistemic_state {nar.epistemic_state_id}"
                        )
    stats["narratives_without_evidence"] = nar_without_evidence

    if hasattr(store, "runtime_queue_depth"):
        stats.update({f"queue_{k}": v for k, v in store.runtime_queue_depth().items()})

    if hasattr(store, "list_runtime_dead_letters"):
        dlq = store.list_runtime_dead_letters(limit=500)
        stats["dead_letters_open"] = len(dlq)

    return {
        "ok": len(problems) == 0,
        "problems": problems[:100],
        "problem_count": len(problems),
        "stats": stats,
    }
