# Twin v2 Tracker — implementable task inventory

Working tracker for the redesign in [`docs/v2.md`](./v2.md).  
Audience: an implementer (human or LLM) **with no prior chat context**. Every task is sized so another agent can pick it up, implement, and verify without guessing product intent.

**Source of truth for product intent:** `docs/v2.md`  
**Source of truth for current shipped behavior:** `docs/CHANGELOG.md`, `docs/ARCHITECTURE.md`, code under `twin/`  
**This file does not redefine the redesign** — it decomposes it into tasks.

---

## How to use this document

1. Read `docs/v2.md` §§0−, 0, 1, 2, 6, 11, 12 before starting any task.
2. Pick the next task whose **Depends on** are all `done`.
3. Do not invent entities, CLI verbs, or fallback cognition paths that contradict the invariants below.
4. Prefer small PRs: one task (or a tightly coupled pair) per PR when possible.
5. Mark status in the task header: `todo` | `in_progress` | `blocked` | `done` | `wontfix`.

### Status legend

| Status | Meaning |
|---|---|
| `todo` | Not started |
| `in_progress` | Actively being implemented |
| `blocked` | Waiting on dependency or open decision |
| `done` | Exit criteria met and QA listed here is green |
| `wontfix` | Explicitly deferred with rationale linking to `v2.md` §10 |

---

## Non-negotiable invariants (every task must preserve)

Copy these into PR descriptions. Violating any of them fails the task regardless of “green tests.”

1. **LLM-or-halt for Cognize.** No heuristic / echo / lexical / regex path may raise Reflections, form Interpretations, assert Relations, run Narrative Revision, Evidence audit, Stance drafts, or Fade/Remarkable *judgment*. If chat LLM is unavailable → Cognize hard-stops with an explicit halt reason; Sense I/O and Domain Firewall may still run.
2. **Three hard modules only:** Sense (deterministic I/O) → Cognize (LLM brain) → Inject (firewall + pack + Observer slot). Host conversation is **not** a fourth module or product “mode.”
3. **No product “memory”.** User-facing / CLI / MCP / Review / docs that define the product use Reflection, Interpretation, Narrative, Stance, Evidence, Situation. `Memory*` / `twin memory` survive only as deprecated aliases during migration.
4. **Understanding is emergent**, not a schema root / table.
5. **Human gates durability.** Stages 8–9: humans commit Narratives; Cognize proposes. No `extract -A`-style silent Narrative commit.
6. **Stale before Cognize finishes.** When a relevant Percept lands, mark overlapping Narratives `stale` **deterministically** before re-synthesis, so Inject never serves stale-as-fresh.
7. **Confidence is read-time**, never an incrementable stored scalar on Narrative/Reflection.
8. **Retain dissent.** Superseded Interpretations/Evidence stay attached; later corroboration can revive them.
9. **ACL intersection on derived claims.** Narrative visibility ≤ ∩ of contributing source ACLs; revoke → synchronous tombstone of dependents.
10. **Public architecture stays Sense → Cognize → Inject.** Cognize pipeline stages belong in Cognize docs, not the README architecture diagram.

---

## Phase map (recommended order)

```text
P0  Docs lock + vocabulary + architecture wording
P1  Schema / store / migrations (entities + EpistemicState)
P2  Kill offline cognition paths (LLM-or-halt gate)
P3  Cognize stages 0–7 (LLM pipeline through Evidence audit)
P4  Human review + Commit Narrative (stages 8–9)
P5  Stance + Consolidation + Fade (stages 10–12)
P6  Sense: stale-on-percept + source-class metadata
P7  Inject: EpistemicState, stale floor, independence display, ACL fan-out
P8  CLI verb retarget (cognize / narrative / stance) + handler extraction
P9  Command Center TUI
P10 MCP / REST / Review UI / Native pack surfaces
P11 Experiments + evals (§9.3 priority)
P12 Doc split (ARCHITECTURE / COGNIZE / EPISTEMICS / RESEARCH) + README trim
```

Phases P3–P5 can overlap with P6–P7 once P1–P2 are done, but Inject must not claim “fresh Narratives” until P1+P6 exist.

---

## Task index

