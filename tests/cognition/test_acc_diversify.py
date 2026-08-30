"""ACC cross-sense quota: Slack must not be crowded out by github commits."""
from __future__ import annotations

from types import SimpleNamespace

from twin.cognize.services.analysis_dossier import (
    CROSS_SENSE_RESERVED,
    MAX_CROSS_SENSE,
    _diversify_cross_sense,
)


def _rec(sense: str, rid: str):
    # sense_for_record keys off source_metadata / connector hints
    if sense == "github":
        sm = {"repo": "caribeedu/dogwalker"}
        et = "commit"
    else:
        sm = {"channel": "C1", "team_id": "T1", "author_kind": "human"}
        et = "message"
    return SimpleNamespace(
        id=rid,
        external_type=et,
        external_id=rid,
        content=f"{sense} {rid}",
        source_metadata=sm,
        connector_id=f"conn_{sense}",
    )


def test_diversify_reserves_other_sense_slots():
    scored = []
    # 20 high-scoring github commits, then 2 slightly lower slack hits
    for i in range(20):
        scored.append((_rec("github", f"gh{i}"), 1.30, ["topic", "project", "time"]))
    scored.append((_rec("slack", "sl1"), 0.88, ["topic", "project", "time", "cross-sense"]))
    scored.append((_rec("slack", "sl2"), 0.87, ["topic", "project", "time", "cross-sense"]))

    picked = _diversify_cross_sense(
        scored, primary_senses={"github"},
        limit=MAX_CROSS_SENSE, reserved=CROSS_SENSE_RESERVED,
    )
    assert len(picked) == MAX_CROSS_SENSE
    senses = []
    from twin.cognize.services import sense_lenses
    for rec, _s, _a in picked:
        senses.append(sense_lenses.sense_for_record(rec))
    assert senses.count("slack") >= 2
    assert "sl1" in {r.id for r, _, _ in picked}
