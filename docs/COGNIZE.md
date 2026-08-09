# Cognize

This document owns the **Cognize pipeline** — staged formation and revision
of Narratives. It is **not** the public architecture diagram.

Public walls: [ARCHITECTURE.md](ARCHITECTURE.md) (Sense → Cognize → Inject).  
Epistemics: [EPISTEMICS.md](EPISTEMICS.md).  
Vocabulary: [GLOSSARY.md](GLOSSARY.md).  
Historical redesign journal: [v2.md](v2.md).  
Implementation inventory: [v2-tracker.md](v2-tracker.md).

---

## Hard rules

1. Every **thinking** stage requires a live chat LLM (or an explicit test
   override). Missing model → **halt** — no invented Reflections,
   Interpretations, Relations, or Narrative Revision.
2. Humans gate durability: **Commit Narrative** and **approve Stance** are
   never automatic.
3. Do not store an incrementable confidence float on Narrative / Reflection.
4. Cognize must not expand ACL / sensitivity beyond contributing Evidence.

Modules: `twin/cognize/orchestrator.py` (stages 0–7), `twin/cognize/commit.py`
(stage 9), `twin/cognize/stages_late.py` (stages 10–12), store mixin
`twin/memory/store/cognize_mixin.py`.

---

## Stage map

| # | Stage | Question | Primary writes | Engine |
|---|---|---|---|---|
| 0 | Salience gate | Worth cognitive work now? | salience / drop / defer | LLM |
| 1 | Situate | Which Situation cluster? | Situation membership | LLM |
| 2 | Raise Reflections | What is still unknown? | Reflection | LLM |
| 3 | Form Interpretations | Candidate explanations? | Interpretation | LLM |
| 4 | Cross Reflections | Same / related / conflicting asks? | Reflection↔Reflection Relation | LLM |
| 5 | Cross Interpretations | Support / contradict / same claim? | Interpretation↔Interpretation Relation | LLM |
| 6 | Narrative Revision | How should new interpretations change the account? | revision decisions + retain dissent + `surprise` / `explanatory_delta` | LLM |
| 7 | Evidence audit | What warrants each Interpretation? Independence? | Evidence links, `same_originating_decision` | LLM |
| 8 | Human review | What may become durable? | review decisions | Human |
| 9 | Commit Narrative | Apply human accept | Narrative + EpistemicState | Persist only |
| 10 | Stance drafts | How evaluate similar cases later? | pending Stance proposal | LLM when reachable; else pending twin-influenced draft via `propose_from_narrative` — **never auto-approve** |
| 11 | Consolidation judgment | Generalize vs stay episodic? | pending drafts / tags | LLM (`run_consolidation_judgment`); halt if no chat LLM; caps on drafts/tokens |
| 12 | Fade / Remarkable | What stays accessible? | accessibility recommendations on Narrative metadata | LLM preferred; Trace-heuristic hints only when halted — **never delete** |

Overrides for CI: `set_cognize_stage_override` (0–7) and
`set_late_stage_override` (`stance_draft`, `consolidation_judgment`,
`fade_judgment`).

---

## Entity I/O (contracts)

| Entity | Meaning | Key fields |
|---|---|---|
| **Situation** | Working cluster of percepts | `percept_ids`, `summary`, `vault_id` |
| **Reflection** | Open epistemic gap | `text`, `status=open\|resolved\|…`, `evidence_ids` |
| **Interpretation** | Competing candidate explanation | `explanation`, `status=competing\|committed\|…` |
| **Relation** | Typed Cognize edge | `same_originating_decision` requires LLM or `asserted_by=test` |
| **Narrative** | Durable account | `account`, `evidence_ids`, `sensitivity`, `epistemic_state_id` |
| **EpistemicState** | Freshness SoT | `fresh` / `stale` / `superseded` / `tombstoned` — no confidence float |
| **EvidenceAnchor** | Span warranting claim | `percept_id`, `quote`, `target_kind` |
| **Trace** | Append-only use event | `pack_serve`, `fade_recommend`, `tombstone`, … |
| **NarrativeRevisionDecision** | Stage 6 output | `outcome`, `surprise`, `explanatory_delta` |
| **Stance** | Alias over Judgment | pending until human approve |

---

## Narrative Revision (stage 6)

Outcomes: `integrate` · `branch` · `contradict` · `supersede` ·
`keep_separate` · `defer`.

Always retain dissent Interpretations / Evidence when preferring one side.
Research fields `surprise` + `explanatory_delta` persist for analysis
(`twin research revisions`) and must not drive Inject floor.

---

## Commit Narrative (stage 9)

`commit_narrative` requires human `committed_by`, non-empty `evidence_ids`,
and optional `preview_token` fingerprint. Sensitivity is ∩ of evidence
confidentiality (refuse expansion). After commit, Stage 10 may enqueue a
pending Stance draft.

CLI: `twin narrative commit-preview` → `twin narrative commit --token …`  
REST: `POST /api/narratives/commit-preview` → `POST /api/narratives/commit`  
Workbench: `#narratives` panel.

---

## Migration ADR — MemoryItem → Narrative / Interpretation

**Rule (dual-read):** confirmed memories map to provisional **Narratives**;
candidates (and any `needs_review` rows) map to competing **Interpretations**.

| Prior row | Cognize | Notes |
|---|---|---|
| `MemoryStatus.confirmed` | `Narrative` + `EpistemicState` | `migrated_from_memory=true` |
| `MemoryStatus.candidate` | `Interpretation` (`competing`) | Never auto-commit |
| `needs_review=true` | `Interpretation` only | Even if status looks confirmed |
| Judgment items | Stance | Store tables unchanged |

CLI: `twin narrative backfill` (`--apply` idempotent on `metadata.memory_id`).