| ID | Phase | Title | Status |
|---|---|---|---|
| T-000 | P0 | Lock vocabulary glossary + deprecate “memory” in product copy | todo |
| T-001 | P0 | Rewrite ARCHITECTURE overview to Sense → Cognize → Inject walls | todo |
| T-002 | P0 | Add stub COGNIZE.md / EPISTEMICS.md pointing at v2.md until split | todo |
| T-010 | P1 | Define pydantic/dataclass contracts for v2 entities | todo |
| T-011 | P1 | Store schema migration: tables/columns for v2 entities | todo |
| T-012 | P1 | EpistemicState model without stored confidence scalar | todo |
| T-013 | P1 | Relation types including `same_originating_decision` | todo |
| T-014 | P1 | Migration plan MemoryItem → Narrative/Interpretation dual-read | todo |
| T-015 | P1 | Judgment → Stance rename in store (alias layer) | todo |
| T-020 | P2 | Cognize availability gate (`require_chat_llm`) | todo |
| T-021 | P2 | Remove/disable heuristic meaning as production cognition | todo |
| T-022 | P2 | Remove echo-as-production meaning path | todo |
| T-023 | P2 | Episode pipeline: delete lexical semantic fallbacks; halt instead | todo |
| T-030 | P3 | Cognize orchestrator skeleton + stage report | todo |
| T-031 | P3 | Stage 0 Salience (LLM) | todo |
| T-032 | P3 | Stage 1 Situate (LLM) | todo |
| T-033 | P3 | Stage 2 Raise Reflections (LLM) | todo |
| T-034 | P3 | Stage 3 Form Interpretations (LLM) | todo |
| T-035 | P3 | Stage 4 Cross Reflections (LLM) | todo |
| T-036 | P3 | Stage 5 Cross Interpretations (LLM) | todo |
| T-037 | P3 | Stage 6 Narrative Revision (LLM) + retain dissent | todo |
| T-038 | P3 | Stage 7 Evidence audit + independence Relations | todo |
| T-040 | P4 | Review queue for Interpretations + always-visible Open Reflections | todo |
| T-041 | P4 | Stage 9 Commit Narrative + initial EpistemicState | todo |
| T-050 | P5 | Stage 10 Stance drafts (LLM) + human approve path | todo |
| T-051 | P5 | Stage 11 Consolidation judgment (nightly LLM, caps) | todo |
| T-052 | P5 | Stage 12 Fade / Remarkable + Trace ledger | todo |
| T-060 | P6 | Deterministic stale mark on percept land | todo |
| T-061 | P6 | Source-class + timestamp metadata for invalidation asymmetry | todo |
| T-070 | P7 | Inject pack: attach EpistemicState; refuse stale-as-fresh | todo |
| T-071 | P7 | Read-time confidence + independence display in packs | todo |
| T-072 | P7 | Open Reflections section in packs | todo |
| T-073 | P7 | ACL intersection on Narrative + synchronous revoke tombstone | todo |
| T-074 | P7 | Inject Observer slot (interface reserved, stub OK) | todo |
| T-080 | P8 | Extract CLI handlers to `twin/interfaces/commands/` | todo |
| T-081 | P8 | Introduce `twin cognize` / `narrative` / `stance` / `inject pack` | todo |
| T-082 | P8 | Deprecate aliases: extract, meditate, correlate, judgment, memory | todo |
| T-090 | P9 | Command Center MVP: bare `twin` TUI Home + Services + palette | todo |
| T-091 | P9 | Center: Connectors + Jobs screens | todo |
| T-092 | P9 | Center: Cognize / Review / Narratives / Stance / MCP screens | todo |
| T-100 | P10 | MCP tool rename + pack EpistemicState fields | todo |
| T-101 | P10 | REST / Review workbench Narrative commit UX | todo |
| T-102 | P10 | Native pack injection uses v2 pack contract | todo |
| T-110 | P11 | Eval: stale injection (§9.3 #1) | todo |
| T-111 | P11 | Eval: correlated-source independence collapse (§9.3 #3) | todo |
| T-112 | P11 | Eval: disagreement vs agreement attention (§9.3 #4) | todo |
| T-113 | P11 | Eval: quiet reversal path (§9.3 #2) | todo |
| T-114 | P11 | Eval: ACL intersection (§9.3 #5) | todo |
| T-115 | P11 | Research logging: surprise / explanatory_delta (§9.3 #7) | todo |
| T-120 | P12 | Split docs: ARCHITECTURE / COGNIZE / EPISTEMICS / RESEARCH | todo |
| T-121 | P12 | README stays architecture-layer only; add COMMAND_CENTER.md | todo |

---

# Tasks

---

## T-000 — Lock vocabulary glossary + deprecate “memory” in product copy

**Phase:** P0 · **Status:** `todo`  
**Depends on:** none  
**Blocks:** T-001, T-010, T-081, T-100

### Description

Update `docs/GLOSSARY.md` and `docs/COGNITION.md` so the v2 entity names are canonical:

- Add entries: **Situation**, **Reflection**, **Interpretation**, **Relation**, **Narrative**, **EpistemicState**, **Stance**, **Evidence**, **Trace**, **Sense**, **Cognize**, **Inject**.
- Redefine **Understanding** as *emergent* (Narratives + Relations + EpistemicStates + Stances + Open Reflections + Evidence) — **not** a stored type.
- Mark **Memory** / **Judgment** as legacy synonyms: Memory ≈ committed Narrative + related durable claims (deprecated product term); Judgment → Stance.
- Do **not** rewrite the entire README yet (that is T-001 / T-121). Do update any glossary cross-links that still say “Memory is the unit of value.”
- Align wording with `docs/v2.md` §0− and §2.2: Twin is a **longitudinal narrative** architecture, not a memory product / GBrain clone.

### Exit criteria

- [ ] `GLOSSARY.md` contains every entity in `v2.md` §2.2 table with lifecycle one-liners matching the redesign.
- [ ] `COGNITION.md` explains Understanding as emergent and points Situation Model → Situation + Narrative (WorkEpisode called out as legacy carrier).
- [ ] No new doc introduced in this task uses “memory” as a product noun in headings or CLI examples (academic citations in FOUNDATIONS/RESEARCH may still say “memory”).
- [ ] A one-paragraph “Migration note” in GLOSSARY lists deprecated terms → replacements.

### Assumptions

- `docs/v2.md` remains authoritative; this task only mirrors settled naming.
- Existing code still uses `MemoryItem` — docs may say “code still uses Memory* until T-014.”
- IDENTITY.md unit-of-value text may still say “understanding”; leave it unless it contradicts Narrative as durable product unit — if conflict, prefer v2 §0− and note the IDENTITY update in T-121.

### Expected QA

- Manual doc review: another reader can answer “What is a Narrative vs Interpretation vs Reflection?” from GLOSSARY alone.
- Grep `docs/*.md` for `` `twin memory` `` and product headings titled “Memory” — either removed or marked deprecated.
- Link check: new glossary anchors resolve from COGNITION.md.

### Resources

- `docs/v2.md` §§0−, 2.2, 2.4
- `docs/GLOSSARY.md`, `docs/COGNITION.md`, `docs/IDENTITY.md`
- Current runtime carrier note: `WorkEpisode` in `docs/ARCHITECTURE.md` § Brain analogies

---

## T-001 — Rewrite ARCHITECTURE overview to Sense → Cognize → Inject walls

**Phase:** P0 · **Status:** `todo`  
**Depends on:** T-000  
**Blocks:** T-002, T-120

### Description

Rewrite the **top of** `docs/ARCHITECTURE.md` so the public architecture is only:

```text
Sense → Cognize → Inject
```

with the hard-wall table from `v2.md` §1 (owns / must not).

Keep existing brain-stage / episode pipeline detail either:

- moved under a clearly labeled **“Legacy Cognize pipeline (pre-v2)”** section, or
- replaced by a short pointer: “Internal Cognize stages live in `docs/COGNIZE.md` / `docs/v2.md` §2 — not in the architecture diagram.”

Do **not** expand the public diagram into Salience→…→Fade (that violates the architecture vs pipeline rule).

Update sequence diagrams that currently say “extract → meditate → pack” to Sense → Cognize → Inject naming, noting legacy CLI aliases until P8.

### Exit criteria

- [ ] Opening architecture diagram / mermaid shows exactly three modules.
- [ ] Hard-wall table present (Sense / Cognize / Inject owns / must not).
- [ ] No README-bound architecture language lists Cognize stages as peer modules.
- [ ] Threat-model and firewall sections still present and consistent with fail-closed Inject firewall + Cognize LLM-or-halt.
- [ ] Cross-links to `v2.md` for pipeline detail.

### Assumptions

- Full Cognize stage docs are stubbed in T-002 or still live only in `v2.md`.
- Code still implements the old pipeline; architecture docs describe *target* walls and label current episode stages as transitional.

### Expected QA

- Compare against `v2.md` §0− “Architecture vs pipeline” boxes — wording matches.
- Someone reading only ARCHITECTURE.md cannot mistake Stage 6 Narrative Revision for a fourth top-level module.
- Existing links from README / OPERATIONS still resolve (update anchors if headings change).

### Resources

- `docs/v2.md` §§0−, 1, 6
- `docs/ARCHITECTURE.md` (current)
- `README.md` § Direction / Runtime Philosophy (do not dump stages into README — T-121)

---

## T-002 — Add stub COGNIZE.md / EPISTEMICS.md pointing at v2.md

**Phase:** P0 · **Status:** `todo`  
**Depends on:** T-001  
**Blocks:** T-120

### Description

Create:

- `docs/COGNIZE.md` — stub: stage map table from `v2.md` §2.1, entity list, “implementation tracked in v2-tracker”; link to `v2.md` §2 for full contracts until code lands.
- `docs/EPISTEMICS.md` — stub: EpistemicState fields, stale timing, read-time confidence, independence, ACL intersection, retain dissent — all from `v2.md` §§2.3, 3.4, 6.

Do **not** duplicate the entire academic §5 into RESEARCH yet (T-120). Add a short “See also RESEARCH.md / v2.md §5” pointer.

Update `docs/RESEARCH.md` with a “v2 redesign hypotheses” subsection listing the falsifiable claims that experiments in P11 will test (stale floor, independence collapse, quiet reversal, disagreement attention) without claiming they are proven.

### Exit criteria

- [ ] Both new files exist and are linked from ARCHITECTURE.md and the docs table in README (or OPERATIONS index).
- [ ] Stubs do not invent schemas beyond `v2.md`.
- [ ] RESEARCH.md lists experiment IDs matching T-110–T-115.

### Assumptions

- Full prose migration from `v2.md` into these files happens in T-120; stubs prevent link rot while engineering proceeds.

### Expected QA

- Dead-link check from ARCHITECTURE → COGNIZE / EPISTEMICS.
- Stub length stays under ~200 lines each (pointers, not a second redesign).

### Resources

- `docs/v2.md` §§2, 3.4, 5, 6, 9.3, 10
- `docs/RESEARCH.md`

---

## T-010 — Define pydantic/dataclass contracts for v2 entities

**Phase:** P1 · **Status:** `todo`  
**Depends on:** T-000  
**Blocks:** T-011, T-012, T-013, T-030

### Description

Create a new module (suggested: `twin/cognition/v2_models.py` or `twin/cognize/models.py`) defining typed contracts for:

| Type | Required fields (minimum) |
|---|---|
| `Situation` | id, vault_id, membership percept ids, status (`working`\|`concluded`), timestamps |
| `Reflection` | id, text/question, status (`open`\|`answered`\|`superseded`\|`faded`), situation_ids, evidence refs |
| `Interpretation` | id, explanation text, reflection_ids / situation_ids, status (`competing`\|`rejected`\|`merged`\|`superseded`\|`committed`), evidence_ids |
| `Relation` | id, from_id, to_id, type (enum below), rationale, asserted_by (`llm`), model/prompt versions |
| `Narrative` | id, account text, grain optional (`episode`\|`arc`\|`domain`), evidence_ids, epistemic_state_id, status, vault/domain/persona/sensitivity |
| `EpistemicState` | see T-012 (imported/composed here) |
| `Stance` | mirror JudgmentItem taxonomy but named Stance; pending→approved→active/deprecated |
| `Evidence` | anchored percept span, source id, timestamp, ACL tags |
| `Trace` | append-only retrieval/use events |
| `NarrativeRevisionDecision` | exact schema from `v2.md` §10 decision 2 |

Relation type enum **must** include: `same-as`, `related`, `supports`, `contradicts`, `depends-on`, `supersedes`, `part-of`, `continues`, **`same_originating_decision`**.

**Forbidden:** a root `Understanding` model; a stored `confidence: float` on Narrative/Reflection that stages increment.

Provide JSON-schema export or pydantic `.model_json_schema()` used by LLM stage prompts later.

### Exit criteria

- [ ] Types importable; unit tests construct valid and reject invalid Relation types.
- [ ] `NarrativeRevisionDecision.outcome` enum matches `integrate \| branch \| contradict \| supersede \| keep_separate \| defer`.
- [ ] Docstrings cite `docs/v2.md` §2.2 / §10.
- [ ] No `MemoryItem` subclass pretending to be Narrative without an explicit `LegacyMemoryAdapter` name.

### Assumptions

- Persistence is T-011; this task is contracts only.
- WorkEpisode / MemoryItem remain until dual-read migration (T-014).

### Expected QA

- `pytest` on new model tests (round-trip dict ↔ model).
- Static check: grep new module for `confidence:` fields on Narrative/Reflection — must be absent (derived helpers may live elsewhere as functions).

### Resources

- `docs/v2.md` §§2.2, 2.3, 2.4, 10 (Stage 6 schema)
- Existing models for patterns: `twin/memory/models.py`, `twin/judgment/models.py`, `twin/cognition/correlation/models.py`, `twin/cognition/interpreter/schema.py`

---

## T-011 — Store schema migration: tables/columns for v2 entities

**Phase:** P1 · **Status:** `todo`  
**Depends on:** T-010  
**Blocks:** T-014, T-030, T-040, T-060

### Description

Extend `MemoryStore` (SQLite + Postgres paths) with durable tables/collections for Situations, Reflections, Interpretations, Relations, Narratives, EpistemicStates, Evidence attachments, Traces.

Requirements:

1. Vault partition on every row that clusters cognition (`vault_id`) — same isolation rule as correlation today (`twin/cognition/correlation/partition.py`).
2. Idempotent upserts keyed by stable ids (`twin/ids.py` style prefixes, e.g. `nar_`, `ref_`, `intp_`, `rel_`, `sit_`, `eps_`).
3. Migrations must be reversible or at least forward-safe on both SQLite and Postgres backends (`twin/memory/store/base.py`, `postgres.py`).
4. Export/backup (`twin/sovereignty/`) must include new tables once written — update manifest list.
5. Do **not** drop `memories` table yet — dual-read in T-014.

Implement store mixins analogous to existing `correlation_mixin.py` / `judgment_mixin.py`.

### Exit criteria

- [ ] CRUD round-trips on SQLite and Postgres CI jobs.
- [ ] Vault isolation test: writing Relation/Narrative in vault A is invisible when querying as vault B without cross-domain flag.
- [ ] `twin backup create` / export includes new entities (or explicitly documents “empty until first cognize”).
- [ ] Schema version bump recorded where the project tracks migrations.

### Assumptions

- Postgres remains primary; SQLite zero-config still required.
- Encryption-at-rest (`TWIN_ENCRYPTION_KEY`) should encrypt narrative/interpretation bodies if raw memory content is encrypted today — match existing crypto boundaries.

### Expected QA

- Port tests from `tests/cognition/correlation/` patterns: lifecycle, isolation, idempotency.
- New `tests/cognize/test_store_entities.py` (name flexible) covering insert/list/update status transitions.
- Run existing store suites to ensure no regression on memories/judgment tables.

### Resources

- `twin/memory/store/base.py`, `postgres.py`, mixins under `twin/memory/store/`
- `twin/sovereignty/export.py`, `manifest.py`
- `docs/v2.md` §2.2
- `docs/ARCHITECTURE.md` § Data model (legacy Memory Item — do not reintroduce as canonical)

---

## T-012 — EpistemicState model without stored confidence scalar

**Phase:** P1 · **Status:** `todo`  
**Depends on:** T-010  
**Blocks:** T-041, T-060, T-070, T-071

### Description

Implement `EpistemicState` persistence and API matching `v2.md` §2.3:

| Field | Notes |
|---|---|
| `synthesized_at` | datetime |
| `freshness_boundary` | newest Evidence timestamp included in last synthesis |
| `unseen_since` | list/cursor of percept ids after boundary overlapping domain |
| `status` | `fresh` \| `stale` \| `superseded` \| `tombstoned` |
| `stale_reason` | string |
| `evidence_ids` | full set including dissent |
| `independence_sketch` | optional last LLM sketch — **informative only** |

Implement **read-time** helpers (pure functions):

```text
derive_confidence(evidence_ids, relations, supports/contradicts, freshness) -> display struct
derive_independence_summary(relations) -> e.g. "5 observations, 1 independent origin"
```

These helpers must **not** write a confidence float back onto the Narrative row.

### Exit criteria

- [ ] Cannot persist Narrative EpistemicState with a required `confidence` column (schema review).
- [ ] Unit tests: adding a `same_originating_decision` edge among four agreeing sources does **not** increase derived independent-origin count.
- [ ] Marking `status=stale` with reason is a deterministic store update (no LLM).

### Assumptions

- Stage 7 may refresh `independence_sketch`; Inject always recomputes display via helpers (T-071).

### Expected QA

- Table-driven tests for independence collapse and dissent retention (evidence_ids still contain loser ids after supersede — when Commit exists; until then test helper contracts with fixtures).

### Resources

- `docs/v2.md` §§2.3, 3.4, 6
- `docs/EPISTEMICS.md` (stub from T-002)

---

## T-013 — Relation types including `same_originating_decision`

**Phase:** P1 · **Status:** `todo`  
**Depends on:** T-010, T-011  
**Blocks:** T-035, T-036, T-037, T-038, T-071

### Description

Persist Relations with LLM provenance metadata (model id, prompt/schema version, rationale). Special-case documentation and validation for **`same_originating_decision`**:

- It is a **causal** Relation, not similarity.
- Cheap pre-hints allowed (shared time window + actors/artifacts/tokens) but **final assertion requires LLM stage** when Cognize runs (Stage 7).
- Embeddings alone must not create causal Relations.

Provide query helpers: neighbors by type, collapse independent-origin sets for Inject display.

### Exit criteria

- [ ] Enum rejects unknown types.
- [ ] Test: creating `same_originating_decision` without `asserted_by=llm` fails closed in production API (tests may inject with explicit test flag / override similar to `set_stage_override` today).
- [ ] Narrative↔Narrative `part-of` / `continues` / `supersedes` supported for composition (`v2.md` §2.4).

### Assumptions

- Cross stages (T-035/T-036) write most Relations; this task is storage + validation.

### Expected QA

- `tests/cognize/test_relations.py`
- Negative test: similarity score path cannot insert `same_originating_decision`.

### Resources

- `docs/v2.md` §§2.2, 2.3, 2.4, 3.1, 3.4
- Pattern: episode edges confirm/reject in correlation persistence

---

## T-014 — Migration plan MemoryItem → Narrative/Interpretation dual-read

**Phase:** P1 · **Status:** `todo`  
**Depends on:** T-011, T-012  
**Blocks:** T-040, T-081, T-100

### Description

Ship an explicit dual-read adapter so existing confirmed `MemoryItem`s remain usable while Cognize writes Narratives:

1. Document mapping:
   - confirmed Memory (decision/event/fact…) → provisional **Narrative** or **Interpretation** (choose one rule and stick to it; recommended: confirmed memories become Narratives with EpistemicState `freshness_boundary=valid_from`, flagged `migrated_from_memory=true`; candidates become Interpretations `competing`).
2. Pack/search code paths can read both during migration.
3. Write path for new cognition goes to v2 entities only once Cognize pipeline is on (P3+).
4. Provide `twin narrative backfill-from-memories --dry-run|--apply` (or store method) — **does not** invent new meaning; copies existing confirmed claims.
5. Deprecation warnings when APIs return Memory-shaped payloads.

Do **not** delete memory tables in this task.

### Exit criteria

- [ ] Written ADR/section in `docs/COGNIZE.md` or tracker note describing the mapping 1:1.
- [ ] Dual-read pack fixture: old DB with only memories still produces a pack (legacy) OR empty Narratives with clear “migration required” — pick one behavior and test it; prefer dual-read so v1 users do not brick.
- [ ] `--dry-run` backfill prints counts; `--apply` is idempotent.

### Assumptions

- Judgment→Stance handled in T-015.
- Auto-confirm paths remain forbidden.

### Expected QA

- Integration test on a golden SQLite fixture from current evals (`evals/v1` / golden work loop) after backfill.
- Ensure `needs_review` candidates never become committed Narratives via backfill.

### Resources

- `twin/memory/models.py`, `twin/memory/formation.py`
- `twin/cognition/context_pack.py`
- `docs/v2.md` §2.2 “Do not use memory as a product term”
- `docs/CHANGELOG.md` v1.x memory semantics

---

## T-015 — Judgment → Stance rename in store (alias layer)

**Phase:** P1 · **Status:** `todo`  
**Depends on:** T-010  
**Blocks:** T-050, T-082

### Description

Introduce Stance as the public name for Judgment:

1. Type aliases / wrappers: `StanceItem = JudgmentItem` (or rename with DB column compatibility).
2. CLI/MCP/API accept `stance` paths; `judgment` remains deprecated alias calling the same handlers.
3. YAML bootstrap `judgment.yaml` may remain filename initially; document `stance.yaml` alias or copy-on-read — choose one, document in SETUP.
4. Context pack section rename: `applicable_judgment` → `applicable_stance` with deprecated key still emitted once for compatibility (warn in debug logs).

Constitutional confirm flags and proposal preview tokens keep the same security properties as current judgment (`confirm_constitutional`, preview fingerprints).

### Exit criteria

- [ ] `twin stance list` works; `twin judgment list` warns deprecation and returns same data.
- [ ] Existing judgment tests pass via aliases.
- [ ] Pack JSON includes Stance naming per chosen compatibility policy (tested).

### Assumptions

- Full prompt retarget “stance drafts” is T-050.
- No behavior change to approval gates.

### Expected QA

- Run `tests` under `judgment/` / privacy personas — green.
- CLI help text shows Stance first.

### Resources

- `twin/judgment/**`
- `docs/v2.md` §10 decision 5; §12.2b table
- `docs/CLI.md` Judgment section

---

## T-020 — Cognize availability gate (`require_chat_llm`)

**Phase:** P2 · **Status:** `todo`  
**Depends on:** none (can parallel P0/P1)  
**Blocks:** T-021, T-030, T-081

### Description

Implement a single gate used by all Cognize entrypoints:

```text
require_chat_llm(config/runtime) -> Ok | Halt(reason)
```

Halt reasons must be explicit and machine-readable, e.g.:

- `llm_unreachable`
- `llm_misconfigured`
- `heuristic_meaning_requested`
- `extractor_mode_blocks_cognition` (when `TWIN_EXTRACTOR=heuristic`)

Behavior:

- Sense ingest/connectors continue.
- Firewall continues.
- Cognize writes **zero** Reflections/Interpretations/Relations/Narrative revisions/Stance drafts/Fade judgments.
- Surfaces report halt clearly (`twin cognize status`, runtime job result, API error body).

Wire gate into future orchestrator and, temporarily, into existing `extract` / `meditate` / episode semantic stages so production cannot silently degrade to lexical understanding (bridge until those commands become aliases).

### Exit criteria

- [ ] With LLM stopped: cognize/extract/meditate semantic paths halt; percepts remain pending/deferred — **no new MemoryCandidates invented by heuristics in interpreting modes**.
- [ ] Status command/API shows last halt reason + timestamp.
- [ ] Unit test covers each halt reason.

### Assumptions

- Sense + Firewall explicitly out of scope for halt.
- Deterministic stale mark (T-060) is allowed without LLM.

### Expected QA

- Extend patterns from `tests/cognition/test_interpreter.py` deferral tests.
- Runtime job kind for cognize (when added) marks failure retryable like `model_unavailable` — never DLQ permanent for “LLM down.”

### Resources

- `docs/v2.md` §0
- `twin/cognition/interpreter/**`, `twin/cognition/episode_pipeline.py`
- `twin/config.py` (`TWIN_EXTRACTOR`, LLM provider settings)
- `twin/runtime/handlers.py`

---

## T-021 — Remove/disable heuristic meaning as production cognition

**Phase:** P2 · **Status:** `todo`  
**Depends on:** T-020  
**Blocks:** T-023, T-030

### Description

`twin/cognition/extractors/heuristic.py` and any “lexical establishes memory type/domain/confidence” path must **not** create cognitive conclusions in production.

Allowed residual roles (if any):

- DetectionSignal-only routing hints (already the v0.7 intent), **or**
- Complete disable with clear error when selected.

Interpreting modes (`auto` / provider chat): unavailable model → halt/defer (already), never heuristic fill-in.

Update docs/SETUP: heuristic is not a cognition backend.

### Exit criteria

- [ ] Test: `TWIN_EXTRACTOR=heuristic` + `twin cognize`/`extract` does not insert MemoryItems or Interpretations; returns blocked/halt.
- [ ] CI still has a deterministic stand-in for tests via **authored overrides** / recorded fixtures (like `set_interpreter_override`), not lexical meaning.
- [ ] CHANGELOG/OPERATIONS note the behavior change.

### Assumptions

- Echo mock handled in T-022.
- Eval harnesses that depended on heuristic meaning must switch to fixtures (call that out in PR).

### Expected QA

- `tests/cognition/test_heuristic.py` updated expectations.
- Grep for “fallback” / “lexical” semantic writes in cognition package — none remain on production paths.

### Resources

- `docs/v2.md` §0, §11.1
- `docs/CHANGELOG.md` v0.7 interpreter semantics
- `twin/cognition/extractors/heuristic.py`, `twin/cognition/pipeline.py`

---

## T-022 — Remove echo-as-production meaning path

**Phase:** P2 · **Status:** `todo`  
**Depends on:** T-020  
**Blocks:** T-030

### Description

Echo extractor/interpreter is a **test double**, not a production cognition backend. Ensure:

1. Production config cannot select echo as a real understanding engine without an explicit `TWIN_ALLOW_ECHO_COGNITION=1` test-only flag (or remove from production enum entirely).
2. Docs state echo classifies nothing meaningful (already true in v0.7) and cannot satisfy Cognize.
3. Any code path that treated echo completions as “LLM up” for gate purposes must not count as satisfying `require_chat_llm` unless the test flag is set.

### Exit criteria

- [ ] Default install / `twin init` never configures echo.
- [ ] Gate treats echo as halt in production.
- [ ] Tests that need deterministic cognition use stage overrides / recorded LLM fixtures.

### Assumptions

- Hash embedder remains valid (embeddings are indexes, not cognition).

### Expected QA

- Config construction tests for provider enum.
- Doctor warns if echo detected in env.

### Resources

- `docs/v2.md` §0
- `twin/cognition/extractors/`, interpreter echo/mock paths
- `docs/SETUP.md`

---

## T-023 — Episode pipeline: delete lexical semantic fallbacks; halt instead

**Phase:** P2 · **Status:** `todo`  
**Depends on:** T-020, T-021  
**Blocks:** T-030 (cleanup), T-082

### Description

`twin/cognition/episode_pipeline.py` and related phase/edge code already moved semantics to LLM in v1.3. Ensure remaining gaps match v2:

1. Missing model → **halt/defer** with no structural-only “fake understanding” presented as cortex success for semantic claims.
2. Remove brain-region CLI names from **primary** UX when Cognize lands (aliases OK); stop documenting amygdala/hippocampus as user-facing verbs (align with §12.2b).
3. Soft-fuse / ACC may remain as **input compilation** for LLM stages but must not assert Narrative meaning alone.
4. Plan deletion or quarantine of `structural_reflector`-style leftovers if any remain.

This task is the bridge: either wrap the old pipeline behind the new gate or mark it deprecated pending T-030 replacement. Prefer: old `meditate` calls gate + warns “deprecated; use cognize.”

### Exit criteria

- [ ] No production path writes phase/edge with `method` implying lexical understanding when LLM down.
- [ ] Tests for deferral remain green; any test that expected lexical phases updated.
- [ ] OPERATIONS.md notes halt behavior.

### Assumptions

- Full replacement of stage graph is P3; this task makes the old path safe under v2 invariants.

### Expected QA

- Episode pipeline tests + interpreter deferral tests.
- Manual: stop Ollama/API → `twin meditate` / `cognize` halts cleanly.

### Resources

- `twin/cognition/episode_pipeline.py`, `episode_reflect.py`, `correlation/**`
- `docs/v2.md` §§0, 11.1, 12.2b
- `docs/ARCHITECTURE.md` brain stages (legacy)

---

## T-030 — Cognize orchestrator skeleton + stage report

**Phase:** P3 · **Status:** `todo`  
**Depends on:** T-011, T-020, T-021, T-022  
**Blocks:** T-031–T-038, T-081

### Description

Implement `twin/cognize/orchestrator.py` (path flexible) that:

1. Calls `require_chat_llm()` first.
2. Runs stages 0→7 in order (stubs OK initially that return `skipped` until each stage lands).
3. Returns a `CognitionReport`-like object: per-stage `ok | halted | deferred | skipped | blocked` + counts + model/prompt versions + usage ledger hooks (`twin/cognition/llm/usage.py`).
4. Supports `--until <stage>` for debug.
5. Enqueues review clusters after stage 7 (even if review UI is still memory-shaped — queue abstraction).
6. **Never** auto-commits Narratives.
7. Invokes deterministic `mark_stale` hook (interface) before LLM stages when percept batch arrives — implement real mark in T-060; orchestrator must call the hook in the correct order (`v2.md` §3.2).

Wire runtime job kind `cognize_batch` (name flexible) in `twin/runtime/`.

### Exit criteria

- [ ] `twin cognize run --dry-run` (or python API) prints stage plan and halt if no LLM.
- [ ] Report schema stable enough for CLI `--json`.
- [ ] Unit test: LLM down → all cognitive stages halted, zero entity writes.
- [ ] Unit test: LLM up with all stages stubbed `skipped` still persists nothing durable except optional run record.

### Assumptions

- Stage implementations land as T-031…T-038 filling stubs.
- Human review is T-040.

### Expected QA

- Mirror `CognitionReport` testing style from `episode_pipeline.py`.
- Usage ledger entries created when stubs call LLM later.

### Resources

- `docs/v2.md` §§2.1, 3.2, 11
- `twin/cognition/episode_pipeline.py` (report pattern)
- `twin/runtime/handlers.py`, `service.py`

---

## T-031 — Stage 0 Salience (LLM)

**Phase:** P3 · **Status:** `todo`  
**Depends on:** T-030  
**Blocks:** T-032

### Description

LLM decides whether a percept batch deserves Cognize budget now: drop / defer / proceed with salience score/rationale.

Inputs: percept batch (PII-masked if cloud), source class, vault.  
Outputs: per-item or batch salience marks persisted; dropped items do not proceed to Situate.

No keyword classifier as authority. Prompt/schema versioned. Test override hook required.

### Exit criteria

- [ ] Live LLM path + `set_stage_override("salience", …)` for CI.
- [ ] Dropped percepts remain available for a future run (not deleted).
- [ ] Halt if LLM fails mid-stage (no partial silent success without record).

### Assumptions

- Masking uses existing PII pipeline before cloud calls.

### Expected QA

- Override tests; optional `TWIN_EVAL_MODEL=1` scenario later.
- Ensure drop ≠ interpreted-as-empty-confusion (distinct statuses).

### Resources

- `docs/v2.md` §§2.1, 4, 5.1 (Spotlight adjacent)
- `twin/cognition/salience.py` (v0.8 — may inspire signals but Stage 0 must be LLM-judged meaning)

---

## T-032 — Stage 1 Situate (LLM)

**Phase:** P3 · **Status:** `todo`  
**Depends on:** T-031, T-011  
**Blocks:** T-033

### Description

LLM assigns percepts to Situation clusters (create/join/conclude). No Event entity (`v2.md` §10 #14). Vault-scoped. Temporal proximity alone must not force merge without model judgment (align with correlation non-goals).

Persist Situation membership. Reuse lessons from WorkEpisode clustering but **do not** auto-write Memory.

### Exit criteria

- [ ] Situations CRUD via stage output.
- [ ] Cross-vault situate refused.
- [ ] Override tests for join vs new situation.

### Assumptions

- Old WorkEpisode can remain; Situate may later replace episode identity — do not dual-write episodes unless needed for dual-read.

### Expected QA

- Multi-percept batch fixtures (Slack+GitHub) create one Situation when override says so; two when override separates.

### Resources

- `docs/v2.md` §§2.1, 2.2, 10 #14
- `twin/cognition/correlation/episodes.py`, `partition.py`

---

## T-033 — Stage 2 Raise Reflections (LLM)

**Phase:** P3 · **Status:** `todo`  
**Depends on:** T-032  
**Blocks:** T-034, T-035

### Description

LLM raises open Reflections (questions / tensions / unresolved framings) for Situations — **few** high-value gaps, not one factoid per sentence.

Prioritize by expected learning progress / uncertainty (`v2.md` §5 curiosity refs as design criteria in prompts — not a numeric library).

Status `open` by default. Always visible in Review later (T-040).

### Exit criteria

- [ ] Reflections persisted; linked to situations/percepts.
- [ ] Prompt forbids inventing Reflections that are not grounded in provided batch/situation brief.
- [ ] CI override can emit canonical Reflection set.

### Assumptions

- Cross-merge of duplicate questions is Stage 4, but Stage 2 should still avoid obvious spam.

### Expected QA

- Grounding checks similar to interpreter evidence_span validation where applicable.
- Count sanity: batch of near-duplicate Slack messages → small Reflection set under override policy tests.

### Resources

- `docs/v2.md` §§2.1, 3.1, 5 (curiosity)
- Interpreter grounding patterns: `twin/cognition/interpreter/`

---

## T-034 — Stage 3 Form Interpretations (LLM)

**Phase:** P3 · **Status:** `todo`  
**Depends on:** T-033  
**Blocks:** T-036, T-037

### Description

LLM forms competing **Interpretations** (candidate explanations) for Reflections/Situations — not “answers to user queries,” not MemoryCandidates.

Each Interpretation must cite Evidence anchors (percept spans). Ungrounded items dropped (deterministic validation).

Status starts `competing`. Multiple Interpretations per Reflection allowed.

### Exit criteria

- [ ] Ungrounded interpretation dropped with counter.
- [ ] No auto-promote to Narrative.
- [ ] Schema distinguishes Interpretation from Narrative in storage.

### Assumptions

- Evidence audit (Stage 7) deepens independence; Stage 3 still requires span grounding.

### Expected QA

- Invented span test (must drop).
- Competing pair fixture under one Reflection.

### Resources

- `docs/v2.md` §§2.1, 2.2, 3.1
- `twin/cognition/interpreter/schema.py` (act-aware items — do not confuse with Interpretation entity; new schema)

---

## T-035 — Stage 4 Cross Reflections (LLM)

**Phase:** P3 · **Status:** `todo`  
**Depends on:** T-033, T-013  
**Blocks:** T-037

### Description

LLM links Reflections: `same-as` / `related` / conflict-of-asks. Collapse duplicates to canonical open Reflection; supersede losers with provenance (do not delete history).

### Exit criteria

- [ ] Relations written with rationales.
- [ ] Canonical Reflection id stable under re-run (idempotent).
- [ ] Review can see merged history.

### Assumptions

- Embeddings may propose candidates to the LLM brief but cannot alone assert `same-as`.

### Expected QA

- Five paraphrased questions → one canonical Reflection in override test.

### Resources

- `docs/v2.md` §3.1–3.3

---

## T-036 — Stage 5 Cross Interpretations (LLM)

**Phase:** P3 · **Status:** `todo`  
**Depends on:** T-034, T-013  
**Blocks:** T-037

### Description

LLM relates Interpretations: `same-as` / `supports` / `contradicts` / evidence overlap. Weight disagreement; do not treat echo agreement as strong confirmation.

### Exit criteria

- [ ] Contradict Relations retained for Stage 6.
- [ ] Idempotent re-cross on same set.
- [ ] Metrics/counters for support vs contradict edges.

### Assumptions

- `same_originating_decision` primarily Stage 7, but Stage 5 may hint overlaps.

### Expected QA

- Fixture with two contradictory explanations under one Reflection → `contradicts` edge.

### Resources

- `docs/v2.md` §§3.1, 3.4

---

## T-037 — Stage 6 Narrative Revision (LLM) + retain dissent

**Phase:** P3 · **Status:** `todo`  
**Depends on:** T-035, T-036, T-012, T-013  
**Blocks:** T-038, T-041, T-115

### Description

Implement Narrative Revision producing `NarrativeRevisionDecision` (`v2.md` §10):

- Outcomes: `integrate | branch | contradict | supersede | keep_separate | defer`
- Fields: `surprise`, `explanatory_delta`, `retained_dissent_ids`, `same_originating_decision_hints`, `rationale`
- Frame prompts around **surprise / explanatory power**, not vote counting
- Silent reversal path: allow low-confidence **challenger** Interpretation without instantly replacing durable Narrative
- **Retain dissent:** never detach losing Interpretation/Evidence

Does not itself commit Narrative (Stage 9 / human).

### Exit criteria

- [ ] Decision objects persisted and attached to review clusters.
- [ ] Supersede outcome lists `retained_dissent_ids` non-empty when a loser exists.
- [ ] Override tests for each outcome at least once.
- [ ] Logging hooks for research (§9.3 #7) — even if full eval is T-115.

### Assumptions

- Prior Narratives may be empty on first run → outcome often `integrate`/`defer` creating first account proposal for review.

### Expected QA

- Quiet reversal fixture: single contradicting meeting percept → challenger + `defer` or `contradict`, not silent overwrite of committed Narrative.
- Correlated echoes do not auto-`supersede` solely from agreement count.

### Resources

- `docs/v2.md` §§2.1, 3.4, 4, 5 (prediction error), 9.3, 10
- Stage schema in §10

---

## T-038 — Stage 7 Evidence audit + independence Relations

**Phase:** P3 · **Status:** `todo`  
**Depends on:** T-037, T-013  
**Blocks:** T-040, T-071

### Description

LLM audits warrants for Interpretations; writes Evidence links; estimates independence; asserts `same_originating_decision` where appropriate.

Rules:

- Skip heavy re-audit on tiny single-origin batches (performance) per §10 #11 — still allow Inject read-time derivation.
- Prefer disagreement attention signals for review ranking.
- **Must not** bump a stored confidence scalar.
- May write `independence_sketch` on EpistemicState for proposals awaiting commit.

### Exit criteria

- [ ] Multi-source fixture collapses to one independent origin when LLM override says same decision.
- [ ] Evidence ids include dissenting spans.
- [ ] Production refuses to set `narrative.confidence += x`.

### Assumptions

- ACL tags on Evidence come from Sense/connectors.

### Expected QA

- Unit tests with overrides (no network).
- Eval scaffolding for T-111.

### Resources

- `docs/v2.md` §§2.3, 3.4, 6, 10 #11
- ACC dossier patterns: `twin/cognition/analysis_dossier.py` (compile briefs for the LLM; LLM still judges)

---

## T-040 — Review queue for Interpretations + always-visible Open Reflections

**Phase:** P4 · **Status:** `todo`  
**Depends on:** T-038, T-014  
**Blocks:** T-041, T-092, T-101

### Description

Retarget review UX (CLI `twin review`, workbench under `twin serve`) so the primary queue is:

1. **Interpretation clusters** with Narrative Revision decisions + Evidence
2. **Open Reflections always visible** (sidebar/section — `v2.md` §10 #1)

Actions: accept Interpretation(s) → prepare Commit Narrative; reject; keep conflict open; request more evidence; attach dissent.

Do not require reviewing every Reflection to proceed, but they must not be hidden.

Forest/Trees presentation (`v2.md` §9.4): higher-grain proposal + epistemic summary, then evidence/conflict anchors.

Remove product copy that says “confirm memory.”

### Exit criteria

- [ ] Open Reflections section always rendered when any exist (CLI + API).
- [ ] Commit path calls Stage 9 API (T-041) — if T-041 not merged, gate behind feature flag but UI wired.
- [ ] Legacy memory review still reachable via deprecated mode during migration, with warning banner.

### Assumptions

- Browser workbench remains; Command Center only deep-links (P9).

### Expected QA

- API tests for review list shape.
- Manual screenshot/notes optional; automated JSON fixtures required.

### Resources

- `docs/v2.md` §§9.4, 10 #1, #4
- `twin/interfaces/cli.py` `cmd_review`, `twin/interfaces/web/**`, `twin/interfaces/api.py`

---

## T-041 — Stage 9 Commit Narrative + initial EpistemicState

**Phase:** P4 · **Status:** `todo`  
**Depends on:** T-040, T-012  
**Blocks:** T-050, T-070, T-110

### Description

Human accept applies:

1. Persist **Narrative** (account text, grain optional, evidence_ids including dissent).
2. Create **EpistemicState** with `status=fresh`, `synthesized_at=now`, `freshness_boundary=max(evidence timestamps)`, empty `unseen_since`.
3. Mark winning Interpretation `committed` / losers `superseded` or `rejected` per decision — **retain attachments**.
4. Audit actor = human principal; Cognize must not call commit without human.
5. Optional Narrative↔Narrative Relations (`part-of`) if review selected composition.

### Exit criteria

- [ ] Commit without evidence fails closed.
- [ ] Commit without human actor fails closed.
- [ ] Idempotent commit token / preview fingerprint (mirror judgment preview pattern).
- [ ] Pack-eligible Narratives are committed+fresh (or explicitly stale-labeled — never silent stale).

### Assumptions

- Stance drafts are separate (T-050) and may be enqueued after commit.

### Expected QA

- Tests ported from `tests/memory/test_formation.py` confirm invariants.
- Sovereignty integrity check: Narrative without evidence fails cognition health.

### Resources

- `docs/v2.md` §§2.1–2.3, 6
- `twin/memory/formation.py`, judgment approve preview tokens

---

## T-050 — Stage 10 Stance drafts (LLM) + human approve path

**Phase:** P5 · **Status:** `todo`  
**Depends on:** T-041, T-015  
**Blocks:** T-082

### Description

After Narrative commit, LLM may draft pending **Stance** proposals (how to evaluate similar cases). Human approve via `twin stance …` (judgment aliases). Constitutional flags unchanged in spirit.

Prompts must not treat Stance as factual Narrative.

### Exit criteria

- [ ] Drafts are pending until approve.
- [ ] Pack `applicable_stance` uses approved items only.
- [ ] Tests for propose-from-narrative parallel to `propose_from_episode`.

### Assumptions

- Nightly consolidation may also propose stances (T-051) — share proposal engine.

### Expected QA

- Existing judgment evals under `evals/judgment/` still pass via aliases.
- New cognize→stance draft unit test with override.

### Resources

- `docs/v2.md` §§2.1, 10 #5, 12.2b
- `twin/judgment/proposals.py`, `application.py`

---

## T-051 — Stage 11 Consolidation judgment (nightly LLM, caps)

**Phase:** P5 · **Status:** `todo`  
**Depends on:** T-030, T-041  
**Blocks:** none critical

### Description

Nightly/weekly job: LLM argues what should generalize vs stay episodic; emits consolidation tags / promote drafts; **humans still gate durability**.

Caps: max drafts per vault/night; max tokens; skip if LLM halted.

Retarget `twin consolidate daily|weekly` to this stage (legacy schedule OK). Never confirm Narrative/Stance automatically (`ConsolidationInvariantError` spirit preserved).

### Exit criteria

- [ ] Caps enforced and tested.
- [ ] Idempotent window apply (`duplicated=True`) preserved.
- [ ] Halt if no LLM — job retryable, no heuristic consolidation meaning.

### Assumptions

- CLS / selective consolidation citations inform prompts only (`v2.md` §5).

### Expected QA

- Extend `tests/cognition/test_consolidation_cycle.py`.
- Invariant: completed run did not confirm Narrative.

### Resources

- `docs/v2.md` §§4, 5, 10 #3, 11.6
- `twin/cognition/consolidation_cycle.py`, runtime consolidate handlers

---

## T-052 — Stage 12 Fade / Remarkable + Trace ledger

**Phase:** P5 · **Status:** `todo`  
**Depends on:** T-041  
**Blocks:** none critical

### Description

1. Append-only **Trace** of retrieval/use events (Inject packs, search hits, review opens).
2. LLM recommends accessibility: remarkable / ordinary / fading / archive stub — **not** cron-delete-by-age alone.
3. Recommendations enqueue review; do not silently delete Narratives.

### Exit criteria

- [ ] Trace written on pack serve.
- [ ] Fade recommendations visible in Review/CLI.
- [ ] Age-only deletion of Narratives does not exist as Cognize policy.

### Assumptions

- Retention of raw connector artifacts remains Sense/sovereignty concern.

### Expected QA

- Trace append idempotency / volume smoke test.
- Override test for remarkable pin when Stance-linked.

### Resources

- `docs/v2.md` §§2.1, 4, 5 (forgetting / tag-and-capture)

---

## T-060 — Deterministic stale mark on percept land

**Phase:** P6 · **Status:** `todo`  
**Depends on:** T-012, T-011  
**Blocks:** T-070, T-110

### Description

When a Percept is committed by Sense into a domain/vault that overlaps a committed Narrative:

1. **Before** Cognize runs, set Narrative EpistemicState `status=stale`, fill `stale_reason`, append percept id to `unseen_since`.
2. No LLM.
3. Overlap definition: shared vault + domain/project/entity/situation membership heuristic documented in EPISTEMICS — start conservative (same vault + overlapping project/domain tags or explicit situation link).
4. Orchestrator order in T-030 must call this first.

### Exit criteria

- [ ] Test: insert percept → Narrative becomes stale without LLM configured.
- [ ] Inject path (even stub) can detect stale immediately.
- [ ] Re-synthesis / commit clears stale and refreshes freshness_boundary (integration with T-041).

### Assumptions

- False-positive stale is safer than false-fresh; tune overlap later via experiments.

### Expected QA

- Concurrent percept insert + pack request race: pack must not claim fresh if stale mark committed.

### Resources

- `docs/v2.md` §§2.3, 3.2, 6, 10 #10
- Sense write paths: connectors finalize, `twin/sensory/`, session_complete percept insert

---

## T-061 — Source-class + timestamp metadata for invalidation asymmetry

**Phase:** P6 · **Status:** `todo`  
**Depends on:** T-060  
**Blocks:** T-113

### Description

Ensure every Percept carries durable **source class** (e.g. `code_repo`, `chat_discussion`, `meeting`, `mail`, `calendar`, `document`, `session_residue`) and reliable timestamps so Cognize/Inject can treat lifetimes differently (code often self-invalidates; discussion may reverse quietly).

Document the enum; map connectors → classes; forbid missing class on new writes (default `unknown` + review flag).

### Exit criteria

- [ ] Connector normalizers set source class.
- [ ] Session residue percepts labeled distinctly.
- [ ] EPISTEMICS.md documents asymmetry policy.

### Assumptions

- Does not by itself implement quiet-reversal cognition (T-037/T-113); only enables it.

### Expected QA

- Fixture asserts Slack vs GitHub classes differ.
- Migration backfill for old percepts → `unknown` acceptable with warning metric.

### Resources

- `docs/v2.md` §§7, 9.2 C
- Connector normalize modules under `twin/connectors/**`

---

## T-070 — Inject pack: attach EpistemicState; refuse stale-as-fresh

**Phase:** P7 · **Status:** `todo`  
**Depends on:** T-041, T-060  
**Blocks:** T-071, T-072, T-102, T-110

### Description

Update context pack assembly (`twin/cognition/context_pack.py`, pack_format/select):

1. Include EpistemicState for every Narrative served.
2. **Floor:** never present `status=stale` as current without labeling; preferred behavior: withhold from “active” section OR include only in `stale` section with reason — never silently as fresh.
3. If Cognize never ran / no Narratives: do not invent heuristic content; return empty/honest degraded pack.
4. Provenance: every claim traces to Evidence ids + timestamps.
5. Firewall still runs deterministically before content leaves.

### Exit criteria

- [ ] Contract test: stale Narrative cannot appear in `active` without `epistemic.status=stale`.
- [ ] Golden pack JSON schema includes epistemic fields.
- [ ] Blocked items still ids/reasons only (no leak).

### Assumptions

- Observer LLM slot is T-074 (optional later); packs can work without it.

### Expected QA

- Extend `tests/cognition/test_context_pack.py`.
- Adversarial: attempt to force stale-as-fresh via API flags — fail closed.

### Resources

- `docs/v2.md` §§6, 9.2 A, 9.4
- `twin/cognition/context_pack.py`, `pack_format.py`, `pack_select.py`

---

## T-071 — Read-time confidence + independence display in packs

**Phase:** P7 · **Status:** `todo`  
**Depends on:** T-070, T-012, T-038  
**Blocks:** T-111

### Description

At pack time, compute and display:

- derived confidence summary (not stored float)
- independence summary (`N observations, K independent origins`)
- supports vs contradicts highlights
- retained dissent pointers

Never show a cached confidence scalar field from DB as authoritative.

### Exit criteria

- [ ] Correlated-source fixture displays K=1 when Relations say so.
- [ ] Pack schema documents derived fields as derived.
- [ ] Unit tests do not require LLM (use stored Relations fixtures).

### Assumptions

- Stage 7 quality affects Relations richness; Inject must still derive something sensible with sparse Relations (show uncertainty).

### Expected QA

- Table tests for derive_* helpers + pack integration snapshot.

### Resources

- `docs/v2.md` §§2.3, 3.4, 6

---

## T-072 — Open Reflections section in packs

**Phase:** P7 · **Status:** `todo`  
**Depends on:** T-070, T-033  
**Blocks:** none

### Description

Settled decision (`v2.md` §10 #4): packs include Open Reflections in an uncertainty section (policy-filtered by firewall).

### Exit criteria

- [ ] Open reflections appear when allowed by domain firewall.
- [ ] Restricted reflections blocked with reasons, not content.
- [ ] Section named without “memory.”

### Assumptions

- Ranking may be simple (salience/recency) initially.

### Expected QA

- Firewall tests for reflection domain tags.
- Pack size budget still respected (`max_tokens`).

### Resources

- `docs/v2.md` §10 #4, §6

---

## T-073 — ACL intersection on Narrative + synchronous revoke tombstone

**Phase:** P7 · **Status:** `todo`  
**Depends on:** T-041  
**Blocks:** T-114

### Description

1. On Commit Narrative, compute ACL / sensitivity / vault visibility as **intersection** of contributing Evidence/source ACLs (private Slack ∩ public PR → private).
2. Cognize must refuse to write a claim that expands permissions beyond inputs.
3. On source revoke/delete: **synchronously tombstone** dependent Narratives/Interpretations (or mark tombstoned EpistemicState) — no async “eventually consistent leftover truth” for MVP (`v2.md` §10 #12).
4. Align with Domain Firewall + privacy engine (`twin/privacy/**`).

### Exit criteria

- [ ] ACL stress test: user without Slack ACL cannot see derived Narrative from private Slack + public PR.
- [ ] Delete-source / revoke path tombstones dependents in same request transaction.
- [ ] Audit log entries for tombstones.

### Assumptions

- PermissionGrant TTL machinery can remain; intersection is additional constraint on derived artifacts.

### Expected QA

- New tests under `tests/privacy/` + sovereignty deletion tests.
- Eval T-114 can wrap this.

### Resources

- `docs/v2.md` §§6, 9.2 D, 10 #12
- `twin/privacy/**`, `twin/memory/retention.py`, delete-source CLI

---

## T-074 — Inject Observer slot (interface reserved, stub OK)

**Phase:** P7 · **Status:** `todo`  
**Depends on:** T-070  
**Blocks:** none

### Description

Reserve the Inject Observer interface (`v2.md` §6):

- Module/API: watch conversation turns → decide whether/what/when to inject from committed substrate
- **Must not** raise Reflections or commit Narratives
- **Must not** use regex topic detector as the Observer
- MVP: stub that returns “no-op / use explicit pack request”; feature flag `TWIN_INJECT_OBSERVER=0` default
- Document reserved space in ARCHITECTURE / INTERFACES

Do not implement full watcher yet unless explicitly expanding scope — redesign says design for it, don’t fully implement yet.

### Exit criteria

- [ ] Interface exists; default stub wired; no heuristic fake observe.
- [ ] Docs mark Observer as reserved Inject LLM slot.
- [ ] Tests ensure stub cannot write Cognize entities.

### Assumptions

- Native search-vote domain resolution may remain temporary hot-path until Observer exists — document as transitional, not Observer.

### Expected QA

- Import/smoke test; capability flag in MCP `capabilities`.

### Resources

- `docs/v2.md` §6
- `twin/cognition/observer.py` (legacy Memory Observer — clarify rename vs Inject Observer in docs to avoid collision; consider `inject_observer.py`)

---

## T-080 — Extract CLI handlers to `twin/interfaces/commands/`

**Phase:** P8 · **Status:** `todo`  
**Depends on:** none (can start early)  
**Blocks:** T-081, T-090

### Description

Refactor `twin/interfaces/cli.py` monolith: move business handlers into `twin/interfaces/commands/` modules (ingest, cognize, review, connectors, runtime, …). Argparse remains thin.

**Mandate:** TUI and argparse call the **same** functions — no forked logic (`v2.md` §12.6).

No user-visible behavior change required in this task beyond optional import path cleanup.

### Exit criteria

- [ ] `cli.py` mostly registration + parsing.
- [ ] `pytest` / smoke CLI commands still work.
- [ ] Public function signatures documented for TUI use.

### Assumptions

- Textual app not required yet.

### Expected QA

- `twin --help`, `twin doctor`, `twin pack … --json` smoke.
- Full `pytest -q` green.

### Resources

- `docs/v2.md` §§12.6, 12.8 step 1
- `twin/interfaces/cli.py`

---

## T-081 — Introduce `twin cognize` / `narrative` / `stance` / `inject pack`

**Phase:** P8 · **Status:** `todo`  
**Depends on:** T-080, T-030, T-015, T-014  
**Blocks:** T-082, T-090, T-100

### Description

Add primary v2 verbs (`v2.md` §12.2b):

```text
twin cognize run [--until <stage>] [--dry-run] [--json]
twin cognize status
twin narrative search|show|relations|…
twin stance list|propose|preview|approve|…
twin inject pack <query> --domain …   # or keep twin pack as alias initially
```

Command Center (later) shows only these names. Implement by calling orchestrator + store APIs.

Scripted shape must support CI (`--json`).

### Exit criteria

- [ ] Help text lists v2 verbs prominently.
- [ ] `cognize run` respects LLM-or-halt.
- [ ] `narrative show` prints EpistemicState.
- [ ] Docs CLI.md updated for new verbs (legacy appendix can wait for T-082).

### Assumptions

- Full narrative mutation ops can be minimal (show/search/relations) in first pass.

### Expected QA

- CLI tests / subprocess smoke.
- JSON schema stability snapshot.

### Resources

- `docs/v2.md` §12.2b
- `docs/CLI.md`

---

## T-082 — Deprecate aliases: extract, meditate, correlate, judgment, memory

**Phase:** P8 · **Status:** `todo`  
**Depends on:** T-081, T-023  
**Blocks:** T-092

### Description

Legacy argv becomes aliases that:

1. Print deprecation warning to stderr (unless `--json` then warning field).
2. Call new handlers (`meditate` → `cognize run`, `judgment` → `stance`, `memory` → `narrative` ops where mapped).
3. `extract -A` / `--auto-approve` **removed or hard-blocked** for Narrative commit (may still exist as error message explaining human gate).

Sunset date: document in CHANGELOG / CLI appendix (e.g. remove aliases in next minor after v2 ships).

Command Center must **not** list legacy names as primary (fuzzy match OK).

### Exit criteria

- [ ] Each legacy command warns once per invocation.
- [ ] CI scripts using meditate still work via alias.
- [ ] Auto-approve path cannot commit Narrative.
- [ ] CLI.md “Legacy aliases” appendix exists.

### Assumptions

- Brain-stage CLI labels dropped from primary docs.

### Expected QA

- Tests assert warning + equivalent effect for meditate→cognize.
- Negative test for `-A` commit.

### Resources

- `docs/v2.md` §§12.2b, 12.8, 12.9
- OPERATIONS.md command examples — update to v2 verbs with alias notes

---

## T-090 — Command Center MVP: bare `twin` TUI Home + Services + palette

**Phase:** P9 · **Status:** `todo`  
**Depends on:** T-080, T-081  
**Blocks:** T-091, T-092

### Description

When `twin` is invoked with no subcommand and stdin is a TTY, launch Command Center TUI (`v2.md` §12).

MVP screens:

- **Home:** home path, doctor summary, services state, due syncs, review backlog count
- **Services:** start/stop supervised `twin serve` and `twin runtime` children; attach if already running; log pane
- **Palette:** `/` fuzzy over **v2 verbs** (+ deprecated aliases fuzzy)

Non-TTY: do not enter TUI; print concise help / require subcommand.

Exit policy: prompt Stop supervised services? Yes / Leave running / Cancel.

Stack suggestion: Textual (swap allowed if justified). Prefer panes over emoji chrome.

### Exit criteria

- [ ] `twin` on TTY opens center; `echo | twin` does not hang in TUI.
- [ ] Starting serve from Services shows URL; stop works.
- [ ] Runtime attach-vs-start rule implemented.
- [ ] `docs/COMMAND_CENTER.md` stub or § in CLI.md describing MVP.

### Assumptions

- Auto-start preferences may be manual-only for MVP (`v2.md` §12.10 open).
- Does not embed Cognize LLM in TUI process — triggers jobs only.

### Expected QA

- Manual operator test script in PR.
- Automated: non-TTY help; optional Textual pilot tests if feasible in CI.

### Resources

- `docs/v2.md` §§12.1–12.5, 12.7–12.8
- Textual docs: https://textual.textualize.io/
- Existing Rich patterns in `twin/interfaces/ux.py`, runtime live panel

---

## T-091 — Center: Connectors + Jobs screens

**Phase:** P9 · **Status:** `todo`  
**Depends on:** T-090  
**Blocks:** none

### Description

Add Connectors and Jobs screens:

- Configure / auth / test / pause connectors (Sense I/O)
- Create sync/backfill/cognize/consolidate jobs with live progress
- Job fields per §12.5 (`kind`, `state`, `progress`, `log_ref`)
- Parallelism: jobs run while navigating other screens

Share implementation with `twin connector …` / runtime enqueue.

### Exit criteria

- [ ] Backfill progress visible without leaving TUI.
- [ ] Destructive connector revoke still requires confirm.
- [ ] Jobs use same runtime queue as CLI.

### Assumptions

- Webhooks remain HTTP-side; Center does not replace them.

### Expected QA

- Operator script: add fake/github connector in dry environment if available; or mock job progress unit tests.

### Resources

- `docs/v2.md` §§12.2, 12.5
- `twin/connectors/service.py`, `twin/runtime/**`

---

## T-092 — Center: Cognize / Review / Narratives / Stance / MCP screens

**Phase:** P9 · **Status:** `todo`  
**Depends on:** T-090, T-081, T-040, T-082  
**Blocks:** none

### Description

Add remaining IA screens from §12.3:

- Cognize: run / until stage / last report / halt reason / open reflection count
- Review: queue + deep-link to serve workbench URL
- Narratives: search/show/relations/grain
- Stance: list/proposals/approve
- MCP: client bindings + setup wizard launch
- Privacy / Settings minimal if time — otherwise Settings home/models/backup only

Primary labels are v2-only.

### Exit criteria

- [ ] Each screen calls shared command functions (no duplicated store logic).
- [ ] Review shows open Reflections.
- [ ] Cognize screen surfaces halt reason when LLM down.

### Assumptions

- Browser workbench not replaced.

### Expected QA

- Keyboard navigation smoke (documented shortcuts).
- No legacy “Memory” screen title.

### Resources

- `docs/v2.md` §12.3
- Review/MCP existing CLIs

---

## T-100 — MCP tool rename + pack EpistemicState fields

**Phase:** P10 · **Status:** `todo`  
**Depends on:** T-070, T-071, T-072, T-081  
**Blocks:** T-102

### Description

Update MCP server tools (`twin/interfaces/mcp_server.py`, `docs/MCP.md`):

1. Pack tools return EpistemicState + open reflections + derived confidence/independence.
2. Introduce Narrative/Stance tool names; deprecate memory_* tool names with warnings in tool descriptions.
3. Mutating tools still require `confirm=true` + capability checks.
4. Never expose forbidden content in blocked lists.

Keep process-env client identity (`TWIN_MCP_CLIENT`).

### Exit criteria

- [ ] MCP.md documents v2 fields and deprecations.
- [ ] Contract tests for pack payload.
- [ ] Old tool names still work briefly with deprecation note in response metadata.

### Assumptions

- Hosts (Cursor/Claude) may cache tool schemas — document restart requirement.

### Expected QA

- MCP protocol unit tests if present; else API-level pack tests suffice + manual host check.

### Resources

- `docs/v2.md` §§6, 12.2b
- `docs/MCP.md`
- `twin/interfaces/mcp_server.py`

---

## T-101 — REST / Review workbench Narrative commit UX

**Phase:** P10 · **Status:** `todo`  
**Depends on:** T-040, T-041  
**Blocks:** none

### Description

Update FastAPI routes and `twin serve` UI:

- Interpretation review cards
- Commit Narrative action with preview fingerprint
- EpistemicState badges (fresh/stale)
- Open Reflections panel
- Remove/hide “memory blob” chrome; rename labels

OpenAPI must reflect new resources (`/api/narratives`, `/api/reflections`, …) while legacy `/api/memories` remains aliased.

### Exit criteria

- [ ] OpenAPI lists Narrative commit endpoint.
- [ ] UI cannot commit without evidence + confirm.
- [ ] Stale badge visible on stale narratives.

### Assumptions

- Local-only bind remains default.

### Expected QA

- API tests; optional Playwright not required.
- Accessibility of badges not color-only (text status).

### Resources

- `docs/REST.md`, `twin/interfaces/api.py`, `twin/interfaces/web/**`
- `docs/v2.md` §9.4

---

## T-102 — Native pack injection uses v2 pack contract

**Phase:** P10 · **Status:** `todo`  
**Depends on:** T-070, T-100  
**Blocks:** none

### Description

Claude Code native hooks inject packs built with the v2 contract (EpistemicState, stale floor, open reflections). Hot-path deadlines remain. Fail-open behavior unchanged. Session residue still flows Sense → cognize enqueue — not Cognize talking to host.

Clarify in NATIVE.md: conversation uses Sense+Inject edges; no session “mode.”

### Exit criteria

- [ ] Native pack JSON includes epistemic fields when domain known.
- [ ] Stale narratives not injected as fresh.
- [ ] Fake-host evals updated.

### Assumptions

- Domain search-vote may remain until Observer exists.

### Expected QA

- `tests/interfaces/native/**` + evals/native lifecycle.

### Resources

- `docs/NATIVE.md`, `docs/v2.md` §§1, 6
- `twin/interfaces/native/**`, `twin/cognition/host_session.py`

---

## T-110 — Eval: stale injection (§9.3 #1)

**Phase:** P11 · **Status:** `todo`  
**Depends on:** T-070, T-060  
**Blocks:** none

### Description

Automated experiment:

1. Commit Narrative from Slack+GitHub-style fixtures.
2. Inject a **newer stale-making** Slack percept that contradicts / post-dates synthesis.
3. Request pack / fresh-host action prompt.
4. Assert Twin marks stale and does **not** narrate old world as current without epistemic label.

Offline fixtures preferred; optional model layer gated by env.

### Exit criteria

- [ ] Eval case under `evals/` with pass/fail assertions.
- [ ] Wired into `twin eval` or pytest.
- [ ] Failure message explains which floor broke.

### Assumptions

- Priority #1 experiment per `v2.md` §10 decision 13.

### Expected QA

- CI green without network.
- Document expected behavioral contract in eval README.

### Resources

- `docs/v2.md` §§9.3 #1, 10
- `twin/evals/**`, `tests/evals/**`

---

## T-111 — Eval: correlated-source independence collapse (§9.3 #3)

**Phase:** P11 · **Status:** `todo`  
**Depends on:** T-071, T-038  
**Blocks:** none

### Description

Fixture: meeting + roadmap + calendar + commit from **one** decision. Assert independence summary collapses to one origin and derived confidence does not treat four echoes as four votes.

Use Relation overrides if LLM not in CI.

### Exit criteria

- [ ] Assert K independent origins == 1.
- [ ] Assert display string / structure matches.
- [ ] Counter-example: truly independent contradicting source increases attention / does not collapse incorrectly.

### Assumptions

- Stage 7 override available.

### Expected QA

- Pure pytest table tests + one integration eval.

### Resources

- `docs/v2.md` §§9.3 #3, 3.4

---

## T-112 — Eval: disagreement vs agreement attention (§9.3 #4)

**Phase:** P11 · **Status:** `todo`  
**Depends on:** T-037  
**Blocks:** none

### Description

Single contradicting artifact (e.g. PR for Feature B while Narrative says Feature A) must produce Stage 6 attention / outcome stronger than three agreeing echoes (measured via decision outcome, surprise field, or review priority — define metric in eval).

### Exit criteria

- [ ] Metric documented and asserted.
- [ ] Echo-agreement control fixture included.

### Assumptions

- LLM override can set surprise=high on disagreement path.

### Expected QA

- Deterministic overrides in CI.

### Resources

- `docs/v2.md` §§9.3 #4, 3.4

---

## T-113 — Eval: quiet reversal path (§9.3 #2)

**Phase:** P11 · **Status:** `todo`  
**Depends on:** T-037, T-061  
**Blocks:** none

### Description

Known-wrong Narrative invalidated by a quiet meeting percept with **little subsequent discussion**. Assert system raises challenger / marks need for revision rather than relying on recency TTL alone.

### Exit criteria

- [ ] Challenger Interpretation or open Reflection exists.
- [ ] Prior Narrative retained (dissent) if superseded in fixture’s later step.
- [ ] Eval distinguishes drift (lots of talk) vs quiet reversal fixtures.

### Assumptions

- Sense coverage prerequisite: meeting percept must exist.

### Expected QA

- Two fixtures side-by-side in eval folder.

### Resources

- `docs/v2.md` §§3.4, 7, 9.3 #2

---

## T-114 — Eval: ACL intersection (§9.3 #5)

**Phase:** P11 · **Status:** `todo`  
**Depends on:** T-073  
**Blocks:** none

### Description

Private Slack fact + public PR → derived Narrative must not be visible to a principal lacking Slack ACL.

### Exit criteria

- [ ] Pack/search deny with reason.
- [ ] Canary/leakage tests fail closed if content appears.

### Assumptions

- Test principals/personas exist in privacy test harness.

### Expected QA

- `tests/privacy` + eval wrapper.

### Resources

- `docs/v2.md` §§6, 9.3 #5
- `tests/privacy/test_engine.py`

---

## T-115 — Research logging: surprise / explanatory_delta (§9.3 #7)

**Phase:** P11 · **Status:** `todo`  
**Depends on:** T-037  
**Blocks:** none

### Description

Not a ship gate for product, but required instrumentation:

- Persist Stage 6 `surprise` + `explanatory_delta` + outcome for analysis
- Exportable via stats/usage
- RESEARCH.md describes hypothesis: explanatory-power optimization vs support-accumulation baseline

### Exit criteria

- [ ] Fields queryable from store/CLI.
- [ ] RESEARCH.md hypothesis section updated.
- [ ] No product dependency on this metric for Inject floor.

### Assumptions

- May run only when Cognize runs with real LLM.

### Expected QA

- Unit test that decisions persist research fields.

### Resources

- `docs/v2.md` §§9.3 #7, 10 #15
- `docs/RESEARCH.md`

---

## T-120 — Split docs: ARCHITECTURE / COGNIZE / EPISTEMICS / RESEARCH

**Phase:** P12 · **Status:** `todo`  
**Depends on:** T-001, T-002, majority of P3–P7 `done`  
**Blocks:** T-121

### Description

Move content out of the monolithic `docs/v2.md` working doc into durable homes:

| Doc | Owns |
|---|---|
| ARCHITECTURE.md | Sense/Cognize/Inject walls, runtime topology, threat model |
| COGNIZE.md | Full stage pipeline, entity I/O contracts, Narrative Revision |
| EPISTEMICS.md | Provenance, freshness, independence, ACL, tombstones, confidence |
| RESEARCH.md | Academic §5, hypotheses, experiments, bibliography |

Keep `docs/v2.md` as historical redesign journal or slim pointer to the split docs + this tracker.

Update GLOSSARY/COGNITION/IDENTITY cross-links.

### Exit criteria

- [ ] No critical implementer info lives only in outdated stubs.
- [ ] README docs table updated.
- [ ] Academic claims absent from README.

### Assumptions

- Engineering may still reference tracker IDs.

### Expected QA

- Link audit across docs/.
- Compare checklists vs `v2.md` §0− planned split table.

### Resources

- `docs/v2.md` §§0−, 5, 11.9
- Existing docs set

---

## T-121 — README stays architecture-layer only; add COMMAND_CENTER.md

**Phase:** P12 · **Status:** `todo`  
**Depends on:** T-120, T-090  
**Blocks:** none (release documentation gate)

### Description

1. README public story: Sense → Cognize → Inject; longitudinal Narratives; no Cognize stage laundry list; no academic dump.
2. Identity vs GBrain differentiation short table OK.
3. Add `docs/COMMAND_CENTER.md` from §12 (or finalize stub).
4. Update OPERATIONS quickstart to `twin cognize` / review Narrative commit.
5. Speak-about guidance: lead with demonstration outcomes (`IDENTITY.md`).

### Exit criteria

- [ ] README architecture section matches three-module rule.
- [ ] COMMAND_CENTER.md describes TTY behavior + screens shipped.
- [ ] Setup/Operations examples use v2 verbs with legacy alias notes.

### Assumptions

- PyPI/package metadata unchanged unless version bump tasked separately.

### Expected QA

- Editorial review against `v2.md` §0− “README must stay on the architecture layer only.”
- Fresh-reader test: can they explain Twin vs memory tool in one minute from README?

### Resources

- `README.md`, `docs/v2.md` §§0−, 12
- `docs/IDENTITY.md` § How Twin should be spoken about

---

## Out of scope / explicit non-tasks (do not invent work)

Unless a new tracker ID is added, do **not**:

- Implement Event entity between Percept and Situation (`v2.md` §10 #14).
- Implement full Inject Observer watcher (only slot — T-074).
- Build ARCTIC code-critique product inside Cognize (`v2.md` §5.1, §10 #16) — ingest external critique outputs as percepts only if needed later.
- Make Twin a query-time KB synthesizer (GBrain mode).
- Auto-confirm Narrative/Stance.
- Store incrementable confidence scalars.
- Replace MCP/Native with the Command Center.
- Remote SSH Twin home management (§12.10 #4).
- Literary L1–L4 narrative ontology as schema (§2.4).

---

## Suggested first slice (if starting cold)

1. T-000, T-001, T-002 (docs lock)  
2. T-010 → T-011 → T-012 → T-013 (schema)  
3. T-020 → T-021 → T-022 → T-023 (LLM-or-halt)  
4. T-030 → T-031…T-038 (pipeline)  
5. T-060 early (stale latch) parallel to late P3  
6. T-040 → T-041 → T-070…T-073 (commit + inject floor)  
7. T-080 → T-081 → T-082 → T-090 (CLI + center)  
8. P11 evals in §10 priority order  

---

*Tracker aligned to `docs/v2.md` — longitudinal narratives, architecture vs pipeline, CLI command center.*

ATTENTION: Do not mention task numbers in any Git resource (PR/release/commit).