# Epistemics

This document owns provenance, freshness, independence, contradictions,
ACL inheritance on derived claims, tombstones, and **read-time confidence**.

Architecture walls: [ARCHITECTURE.md](ARCHITECTURE.md).  
Cognize stages: [COGNIZE.md](COGNIZE.md).  
Vocabulary: [GLOSSARY.md](GLOSSARY.md).  
Historical journal: [v2.md](v2.md) §§2.3, 3.4, 6.

Implementation: `twin/cognize/models.py` (derive helpers),
`twin/cognize/acl.py`, `twin/cognize/stale.py`, pack assembly in
`twin/cognition/context_pack.py`.

---

## EpistemicState (on Narratives)

| Field | Meaning |
|---|---|
| `synthesized_at` | When Cognize last formed / revised this account |
| `freshness_boundary` | Timestamp of newest Evidence included in synthesis |
| `unseen_since` | Percept ids after the boundary that overlap the Narrative’s domain |
| `status` | `fresh` \| `stale` \| `superseded` \| `tombstoned` |
| `stale_reason` | e.g. new observation in domain after synthesis |
| `evidence_ids` | Full provenance set, including dissent |
| `independence_sketch` | Optional last LLM sketch — informative, not confidence SoT |

**Do not store an incrementable `confidence` float** on Narrative /
Reflection. Derive confidence at read / Inject / Review time from
evidence_ids + independence / `same_originating_decision` Relations +
supports vs contradicts + freshness.

Pack field: `derived_confidence[narrative_id]` always includes
`"derived": true`.

---

## Stale mark timing

```text
Percept lands in a covered domain
  → deterministic mark Narrative status=stale + stale_reason   ← BEFORE Cognize finishes
  → Inject refuses stale-as-fresh immediately
  → Cognize (when LLM up) re-synthesizes / revises meaning
```

The deterministic gate is a **safety latch**, not cognition
(`twin/cognize/stale.py` on percept insert).

---

## Independence and dissent

- Prefer disagreement over counting agreeing channels that share one
  upstream decision (`same_originating_decision`).
- When Narrative Revision prefers one side, **retain** losing
  Interpretation / Evidence (attached, lower weight) — never discard.
- Inject surfaces e.g. `5 observations, 1 independent origin` rather
  than four echoes as four votes (`collapse_independent_origins`,
  `derive_confidence`).
- Pack scopes SOD Relations to the Narrative’s evidence set.

Eval: `tests/evals/test_independence_collapse.py`.

---

## ACL intersection and revoke

- Narrative `sensitivity` = ∩ (strictest) of contributing Evidence /
  Percept `source_confidentiality`.
- Commit refuses sensitivity that expands beyond the evidence floor.
- `metadata.source_sensors` records contributing sensors; pack may deny
  when AccessRequest `allowed_source_sensors` does not cover them.
- Revoke / delete of a source Percept → **synchronous tombstone** of
  dependent Narratives (`tombstone_narratives_for_percept`) + Trace
  (`event_kind=tombstone`) inside the same delete transaction
  (`twin/memory/retention.py`, `twin/privacy/deletion.py`).

Eval: `tests/evals/test_acl_intersection.py`.

---

## Source-class asymmetry

Every Percept carries durable `source_class`
(`code_repo`, `chat_discussion`, `meeting`, `mail`, `calendar`,
`document`, `session_residue`, `unknown`). Inferred from `source_sensor`
/ `percept_type` on write; persisted in store.

| Class | Lifetime hint |
|---|---|
| `code_repo` | Often self-invalidates when tree changes |
| `chat_discussion` / `meeting` | May reverse quietly with little follow-up |
| `session_residue` | Host-session absorb; not Cognize talking to host |

Enables quiet-reversal / fade policy; does not by itself delete.

---

## Inject floor + ceiling

1. **Floor:** never present a stale Narrative as current without
   `EpistemicState.status=stale` (+ reason), or withhold the account.
2. **Ceiling:** expose enough EpistemicState for the host to proceed,
   trigger re-synthesis, or refuse.
3. **Provenance:** every served claim traces to Evidence.
4. If Cognize never ran, do not invent pack content with heuristics.
5. Open Reflections appear in an uncertainty section when ACL/domain
   allow; restricted reflections are blocked with reasons, not content.
6. Inject Observer (`twin.cognition.inject_observer`) is a reserved slot;
   default stub must not write Cognize entities (`TWIN_INJECT_OBSERVER`).

---

## Trace + accessibility

Pack serve appends Trace `pack_serve` per Narrative.
Fade / Remarkable recommendations live on
`Narrative.metadata.accessibility_recommendation` and are visible via
`twin narrative accessibility`, Review workbench reflections panel, and
Command Center Review screen. Age-only deletion of Narratives is **not**
Cognize policy.
