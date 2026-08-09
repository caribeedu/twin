# Epistemics

This document owns provenance, freshness, independence, contradictions,
ACL inheritance on derived claims, tombstones, and **read-time confidence**.

Architecture walls: [ARCHITECTURE.md](ARCHITECTURE.md).  
Cognize stages: [COGNIZE.md](COGNIZE.md).  
Design source: [v2.md](v2.md) §§2.3, 3.4, 6.  
Vocabulary: [GLOSSARY.md](GLOSSARY.md).

Normative detail: [v2.md](v2.md) §§2.3, 3.4, 6.

---

## EpistemicState (on Narratives)

| Field | Meaning |
|---|---|
| `synthesized_at` | When Cognize last formed / revised this account |
| `freshness_boundary` | Timestamp of newest Evidence included in synthesis |
| `unseen_since` | Percept ids / cursors after the boundary that overlap the Narrative’s domain |
| `status` | `fresh` \| `stale` \| `superseded` \| `tombstoned` |
| `stale_reason` | e.g. new observation in domain after synthesis |
| `evidence_ids` | Full provenance set, including dissent |
| `independence_sketch` | Optional last LLM sketch — informative, not confidence SoT |

**Do not store an incrementable `confidence` float** on Narrative /
Reflection. Derive confidence at read / Inject / Review time from
evidence_ids + independence / `same_originating_decision` Relations +
supports vs contradicts + freshness.

---

## Stale mark timing

```text
Percept lands in a covered domain
  → deterministic mark Narrative status=stale + stale_reason   ← BEFORE Cognize finishes
  → Inject refuses stale-as-fresh immediately
  → Cognize (when LLM up) re-synthesizes / revises meaning
```

The deterministic gate is a **safety latch**, not cognition.

---

## Independence and dissent

- Prefer disagreement over counting agreeing channels that share one
  upstream decision (`same_originating_decision`).
- When Narrative Revision prefers one side, **retain** losing
  Interpretation / Evidence (attached, lower weight) — never discard.
- Inject should surface e.g. `5 observations, 1 independent origin` rather
  than four echoes as four votes.

---

## ACL intersection and revoke

- A Narrative’s visibility ≤ **intersection** of ACLs of contributing
  sources.
- Revoke / delete of a source → **synchronous tombstone** (or recompute)
  of dependents — no silent leftover truth.
- Aligns with Domain Firewall; Cognize must not expand permission beyond
  inputs.

---

## Inject floor + ceiling

1. **Floor:** never present a stale Narrative as current without
   `EpistemicState.status=stale` (+ reason), or withhold it.
2. **Ceiling:** expose enough EpistemicState for the host to proceed,
   trigger re-synthesis, or refuse.
3. **Provenance:** every served claim traces to Evidence.
4. If Cognize never ran, do not invent pack content with heuristics.

---

## Source-class asymmetry

Every Percept carries a durable `source_class` (`code_repo`,
`chat_discussion`, `meeting`, `mail`, `calendar`, `document`,
`session_residue`, `unknown`). Connectors map via `source_sensor`;
missing class defaults to `unknown`.

Policy sketch (enables later quiet-reversal / fade work):

| Class | Lifetime hint |
|---|---|
| `code_repo` | Often self-invalidates when tree changes |
| `chat_discussion` / `meeting` | May reverse quietly with little follow-up |
| `session_residue` | Host-session absorb; not Cognize talking to host |

Read-time confidence never trusts a stored scalar — packs emit
`derived_confidence` with `derived: true`, independence display, and
optional supports/contradicts + retained dissent.

ACL: Narrative `sensitivity` is the ∩ (strictest) of contributing
Evidence confidentiality; `metadata.source_sensors` records origins.
Revoke/delete of a source Percept synchronously tombstones dependent
Narratives (`twin.cognize.acl.tombstone_narratives_for_percept`) and
appends a Trace. Inject Observer is a reserved Inject LLM slot
(`twin.cognition.inject_observer`); default stub must not write Cognize
entities.
