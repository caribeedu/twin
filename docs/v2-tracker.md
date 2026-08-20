# Twin v2 Tracker — implementable task inventory

Working tracker for the Twin **v2** product line redesign in [`docs/v2.md`](./v2.md).  
Audience: an implementer (human or LLM) **with no prior chat context**. Every task is sized so another agent can pick it up, implement, and verify without guessing product intent.

**Source of truth for product intent:** `docs/v2.md`  
**Source of truth for current shipped behavior:** `docs/CHANGELOG.md`, `docs/ARCHITECTURE.md`, code under `twin/`  
**This file does not redefine the redesign** — it decomposes it into tasks and maps them to Twin package versions (`v2.0` … `v2.4`).

> **Version wording:** `v2` / `v2.x` always mean the **Twin product version**. `docs/v2.md` is a filename for the redesign note, not a “documentation version.”

---

## How to use this document

1. Read `docs/v2.md` §§0−, 0, 1, 2, 6, 11, 12 before starting any task.
2. Prefer work that unblocks the **next unreleased Twin version** (see [Twin version map](#twin-version-map-package-releases)).
3. Pick the next task whose **Depends on** are all `done`.
4. Do not invent entities, CLI verbs, or fallback cognition paths that contradict the invariants below.
5. Prefer small PRs: one task (or a tightly coupled pair) per PR when possible.
6. Mark status in the task header: `todo` | `in_progress` | `blocked` | `done` | `wontfix`.
7. When every required task for a version is `done` and the release gate passes, cut the package version and record it in `docs/CHANGELOG.md`.

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
3. **No product “memory”.** User-facing / CLI / MCP / Review / Web / docs that define the product use Reflection, Interpretation, Narrative, Stance, Evidence, Situation. Internal `Memory*` dual-read may remain in store code; no argv or primary UI labeled Memory.
4. **Understanding is emergent**, not a schema root / table.
5. **Human gates durability.** Stages 8–9: humans commit Narratives; Cognize proposes. No `extract -A`-style silent Narrative commit.
6. **Stale before Cognize finishes.** When a relevant Percept lands, mark overlapping Narratives `stale` **deterministically** before re-synthesis, so Inject never serves stale-as-fresh.
7. **Confidence is read-time**, never an incrementable stored scalar on Narrative/Reflection.
8. **Retain dissent.** Superseded Interpretations/Evidence stay attached; later corroboration can revive them.
9. **ACL intersection on derived claims.** Narrative visibility ≤ ∩ of contributing source ACLs; revoke → synchronous tombstone of dependents.
10. **Public architecture stays Sense → Cognize → Inject.** Cognize pipeline stages belong in Cognize docs, not the README architecture diagram.

---

## Twin version map (package releases)

`v2.x` below are **Twin product / package versions** (`twin-cognition` / `__version__`), not documentation draft numbers. `docs/v2.md` is the redesign intent for the Twin **v2** line.

A version ships only when **every required task** for that version is `done` and its release gate passes. Engineering phases (P0–P13) are implementation order; versions are the shippable product cuts.

| Twin version | Codename / theme | Product bar (user-visible) | Required tasks | Release gate |
|---|---|---|---|---|
| **v2.0** | Narrative substrate | Sense → Cognize → Inject with committed **Narratives**; LLM-or-halt; human commit; deterministic stale floor; `twin cognize` / `narrative` / `stance` verbs; dual-read of legacy memories | T-000 T-001 T-002 · T-010–T-015 · T-020–T-023 · T-030–T-038 · T-040 T-041 · T-060 T-070 · T-080 T-081 · T-110 | `twin cognize run` halts without LLM; commit Narrative + pack with EpistemicState; stale-injection eval green; package `2.0.0` |
| **v2.1** | Epistemics + host surfaces | Read-time confidence / independence; open Reflections in packs; ACL ∩ + revoke tombstone; Stance drafts; MCP / REST / Native serve v2 pack contract; legacy CLI aliases deprecated | T-050 · T-061 · T-071–T-074 · T-082 · T-100–T-102 · T-111 T-114 | Independence + ACL evals green; MCP/Native pack contract tests green; package `2.1.0` |
| **v2.2** | Consolidation & accessibility | Nightly consolidation judgment (caps); Fade / Remarkable + Trace; quiet-reversal and disagreement-attention evals; research logging for surprise | T-051 T-052 · T-112 T-113 T-115 | Consolidation never auto-commits; fade/trace tests green; package `2.2.0` |
| **v2.3** | Command Center (TUI) | Bare `twin` TUI cockpit (Home / Services / Connectors / Jobs / Cognize / Review / Narratives / Stance / MCP); docs split ARCHITECTURE / COGNIZE / EPISTEMICS / RESEARCH; README architecture-layer only | T-090–T-092 · T-120 T-121 | Non-TTY safe; supervised serve/runtime; docs link audit; package `2.3.0` |
| **v2.4** | Web Command Center | Single-route web cockpit (`twin serve`): browse **all** Cognize entities with purpose-shaped UI; operator panes aligned with TUI Center; retire Memory-as-product UI | T-130–T-139 | Every §2.2 entity list+detail reachable; no Memory nav; REST contract tests green; package `2.4.0` (+ exit-criteria hardening in `2.4.1`) |
| **v2.5** | Package walls | Code packages match Sense / Cognize / Inject (+ store, llm, privacy, interfaces); fold `cognition` → `cognize`; split `memory` / `judgment` by function; MCP names follow product vocabulary | T-140–T-149 | Import graph uses target packages; no product Memory/Judgment nouns in public surfaces; package `2.5.0` |
| **v2.6** | Dual-read schema rename | Retire `MemoryItem` / `memory_id` dual-read names → `StoreClaim` / `claim_id`; migrate tables/columns; MCP `claim_*` only (no `memory_*` / `judgment_*` shims) | T-150–T-152 | Public store API uses claim vocabulary; store/tests/export green; package `2.6.0` |

### Completing this tracker ≠ ROADMAP v3 “Extended Brain”

[`docs/ROADMAP.md`](./ROADMAP.md) places **Extended Brain** (personal domains, voice capture, autobiographical expansion, …) at Twin **v3**. Those items are **not** in this task inventory. Finishing **v2.0–v2.6** completes the redesign in `docs/v2.md` (longitudinal Narratives + Cognize pipeline + Inject receipts + TUI/Web Centers + package walls + **dual-read retirement**) and unblocks v3.

### Version dependency

```text
v2.0  →  v2.1  →  v2.2  →  v2.3 (TUI)  →  v2.4 (Web)  →  v2.5 (Package walls)  →  v2.6 (Dual-read schema)
```


### Per-version checklist (copy into CHANGELOG when cutting)

#### v2.0 — Narrative substrate

- [x] T-000 T-001 T-002
- [x] T-010 T-011 T-012 T-013 T-014 T-015
- [x] T-020 T-021 T-022 T-023
- [x] T-030 T-031 T-032 T-033 T-034 T-035 T-036 T-037 T-038
- [x] T-040 T-041
- [x] T-060 T-070
- [x] T-080 T-081
- [x] T-110
- [x] `__version__ = 2.0.0` + CHANGELOG entry (tag/PyPI when publishing)

#### v2.1 — Epistemics + host surfaces

- [x] T-050 T-061
- [x] T-071 T-072 T-073 T-074
- [x] T-082
- [x] T-100 T-101 T-102
- [x] T-111 T-114
- [x] `__version__ = 2.1.0` + CHANGELOG + tag `v2.1.0`

#### v2.2 — Consolidation & accessibility

- [x] T-051 T-052
- [x] T-112 T-113 T-115
- [x] `__version__ = 2.2.0` + CHANGELOG + tag `v2.2.0`

#### v2.3 — Command Center (TUI)

- [x] T-090 T-091 T-092
- [x] T-120 T-121
- [x] `__version__ = 2.3.0` + CHANGELOG + tag `v2.3.0`

#### v2.4 — Web Command Center

- [x] T-130 T-131 T-132 T-133 T-134
- [x] T-135 T-136 T-137 T-138 T-139
- [x] `__version__ = 2.4.0` + CHANGELOG + tag `v2.4.0`

#### v2.5 — Package walls

- [x] T-140 T-141 T-142 T-143 T-144
- [x] T-145 T-146 T-147 T-148 T-149
- [x] `__version__ = 2.5.0` + CHANGELOG (tag after merge approval)

#### v2.6 — Dual-read schema rename

- [x] T-150 T-151 T-152
- [x] `__version__ = 2.6.0` + CHANGELOG (tag after merge approval)

---

## Engineering phase map (implementation order)

Phases are for dependency ordering inside a version — not alternate version numbers.

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
P13 Web Command Center — single-route entity visibility + operator panes
P14 Package walls — sense / cognize / inject / store / llm / privacy / interfaces
P15 Dual-read schema rename — MemoryItem → StoreClaim vocabulary
```

Phases P3–P5 can overlap with P6–P7 once P1–P2 are done, but Inject must not claim “fresh Narratives” until P1+P6 exist. P13 starts after v2.3 ships. P14 starts after v2.4 ships. P15 starts after v2.5 ships.

---

## Task index

| ID | Twin version | Phase | Title | Status |
|---|---|---|---|---|
| T-000 | **v2.0** | P0 | Lock vocabulary glossary + deprecate “memory” in product copy | done |
| T-001 | **v2.0** | P0 | Rewrite ARCHITECTURE overview to Sense → Cognize → Inject walls | done |
| T-002 | **v2.0** | P0 | Add stub COGNIZE.md / EPISTEMICS.md pointing at v2.md until split | done |
| T-010 | **v2.0** | P1 | Define pydantic/dataclass contracts for v2 entities | done |
| T-011 | **v2.0** | P1 | Store schema migration: tables/columns for v2 entities | done |
| T-012 | **v2.0** | P1 | EpistemicState model without stored confidence scalar | done |
| T-013 | **v2.0** | P1 | Relation types including `same_originating_decision` | done |
| T-014 | **v2.0** | P1 | Migration plan MemoryItem → Narrative/Interpretation dual-read | done |
| T-015 | **v2.0** | P1 | Judgment → Stance rename in store (alias layer) | done |
| T-020 | **v2.0** | P2 | Cognize availability gate (`require_chat_llm`) | done |
| T-021 | **v2.0** | P2 | Remove/disable heuristic meaning as production cognition | done |
| T-022 | **v2.0** | P2 | Remove echo-as-production meaning path | done |
| T-023 | **v2.0** | P2 | Episode pipeline: delete lexical semantic fallbacks; halt instead | done |
| T-030 | **v2.0** | P3 | Cognize orchestrator skeleton + stage report | done |
| T-031 | **v2.0** | P3 | Stage 0 Salience (LLM) | done |
| T-032 | **v2.0** | P3 | Stage 1 Situate (LLM) | done |
| T-033 | **v2.0** | P3 | Stage 2 Raise Reflections (LLM) | done |
| T-034 | **v2.0** | P3 | Stage 3 Form Interpretations (LLM) | done |
| T-035 | **v2.0** | P3 | Stage 4 Cross Reflections (LLM) | done |
| T-036 | **v2.0** | P3 | Stage 5 Cross Interpretations (LLM) | done |
| T-037 | **v2.0** | P3 | Stage 6 Narrative Revision (LLM) + retain dissent | done |
| T-038 | **v2.0** | P3 | Stage 7 Evidence audit + independence Relations | done |
| T-040 | **v2.0** | P4 | Review queue for Interpretations + always-visible Open Reflections | done |
| T-041 | **v2.0** | P4 | Stage 9 Commit Narrative + initial EpistemicState | done |
| T-050 | **v2.1** | P5 | Stage 10 Stance drafts (LLM) + human approve path | done |
| T-051 | **v2.2** | P5 | Stage 11 Consolidation judgment (nightly LLM, caps) | done |
| T-052 | **v2.2** | P5 | Stage 12 Fade / Remarkable + Trace ledger | done |
| T-060 | **v2.0** | P6 | Deterministic stale mark on percept land | done |
| T-061 | **v2.1** | P6 | Source-class + timestamp metadata for invalidation asymmetry | done |
| T-070 | **v2.0** | P7 | Inject pack: attach EpistemicState; refuse stale-as-fresh | done |
| T-071 | **v2.1** | P7 | Read-time confidence + independence display in packs | done |
| T-072 | **v2.1** | P7 | Open Reflections section in packs | done |
| T-073 | **v2.1** | P7 | ACL intersection on Narrative + synchronous revoke tombstone | done |
| T-074 | **v2.1** | P7 | Inject Observer slot (interface reserved, stub OK) | done |
| T-080 | **v2.0** | P8 | Extract CLI handlers to `twin/interfaces/commands/` | done |
| T-081 | **v2.0** | P8 | Introduce `twin cognize` / `narrative` / `stance` / `inject pack` | done |
| T-082 | **v2.1** | P8 | Deprecate aliases: extract, meditate, correlate, judgment, memory | done |
| T-090 | **v2.3** | P9 | Command Center MVP: bare `twin` TUI Home + Services + palette | done |
| T-091 | **v2.3** | P9 | Center: Connectors + Jobs screens | done |
| T-092 | **v2.3** | P9 | Center: Cognize / Review / Narratives / Stance / MCP screens | done |
| T-100 | **v2.1** | P10 | MCP tool rename + pack EpistemicState fields | done |
| T-101 | **v2.1** | P10 | REST / Review workbench Narrative commit UX | done |
| T-102 | **v2.1** | P10 | Native pack injection uses v2 pack contract | done |
| T-110 | **v2.0** | P11 | Eval: stale injection (§9.3 #1) | done |
| T-111 | **v2.1** | P11 | Eval: correlated-source independence collapse (§9.3 #3) | done |
| T-112 | **v2.2** | P11 | Eval: disagreement vs agreement attention (§9.3 #4) | done |
| T-113 | **v2.2** | P11 | Eval: quiet reversal path (§9.3 #2) | done |
| T-114 | **v2.1** | P11 | Eval: ACL intersection (§9.3 #5) | done |
| T-115 | **v2.2** | P11 | Research logging: surprise / explanatory_delta (§9.3 #7) | done |
| T-120 | **v2.3** | P12 | Split docs: ARCHITECTURE / COGNIZE / EPISTEMICS / RESEARCH | done |
| T-121 | **v2.3** | P12 | README stays architecture-layer only; add COMMAND_CENTER.md | done |
| T-130 | **v2.4** | P13 | Web Command Center shell — single route, rail IA | done |
| T-131 | **v2.4** | P13 | REST list/show for all §2.2 entities | done |
| T-132 | **v2.4** | P13 | Narrative + EpistemicState purpose UI | done |
| T-133 | **v2.4** | P13 | Reflection / Interpretation / Situation purpose UI | done |
| T-134 | **v2.4** | P13 | Stance / Evidence / Relation / Trace purpose UI | done |
| T-135 | **v2.4** | P13 | Sense strip — Percepts + Connectors + Jobs in web | done |
| T-136 | **v2.4** | P13 | Unify Review + Commit inside web Center | done |
| T-137 | **v2.4** | P13 | Visual language — entity-coherent design system | done |
| T-138 | **v2.4** | P13 | Docs: WEB_CENTER + REST/COMMAND_CENTER sync | done |
| T-139 | **v2.4** | P13 | QA gate — entity routes, no Memory product UI | done |
| T-140 | **v2.5** | P14 | Docs lock — package target layout + vocabulary | done |
| T-141 | **v2.5** | P14 | `twin.sense` — connectors + sensory | done |
| T-142 | **v2.5** | P14 | `twin.llm` — provider adapters | done |
| T-143 | **v2.5** | P14 | `twin.store` — persistence facade (ex-memory data layer) | done |
| T-144 | **v2.5** | P14 | `twin.inject` — packs + Observer slot | done |
| T-145 | **v2.5** | P14 | Fold `twin.cognition` into `twin.cognize` | done |
| T-146 | **v2.5** | P14 | Split `twin.judgment` → cognize Stance + privacy | done |
| T-147 | **v2.5** | P14 | `privacy` owns Firewall / PII / guardrails | done |
| T-148 | **v2.5** | P14 | `interfaces` absorbs runtime + sovereignty | done |
| T-149 | **v2.5** | P14 | QA gate — imports, MCP names, package `2.5.0` | done |
| T-150 | **v2.6** | P15 | Rename dual-read types (`MemoryItem` → store claim) | done |
| T-151 | **v2.6** | P15 | Migrate store columns / FKs (`memory_id` → claim id) | done |
| T-152 | **v2.6** | P15 | QA gate — API/MCP/export without Memory* product names | done |


---

# Tasks

---

## T-000 — Lock vocabulary glossary + deprecate “memory” in product copy

**Twin version:** `v2.0` · **Phase:** P0 · **Status:** `done`  
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

- [x] `GLOSSARY.md` contains every entity in `v2.md` §2.2 table with lifecycle one-liners matching the redesign.
- [x] `COGNITION.md` explains Understanding as emergent and points Situation Model → Situation + Narrative (WorkEpisode called out as legacy carrier).
- [x] No new doc introduced in this task uses “memory” as a product noun in headings or CLI examples (academic citations in FOUNDATIONS/RESEARCH may still say “memory”).
- [x] A one-paragraph “Migration note” in GLOSSARY lists deprecated terms → replacements.

### Assumptions

- `docs/v2.md` remains authoritative; this task only mirrors settled naming.
- Existing code still uses `MemoryItem` / store claim rows — docs may say “code still uses Memory* until T-014 / T-150.”
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

**Twin version:** `v2.0` · **Phase:** P0 · **Status:** `done`  
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

- [x] Opening architecture diagram / mermaid shows exactly three modules.
- [x] Hard-wall table present (Sense / Cognize / Inject owns / must not).
- [x] No README-bound architecture language lists Cognize stages as peer modules.
- [x] Threat-model and firewall sections still present and consistent with fail-closed Inject firewall + Cognize LLM-or-halt.
- [x] Cross-links to `v2.md` for pipeline detail.

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

**Twin version:** `v2.0` · **Phase:** P0 · **Status:** `done`  
**Depends on:** T-001  
**Blocks:** T-120

### Description

Create:

- `docs/COGNIZE.md` — stub: stage map table from `v2.md` §2.1, entity list, “implementation tracked in v2-tracker”; link to `v2.md` §2 for full contracts until code lands.
- `docs/EPISTEMICS.md` — stub: EpistemicState fields, stale timing, read-time confidence, independence, ACL intersection, retain dissent — all from `v2.md` §§2.3, 3.4, 6.

Do **not** duplicate the entire academic §5 into RESEARCH yet (T-120). Add a short “See also RESEARCH.md / v2.md §5” pointer.

Update `docs/RESEARCH.md` with a “v2 redesign hypotheses” subsection listing the falsifiable claims that experiments in P11 will test (stale floor, independence collapse, quiet reversal, disagreement attention) without claiming they are proven.

### Exit criteria

- [x] Both new files exist and are linked from ARCHITECTURE.md and the docs table in README (or OPERATIONS index).
- [x] Stubs do not invent schemas beyond `v2.md`.
- [x] RESEARCH.md lists experiment IDs matching T-110–T-115.

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

**Twin version:** `v2.0` · **Phase:** P1 · **Status:** `done`  
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

- [x] Types importable; unit tests construct valid and reject invalid Relation types.
- [x] `NarrativeRevisionDecision.outcome` enum matches `integrate \| branch \| contradict \| supersede \| keep_separate \| defer`.
- [x] Docstrings cite `docs/v2.md` §2.2 / §10.
- [x] No `MemoryItem` / `StoreClaim` subclass pretending to be Narrative without an explicit `LegacyMemoryAdapter` name.

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

**Twin version:** `v2.0` · **Phase:** P1 · **Status:** `done`  
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

- [x] CRUD round-trips on SQLite and Postgres CI jobs.
- [x] Vault isolation test: writing Relation/Narrative in vault A is invisible when querying as vault B without cross-domain flag.
- [x] `twin backup create` / export includes new entities (or explicitly documents “empty until first cognize”).
- [x] Schema version bump recorded where the project tracks migrations.

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

**Twin version:** `v2.0` · **Phase:** P1 · **Status:** `done`  
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

- [x] Cannot persist Narrative EpistemicState with a required `confidence` column (schema review).
- [x] Unit tests: adding a `same_originating_decision` edge among four agreeing sources does **not** increase derived independent-origin count.
- [x] Marking `status=stale` with reason is a deterministic store update (no LLM).

### Assumptions

- Stage 7 may refresh `independence_sketch`; Inject always recomputes display via helpers (T-071).

### Expected QA

- Table-driven tests for independence collapse and dissent retention (evidence_ids still contain loser ids after supersede — when Commit exists; until then test helper contracts with fixtures).

### Resources

- `docs/v2.md` §§2.3, 3.4, 6
- `docs/EPISTEMICS.md` (stub from T-002)

---

## T-013 — Relation types including `same_originating_decision`

**Twin version:** `v2.0` · **Phase:** P1 · **Status:** `done`  
**Depends on:** T-010, T-011  
**Blocks:** T-035, T-036, T-037, T-038, T-071

### Description

Persist Relations with LLM provenance metadata (model id, prompt/schema version, rationale). Special-case documentation and validation for **`same_originating_decision`**:

- It is a **causal** Relation, not similarity.
- Cheap pre-hints allowed (shared time window + actors/artifacts/tokens) but **final assertion requires LLM stage** when Cognize runs (Stage 7).
- Embeddings alone must not create causal Relations.

Provide query helpers: neighbors by type, collapse independent-origin sets for Inject display.

### Exit criteria

- [x] Enum rejects unknown types.
- [x] Test: creating `same_originating_decision` without `asserted_by=llm` fails closed in production API (tests may inject with explicit test flag / override similar to `set_stage_override` today).
- [x] Narrative↔Narrative `part-of` / `continues` / `supersedes` supported for composition (`v2.md` §2.4).

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

**Twin version:** `v2.0` · **Phase:** P1 · **Status:** `done`  
**Depends on:** T-011, T-012  
**Blocks:** T-040, T-081, T-100

### Description

Ship an explicit dual-read adapter so existing confirmed `StoreClaim`s remain usable while Cognize writes Narratives:

1. Document mapping:
   - confirmed Memory (decision/event/fact…) → provisional **Narrative** or **Interpretation** (choose one rule and stick to it; recommended: confirmed memories become Narratives with EpistemicState `freshness_boundary=valid_from`, flagged `migrated_from_memory=true`; candidates become Interpretations `competing`).
2. Pack/search code paths can read both during migration.
3. Write path for new cognition goes to v2 entities only once Cognize pipeline is on (P3+).
4. Provide `twin narrative backfill-from-memories --dry-run|--apply` (or store method) — **does not** invent new meaning; copies existing confirmed claims.
5. Deprecation warnings when APIs return Memory-shaped payloads.

Do **not** delete memory tables in this task.

### Exit criteria

- [x] Written ADR/section in `docs/COGNIZE.md` or tracker note describing the mapping 1:1.
- [x] Dual-read pack fixture: old DB with only memories still produces a pack (legacy) OR empty Narratives with clear “migration required” — pick one behavior and test it; prefer dual-read so v1 users do not brick.
- [x] `--dry-run` backfill prints counts; `--apply` is idempotent.

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

**Twin version:** `v2.0` · **Phase:** P1 · **Status:** `done`  
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

- [x] `twin stance list` works; `twin judgment list` warns deprecation and returns same data.
- [x] Existing judgment tests pass via aliases.
- [x] Pack JSON includes Stance naming per chosen compatibility policy (tested).

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

**Twin version:** `v2.0` · **Phase:** P2 · **Status:** `done`  
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

- [x] With LLM stopped: cognize/extract/meditate semantic paths halt; percepts remain pending/deferred — **no new review candidates invented by heuristics in interpreting modes**.
- [x] Status command/API shows last halt reason + timestamp.
- [x] Unit test covers each halt reason.

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

**Twin version:** `v2.0` · **Phase:** P2 · **Status:** `done`  
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

- [x] Test: `TWIN_EXTRACTOR=heuristic` + `twin cognize`/`extract` does not insert StoreClaims or Interpretations; returns blocked/halt.
- [x] CI still has a deterministic stand-in for tests via **authored overrides** / recorded fixtures (like `set_interpreter_override`), not lexical meaning.
- [x] CHANGELOG/OPERATIONS note the behavior change.

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

**Twin version:** `v2.0` · **Phase:** P2 · **Status:** `done`  
**Depends on:** T-020  
**Blocks:** T-030

### Description

Echo extractor/interpreter is a **test double**, not a production cognition backend. Ensure:

1. Production config cannot select echo as a real understanding engine without an explicit `TWIN_ALLOW_ECHO_COGNITION=1` test-only flag (or remove from production enum entirely).
2. Docs state echo classifies nothing meaningful (already true in v0.7) and cannot satisfy Cognize.
3. Any code path that treated echo completions as “LLM up” for gate purposes must not count as satisfying `require_chat_llm` unless the test flag is set.

### Exit criteria

- [x] Default install / `twin init` never configures echo.
- [x] Gate treats echo as halt in production.
- [x] Tests that need deterministic cognition use stage overrides / recorded LLM fixtures.

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

**Twin version:** `v2.0` · **Phase:** P2 · **Status:** `done`  
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

- [x] No production path writes phase/edge with `method` implying lexical understanding when LLM down.
- [x] Tests for deferral remain green; any test that expected lexical phases updated.
- [x] OPERATIONS.md notes halt behavior.

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

**Twin version:** `v2.0` · **Phase:** P3 · **Status:** `done`  
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

- [x] `twin cognize run --dry-run` (or python API) prints stage plan and halt if no LLM.
- [x] Report schema stable enough for CLI `--json`.
- [x] Unit test: LLM down → all cognitive stages halted, zero entity writes.
- [x] Unit test: LLM up with all stages stubbed `skipped` still persists nothing durable except optional run record.

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

**Twin version:** `v2.0` · **Phase:** P3 · **Status:** `done`  
**Depends on:** T-030  
**Blocks:** T-032

### Description

LLM decides whether a percept batch deserves Cognize budget now: drop / defer / proceed with salience score/rationale.

Inputs: percept batch (PII-masked if cloud), source class, vault.  
Outputs: per-item or batch salience marks persisted; dropped items do not proceed to Situate.

No keyword classifier as authority. Prompt/schema versioned. Test override hook required.

### Exit criteria

- [x] Live LLM path + `set_stage_override("salience", …)` for CI.
- [x] Dropped percepts remain available for a future run (not deleted).
- [x] Halt if LLM fails mid-stage (no partial silent success without record).

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

**Twin version:** `v2.0` · **Phase:** P3 · **Status:** `done`  
**Depends on:** T-031, T-011  
**Blocks:** T-033

### Description

LLM assigns percepts to Situation clusters (create/join/conclude). No Event entity (`v2.md` §10 #14). Vault-scoped. Temporal proximity alone must not force merge without model judgment (align with correlation non-goals).

Persist Situation membership. Reuse lessons from WorkEpisode clustering but **do not** auto-write Memory.

### Exit criteria

- [x] Situations CRUD via stage output.
- [x] Cross-vault situate refused.
- [x] Override tests for join vs new situation.

### Assumptions

- Old WorkEpisode can remain; Situate may later replace episode identity — do not dual-write episodes unless needed for dual-read.

### Expected QA

- Multi-percept batch fixtures (Slack+GitHub) create one Situation when override says so; two when override separates.

### Resources

- `docs/v2.md` §§2.1, 2.2, 10 #14
- `twin/cognition/correlation/episodes.py`, `partition.py`

---

## T-033 — Stage 2 Raise Reflections (LLM)

**Twin version:** `v2.0` · **Phase:** P3 · **Status:** `done`  
**Depends on:** T-032  
**Blocks:** T-034, T-035

### Description

LLM raises open Reflections (questions / tensions / unresolved framings) for Situations — **few** high-value gaps, not one factoid per sentence.

Prioritize by expected learning progress / uncertainty (`v2.md` §5 curiosity refs as design criteria in prompts — not a numeric library).

Status `open` by default. Always visible in Review later (T-040).

### Exit criteria

- [x] Reflections persisted; linked to situations/percepts.
- [x] Prompt forbids inventing Reflections that are not grounded in provided batch/situation brief.
- [x] CI override can emit canonical Reflection set.

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

**Twin version:** `v2.0` · **Phase:** P3 · **Status:** `done`  
**Depends on:** T-033  
**Blocks:** T-036, T-037

### Description

LLM forms competing **Interpretations** (candidate explanations) for Reflections/Situations — not “answers to user queries,” not StoreClaim review candidates.

Each Interpretation must cite Evidence anchors (percept spans). Ungrounded items dropped (deterministic validation).

Status starts `competing`. Multiple Interpretations per Reflection allowed.

### Exit criteria

- [x] Ungrounded interpretation dropped with counter.
- [x] No auto-promote to Narrative.
- [x] Schema distinguishes Interpretation from Narrative in storage.

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

**Twin version:** `v2.0` · **Phase:** P3 · **Status:** `done`  
**Depends on:** T-033, T-013  
**Blocks:** T-037

### Description

LLM links Reflections: `same-as` / `related` / conflict-of-asks. Collapse duplicates to canonical open Reflection; supersede losers with provenance (do not delete history).

### Exit criteria

- [x] Relations written with rationales.
- [x] Canonical Reflection id stable under re-run (idempotent).
- [x] Review can see merged history.

### Assumptions

- Embeddings may propose candidates to the LLM brief but cannot alone assert `same-as`.

### Expected QA

- Five paraphrased questions → one canonical Reflection in override test.

### Resources

- `docs/v2.md` §3.1–3.3

---

## T-036 — Stage 5 Cross Interpretations (LLM)

**Twin version:** `v2.0` · **Phase:** P3 · **Status:** `done`  
**Depends on:** T-034, T-013  
**Blocks:** T-037

### Description

LLM relates Interpretations: `same-as` / `supports` / `contradicts` / evidence overlap. Weight disagreement; do not treat echo agreement as strong confirmation.

### Exit criteria

- [x] Contradict Relations retained for Stage 6.
- [x] Idempotent re-cross on same set.
- [x] Metrics/counters for support vs contradict edges.

### Assumptions

- `same_originating_decision` primarily Stage 7, but Stage 5 may hint overlaps.

### Expected QA

- Fixture with two contradictory explanations under one Reflection → `contradicts` edge.

### Resources

- `docs/v2.md` §§3.1, 3.4

---

## T-037 — Stage 6 Narrative Revision (LLM) + retain dissent

**Twin version:** `v2.0` · **Phase:** P3 · **Status:** `done`  
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

- [x] Decision objects persisted and attached to review clusters.
- [x] Supersede outcome lists `retained_dissent_ids` non-empty when a loser exists.
- [x] Override tests for each outcome at least once.
- [x] Logging hooks for research (§9.3 #7) — even if full eval is T-115.

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

**Twin version:** `v2.0` · **Phase:** P3 · **Status:** `done`  
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

- [x] Multi-source fixture collapses to one independent origin when LLM override says same decision.
- [x] Evidence ids include dissenting spans.
- [x] Production refuses to set `narrative.confidence += x`.

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

**Twin version:** `v2.0` · **Phase:** P4 · **Status:** `done`  
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

- [x] Open Reflections section always rendered when any exist (CLI + API).
- [x] Commit path calls Stage 9 API (T-041) — if T-041 not merged, gate behind feature flag but UI wired.
- [x] Legacy memory review still reachable via deprecated mode during migration, with warning banner.

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

**Twin version:** `v2.0` · **Phase:** P4 · **Status:** `done`  
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

- [x] Commit without evidence fails closed.
- [x] Commit without human actor fails closed.
- [x] Idempotent commit token / preview fingerprint (mirror judgment preview pattern).
- [x] Pack-eligible Narratives are committed+fresh (or explicitly stale-labeled — never silent stale).

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

**Twin version:** `v2.1` · **Phase:** P5 · **Status:** `done`  
**Depends on:** T-041, T-015  
**Blocks:** T-082

### Description

After Narrative commit, LLM may draft pending **Stance** proposals (how to evaluate similar cases). Human approve via `twin stance …` (judgment aliases). Constitutional flags unchanged in spirit.

Prompts must not treat Stance as factual Narrative.

### Exit criteria

- [x] Drafts are pending until approve.
- [x] Pack `applicable_stance` uses approved items only.
- [x] Tests for propose-from-narrative parallel to `propose_from_episode`.

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

**Twin version:** `v2.2` · **Phase:** P5 · **Status:** `done`  
**Depends on:** T-030, T-041  
**Blocks:** none critical

### Description

Nightly/weekly job: LLM argues what should generalize vs stay episodic; emits consolidation tags / promote drafts; **humans still gate durability**.

Caps: max drafts per vault/night; max tokens; skip if LLM halted.

Retarget `twin consolidate daily|weekly` to this stage (legacy schedule OK). Never confirm Narrative/Stance automatically (`ConsolidationInvariantError` spirit preserved).

### Exit criteria

- [x] Caps enforced and tested.
- [x] Idempotent window apply (`duplicated=True`) preserved.
- [x] Halt if no LLM — job retryable, no heuristic consolidation meaning.

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

**Twin version:** `v2.2` · **Phase:** P5 · **Status:** `done`  
**Depends on:** T-041  
**Blocks:** none critical

### Description

1. Append-only **Trace** of retrieval/use events (Inject packs, search hits, review opens).
2. LLM recommends accessibility: remarkable / ordinary / fading / archive stub — **not** cron-delete-by-age alone.
3. Recommendations enqueue review; do not silently delete Narratives.

### Exit criteria

- [x] Trace written on pack serve.
- [x] Fade recommendations visible in Review/CLI.
- [x] Age-only deletion of Narratives does not exist as Cognize policy.

### Assumptions

- Retention of raw connector artifacts remains Sense/sovereignty concern.

### Expected QA

- Trace append idempotency / volume smoke test.
- Override test for remarkable pin when Stance-linked.

### Resources

- `docs/v2.md` §§2.1, 4, 5 (forgetting / tag-and-capture)

---

## T-060 — Deterministic stale mark on percept land

**Twin version:** `v2.0` · **Phase:** P6 · **Status:** `done`  
**Depends on:** T-012, T-011  
**Blocks:** T-070, T-110

### Description

When a Percept is committed by Sense into a domain/vault that overlaps a committed Narrative:

1. **Before** Cognize runs, set Narrative EpistemicState `status=stale`, fill `stale_reason`, append percept id to `unseen_since`.
2. No LLM.
3. Overlap definition: shared vault + domain/project/entity/situation membership heuristic documented in EPISTEMICS — start conservative (same vault + overlapping project/domain tags or explicit situation link).
4. Orchestrator order in T-030 must call this first.

### Exit criteria

- [x] Test: insert percept → Narrative becomes stale without LLM configured.
- [x] Inject path (even stub) can detect stale immediately.
- [x] Re-synthesis / commit clears stale and refreshes freshness_boundary (integration with T-041).

### Assumptions

- False-positive stale is safer than false-fresh; tune overlap later via experiments.

### Expected QA

- Concurrent percept insert + pack request race: pack must not claim fresh if stale mark committed.

### Resources

- `docs/v2.md` §§2.3, 3.2, 6, 10 #10
- Sense write paths: connectors finalize, `twin/sensory/`, session_complete percept insert

---

## T-061 — Source-class + timestamp metadata for invalidation asymmetry

**Twin version:** `v2.1` · **Phase:** P6 · **Status:** `done`  
**Depends on:** T-060  
**Blocks:** T-113

### Description

Ensure every Percept carries durable **source class** (e.g. `code_repo`, `chat_discussion`, `meeting`, `mail`, `calendar`, `document`, `session_residue`) and reliable timestamps so Cognize/Inject can treat lifetimes differently (code often self-invalidates; discussion may reverse quietly).

Document the enum; map connectors → classes; forbid missing class on new writes (default `unknown` + review flag).

### Exit criteria

- [x] Connector normalizers set source class.
- [x] Session residue percepts labeled distinctly.
- [x] EPISTEMICS.md documents asymmetry policy.

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

**Twin version:** `v2.0` · **Phase:** P7 · **Status:** `done`  
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

- [x] Contract test: stale Narrative cannot appear in `active` without `epistemic.status=stale`.
- [x] Golden pack JSON schema includes epistemic fields.
- [x] Blocked items still ids/reasons only (no leak).

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

**Twin version:** `v2.1` · **Phase:** P7 · **Status:** `done`  
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

- [x] Correlated-source fixture displays K=1 when Relations say so.
- [x] Pack schema documents derived fields as derived.
- [x] Unit tests do not require LLM (use stored Relations fixtures).

### Assumptions

- Stage 7 quality affects Relations richness; Inject must still derive something sensible with sparse Relations (show uncertainty).

### Expected QA

- Table tests for derive_* helpers + pack integration snapshot.

### Resources

- `docs/v2.md` §§2.3, 3.4, 6

---

## T-072 — Open Reflections section in packs

**Twin version:** `v2.1` · **Phase:** P7 · **Status:** `done`  
**Depends on:** T-070, T-033  
**Blocks:** none

### Description

Settled decision (`v2.md` §10 #4): packs include Open Reflections in an uncertainty section (policy-filtered by firewall).

### Exit criteria

- [x] Open reflections appear when allowed by domain firewall.
- [x] Restricted reflections blocked with reasons, not content.
- [x] Section named without “memory.”

### Assumptions

- Ranking may be simple (salience/recency) initially.

### Expected QA

- Firewall tests for reflection domain tags.
- Pack size budget still respected (`max_tokens`).

### Resources

- `docs/v2.md` §10 #4, §6

---

## T-073 — ACL intersection on Narrative + synchronous revoke tombstone

**Twin version:** `v2.1` · **Phase:** P7 · **Status:** `done`  
**Depends on:** T-041  
**Blocks:** T-114

### Description

1. On Commit Narrative, compute ACL / sensitivity / vault visibility as **intersection** of contributing Evidence/source ACLs (private Slack ∩ public PR → private).
2. Cognize must refuse to write a claim that expands permissions beyond inputs.
3. On source revoke/delete: **synchronously tombstone** dependent Narratives/Interpretations (or mark tombstoned EpistemicState) — no async “eventually consistent leftover truth” for MVP (`v2.md` §10 #12).
4. Align with Domain Firewall + privacy engine (`twin/privacy/**`).

### Exit criteria

- [x] ACL stress test: user without Slack ACL cannot see derived Narrative from private Slack + public PR.
- [x] Delete-source / revoke path tombstones dependents in same request transaction.
- [x] Audit log entries for tombstones.

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

**Twin version:** `v2.1` · **Phase:** P7 · **Status:** `done`  
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

- [x] Interface exists; default stub wired; no heuristic fake observe.
- [x] Docs mark Observer as reserved Inject LLM slot.
- [x] Tests ensure stub cannot write Cognize entities.

### Assumptions

- Native search-vote domain resolution may remain temporary hot-path until Observer exists — document as transitional, not Observer.

### Expected QA

- Import/smoke test; capability flag in MCP `capabilities`.

### Resources

- `docs/v2.md` §6
- `twin/cognition/observer.py` (legacy Memory Observer — clarify rename vs Inject Observer in docs to avoid collision; consider `inject_observer.py`)

---

## T-080 — Extract CLI handlers to `twin/interfaces/commands/`

**Twin version:** `v2.0` · **Phase:** P8 · **Status:** `done`  
**Depends on:** none (can start early)  
**Blocks:** T-081, T-090

### Description

Refactor `twin/interfaces/cli.py` monolith: move business handlers into `twin/interfaces/commands/` modules (ingest, cognize, review, connectors, runtime, …). Argparse remains thin.

**Mandate:** TUI and argparse call the **same** functions — no forked logic (`v2.md` §12.6).

Handlers live in `twin/interfaces/commands/cli_handlers.py` (+ `cognize_cmd.py` / `pack_cmd.py` for Cognize surface). `cli.py` is registration + parsing.

### Exit criteria

- [x] `cli.py` mostly registration + parsing.
- [x] `pytest` / smoke CLI commands still work (`cognize`/`narrative` help + pack path).
- [x] Public function signatures in `twin/interfaces/commands/` suitable for TUI reuse.

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

**Twin version:** `v2.0` · **Phase:** P8 · **Status:** `done`  
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

- [x] Help text lists v2 verbs prominently.
- [x] `cognize run` respects LLM-or-halt.
- [x] `narrative show` prints EpistemicState.
- [x] Docs CLI.md updated for new verbs (legacy appendix can wait for T-082).

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

**Twin version:** `v2.1` · **Phase:** P8 · **Status:** `done`  
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

- [x] Each legacy command warns once per invocation.
- [x] CI scripts using meditate still work via alias.
- [x] Auto-approve path cannot commit Narrative.
- [x] CLI.md “Legacy aliases” appendix exists.

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

**Twin version:** `v2.3` · **Phase:** P9 · **Status:** `done`  
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

- [x] `twin` on TTY opens center; `echo | twin` does not hang in TUI.
- [x] Starting serve from Services shows URL; stop works.
- [x] Runtime attach-vs-start rule implemented.
- [x] `docs/COMMAND_CENTER.md` stub or § in CLI.md describing MVP.

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

**Twin version:** `v2.3` · **Phase:** P9 · **Status:** `done`  
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

- [x] Backfill progress visible without leaving TUI.
- [x] Destructive connector revoke still requires confirm.
- [x] Jobs use same runtime queue as CLI.

### Assumptions

- Webhooks remain HTTP-side; Center does not replace them.

### Expected QA

- Operator script: add fake/github connector in dry environment if available; or mock job progress unit tests.

### Resources

- `docs/v2.md` §§12.2, 12.5
- `twin/connectors/service.py`, `twin/runtime/**`

---

## T-092 — Center: Cognize / Review / Narratives / Stance / MCP screens

**Twin version:** `v2.3` · **Phase:** P9 · **Status:** `done`  
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

- [x] Each screen calls shared command functions (no duplicated store logic).
- [x] Review shows open Reflections.
- [x] Cognize screen surfaces halt reason when LLM down.

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

**Twin version:** `v2.1` · **Phase:** P10 · **Status:** `done`  
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

- [x] MCP.md documents v2 fields and deprecations.
- [x] Contract tests for pack payload.
- [x] Old tool names still work briefly with deprecation note in response metadata.

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

**Twin version:** `v2.1` · **Phase:** P10 · **Status:** `done`  
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

- [x] OpenAPI lists Narrative commit endpoint.
- [x] UI cannot commit without evidence + confirm.
- [x] Stale badge visible on stale narratives.

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

**Twin version:** `v2.1` · **Phase:** P10 · **Status:** `done`  
**Depends on:** T-070, T-100  
**Blocks:** none

### Description

Claude Code native hooks inject packs built with the v2 contract (EpistemicState, stale floor, open reflections). Hot-path deadlines remain. Fail-open behavior unchanged. Session residue still flows Sense → cognize enqueue — not Cognize talking to host.

Clarify in NATIVE.md: conversation uses Sense+Inject edges; no session “mode.”

### Exit criteria

- [x] Native pack JSON includes epistemic fields when domain known.
- [x] Stale narratives not injected as fresh.
- [x] Fake-host evals updated.

### Assumptions

- Domain search-vote may remain until Observer exists.

### Expected QA

- `tests/interfaces/native/**` + evals/native lifecycle.

### Resources

- `docs/NATIVE.md`, `docs/v2.md` §§1, 6
- `twin/interfaces/native/**`, `twin/cognition/host_session.py`

---

## T-110 — Eval: stale injection (§9.3 #1)

**Twin version:** `v2.0` · **Phase:** P11 · **Status:** `done`  
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

- [x] Eval case under `evals/` with pass/fail assertions.
- [x] Wired into `twin eval` or pytest.
- [x] Failure message explains which floor broke.

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

**Twin version:** `v2.1` · **Phase:** P11 · **Status:** `done`  
**Depends on:** T-071, T-038  
**Blocks:** none

### Description

Fixture: meeting + roadmap + calendar + commit from **one** decision. Assert independence summary collapses to one origin and derived confidence does not treat four echoes as four votes.

Use Relation overrides if LLM not in CI.

### Exit criteria

- [x] Assert K independent origins == 1.
- [x] Assert display string / structure matches.
- [x] Counter-example: truly independent contradicting source increases attention / does not collapse incorrectly.

### Assumptions

- Stage 7 override available.

### Expected QA

- Pure pytest table tests + one integration eval.

### Resources

- `docs/v2.md` §§9.3 #3, 3.4

---

## T-112 — Eval: disagreement vs agreement attention (§9.3 #4)

**Twin version:** `v2.2` · **Phase:** P11 · **Status:** `done`  
**Depends on:** T-037  
**Blocks:** none

### Description

Single contradicting artifact (e.g. PR for Feature B while Narrative says Feature A) must produce Stage 6 attention / outcome stronger than three agreeing echoes (measured via decision outcome, surprise field, or review priority — define metric in eval).

### Exit criteria

- [x] Metric documented and asserted.
- [x] Echo-agreement control fixture included.

### Assumptions

- LLM override can set surprise=high on disagreement path.

### Expected QA

- Deterministic overrides in CI.

### Resources

- `docs/v2.md` §§9.3 #4, 3.4

---

## T-113 — Eval: quiet reversal path (§9.3 #2)

**Twin version:** `v2.2` · **Phase:** P11 · **Status:** `done`  
**Depends on:** T-037, T-061  
**Blocks:** none

### Description

Known-wrong Narrative invalidated by a quiet meeting percept with **little subsequent discussion**. Assert system raises challenger / marks need for revision rather than relying on recency TTL alone.

### Exit criteria

- [x] Challenger Interpretation or open Reflection exists.
- [x] Prior Narrative retained (dissent) if superseded in fixture’s later step.
- [x] Eval distinguishes drift (lots of talk) vs quiet reversal fixtures.

### Assumptions

- Sense coverage prerequisite: meeting percept must exist.

### Expected QA

- Two fixtures side-by-side in eval folder.

### Resources

- `docs/v2.md` §§3.4, 7, 9.3 #2

---

## T-114 — Eval: ACL intersection (§9.3 #5)

**Twin version:** `v2.1` · **Phase:** P11 · **Status:** `done`  
**Depends on:** T-073  
**Blocks:** none

### Description

Private Slack fact + public PR → derived Narrative must not be visible to a principal lacking Slack ACL.

### Exit criteria

- [x] Pack/search deny with reason.
- [x] Canary/leakage tests fail closed if content appears.

### Assumptions

- Test principals/personas exist in privacy test harness.

### Expected QA

- `tests/privacy` + eval wrapper.

### Resources

- `docs/v2.md` §§6, 9.3 #5
- `tests/privacy/test_engine.py`

---

## T-115 — Research logging: surprise / explanatory_delta (§9.3 #7)

**Twin version:** `v2.2` · **Phase:** P11 · **Status:** `done`  
**Depends on:** T-037  
**Blocks:** none

### Description

Not a ship gate for product, but required instrumentation:

- Persist Stage 6 `surprise` + `explanatory_delta` + outcome for analysis
- Exportable via stats/usage
- RESEARCH.md describes hypothesis: explanatory-power optimization vs support-accumulation baseline

### Exit criteria

- [x] Fields queryable from store/CLI.
- [x] RESEARCH.md hypothesis section updated.
- [x] No product dependency on this metric for Inject floor.

### Assumptions

- May run only when Cognize runs with real LLM.

### Expected QA

- Unit test that decisions persist research fields.

### Resources

- `docs/v2.md` §§9.3 #7, 10 #15
- `docs/RESEARCH.md`

---

## T-120 — Split docs: ARCHITECTURE / COGNIZE / EPISTEMICS / RESEARCH

**Twin version:** `v2.3` · **Phase:** P12 · **Status:** `done`  
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

- [x] No critical implementer info lives only in outdated stubs.
- [x] README docs table updated.
- [x] Academic claims absent from README.

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

**Twin version:** `v2.3` · **Phase:** P12 · **Status:** `done`  
**Depends on:** T-120, T-090  
**Blocks:** none (release documentation gate)

### Description

1. README public story: Sense → Cognize → Inject; longitudinal Narratives; no Cognize stage laundry list; no academic dump.
2. Identity vs GBrain differentiation short table OK.
3. Add `docs/COMMAND_CENTER.md` from §12 (or finalize stub).
4. Update OPERATIONS quickstart to `twin cognize` / review Narrative commit.
5. Speak-about guidance: lead with demonstration outcomes (`IDENTITY.md`).

### Exit criteria

- [x] README architecture section matches three-module rule.
- [x] COMMAND_CENTER.md describes TTY behavior + screens shipped.
- [x] Setup/Operations examples use v2 verbs with legacy alias notes.

### Assumptions

- PyPI/package metadata unchanged unless version bump tasked separately.

### Expected QA

- Editorial review against `v2.md` §0− “README must stay on the architecture layer only.”
- Fresh-reader test: can they explain Twin vs memory tool in one minute from README?

### Resources

- `README.md`, `docs/v2.md` §§0−, 12
- `docs/IDENTITY.md` § How Twin should be spoken about

---

## T-130 — Web Command Center shell — single route, rail IA

**Twin version:** `v2.4` · **Phase:** P13 · **Status:** `done`  
**Depends on:** T-092, T-101, T-121  
**Blocks:** T-132–T-137, T-139

### Description

Replace the fragmented hash workbench (`#home` / `#review` / `#memories` / …) with one **Command Center** SPA served by `twin serve`:

```text
/   ← only product route (hash or client path segments are panes, not separate apps)
├── Rail (always visible): Home · Explore · Review · Cognize · Sense · Inject · Ops
├── Main: active pane
└── Detail: selected entity inspector (slides/splits — never a second app)
```

- Mirror TUI Center information architecture (`v2.md` §12.3) where it makes sense in the browser.
- **Explore** is the entity cockpit: pick a type → browse → open detail without leaving `/`.
- Deep-links: `#explore/narrative/<id>`, `#review`, `#cognize`, etc. still resolve inside the same shell.
- Retire primary nav label **Memories**; dual-read rows may appear only as migration affordance under Explore if needed, never as a product tab.
- Home rail: doctor summary, open Reflections count, cognize halt, serve/runtime attach status (read-only if TUI owns supervision).

### Exit criteria

- [x] `twin serve` loads a single shell; all panes switch without full reload.
- [x] Nav has no “Memories” product entry.
- [x] Rail includes Explore + Review + Cognize + Sense + Inject + Ops (names may shorten; purposes fixed).
- [x] Deep-link to a Narrative id opens Explore detail in-shell.

### Assumptions

- TUI Center remains the process supervisor; web Center is visibility + human gates (review/commit/approve), not a second job runner unless Ops already exposes enqueue via REST.
- Keep static HTML/JS/CSS under `twin/interfaces/web/` unless a later task introduces a build step (out of scope unless needed for design system).

### Expected QA

- Manual: open `/`, walk every rail item, browser back/forward works.
- Automated: smoke that index serves and shell markers exist (no Memory nav string).

### Resources

- `docs/v2.md` §§2.2, 12.1–12.3, 9.4
- `docs/COMMAND_CENTER.md`, `twin/interfaces/web/static/{index.html,app.js}`

---

## T-131 — REST list/show for all §2.2 entities

**Twin version:** `v2.4` · **Phase:** P13 · **Status:** `done`  
**Depends on:** T-010, T-011, T-012, T-013  
**Blocks:** T-132–T-135, T-139

### Description

Expose stable HTTP list + show (and minimal filter) for every Cognize entity in `v2.md` §2.2:

| Entity | Minimum API |
|---|---|
| Percept | list (vault/source filters), show |
| Situation | list, show (+ member percept ids) |
| Reflection | list (`status=open` default), show |
| Interpretation | list (`competing` filter), show |
| Relation | list by endpoint id / type, show |
| Narrative | list, show (+ embedded EpistemicState summary) |
| EpistemicState | show by narrative (or embedded — no orphan CRUD) |
| Stance | list, show, proposals list |
| Evidence | list by narrative/interpretation, show |
| Trace | list recent for a narrative / vault |

Rules:

- Response shapes use product vocabulary (no “memory” field names in JSON keys meant for UI).
- Read-time confidence / independence only on Narrative (and pack) responses — computed, not stored scalar.
- Pagination + vault scope on every list.
- Reuse store methods; do not invent parallel schemas.

### Exit criteria

- [x] Each entity above has documented list+show in `docs/REST.md`.
- [x] Contract tests cover 200 shapes and empty lists.
- [x] Narrative show includes epistemic status + evidence_ids + grain when present.

### Assumptions

- Write/mutate paths for commit Narrative / approve Stance already exist; this task is **read visibility** first. Mutations stay on existing commit/approve endpoints (extended in T-136 if needed).

### Expected QA

- `pytest` REST contract suite for new routes.
- OpenAPI or REST.md table matches handlers.

### Resources

- `docs/v2.md` §2.2–2.3, `docs/REST.md`, `twin/interfaces/` HTTP routers

---

## T-132 — Narrative + EpistemicState purpose UI

**Twin version:** `v2.4` · **Phase:** P13 · **Status:** `done`  
**Depends on:** T-130, T-131, T-070, T-071  
**Blocks:** T-139

### Description

Explore → Narrative must look like a **governed account**, not a memory card:

- Account body (serif / readable); actors / causality when present in payload.
- Epistemic badges: `fresh` \| `stale` \| `superseded` \| `tombstoned` + stale_reason.
- Read-time confidence / independence display (derived).
- Grain: episode \| arc \| domain.
- Evidence list with retain-dissent visibility (superseded / lower-weight still listed).
- Relations: `part-of`, `continues`, `supersedes`, `same_originating_decision`, …
- Open Reflections that overlap the Narrative’s domain (always visible nearby — `v2.md` §10 #1).
- Actions: open commit flow only when reviewing Interpretations (link to Review), not “edit account as text blob.”

### Exit criteria

- [x] List + detail for Narratives in Explore.
- [x] Stale Narrative never presented as fresh (badge + copy).
- [x] Evidence and relations reachable from detail without leaving shell.

### Assumptions

- Forest/Trees (`v2.md` §2.4 / §5.1 Spotlight) may be a list grouping by grain in v2.4; full graph canvas is optional stretch, not required.

### Expected QA

- Fixture Narrative with stale EpistemicState renders correctly.
- Screenshot or DOM assert on epistemic badge classes.

### Resources

- `docs/v2.md` §§2.2–2.4, 6, 9.4 · `docs/EPISTEMICS.md`

---

## T-133 — Reflection / Interpretation / Situation purpose UI

**Twin version:** `v2.4` · **Phase:** P13 · **Status:** `done`  
**Depends on:** T-130, T-131, T-040  
**Blocks:** T-136, T-139

### Description

Purpose-shaped panes (not one generic table with a “type” column):

| Entity | UI emphasizes |
|---|---|
| **Reflection** | Open question / tension; status open→answered/superseded/faded; links to Situations & Interpretations |
| **Interpretation** | Competing explanation; supports/contradicts; path to Review → commit |
| **Situation** | Working cluster: member percepts, open Reflections count, lifecycle working→concluded |

Default Explore landing may spotlight **open Reflections** (operator attention), then Interpretations needing review.

### Exit criteria

- [x] Each of the three has list + detail with fields matching §2.2 lifecycle language.
- [x] From Interpretation detail, one click to Review/commit path (T-136).
- [x] Open Reflections always visible from Home and Explore.

### Assumptions

- Competing Interpretations stay non-durable until human commit (no “confirm memory” wording).

### Expected QA

- Seeded open Reflection appears on Home count and Explore filter `open`.

### Resources

- `docs/v2.md` §2.1–2.2, §10 #1 · `docs/COGNIZE.md`

---

## T-134 — Stance / Evidence / Relation / Trace purpose UI

**Twin version:** `v2.4` · **Phase:** P13 · **Status:** `done`  
**Depends on:** T-130, T-131, T-050, T-052  
**Blocks:** T-139

### Description

| Entity | UI emphasizes |
|---|---|
| **Stance** | Evaluative posture ≠ Narrative fact; pending proposals; preview→approve (token); active list |
| **Evidence** | Anchored percept span; source, time, ACL tags; attach context (which Interpretation/Narrative) |
| **Relation** | Typed edges among entities; filter by type especially `same_originating_decision` / contradicts / supports |
| **Trace** | Append-only accessibility / retrieval events feeding Fade·Remarkable — display, do not “edit” |

Stance approve uses the same preview-token discipline as CLI/TUI.

### Exit criteria

- [x] Stance proposals approvable from web with preview token.
- [x] Evidence and Relations browsable from Explore and from Narrative detail.
- [x] Trace list for a Narrative or vault (read-only).

### Assumptions

- Graph visualization is nice-to-have; a typed edge list with hop-to-endpoint is enough for v2.4 gate.

### Expected QA

- Approve path rejects missing/mismatched token.
- Relation list filters by type.

### Resources

- `docs/v2.md` §§2.2, 2.3, stage 10–12 · `docs/EPISTEMICS.md`

---

## T-135 — Sense strip — Percepts + Connectors + Jobs in web

**Twin version:** `v2.4` · **Phase:** P13 · **Status:** `done`  
**Depends on:** T-130, T-131, T-091  
**Blocks:** T-139

### Description

**Sense** pane in the web Center:

- Percept browser (immutable observations): source, time, vault, link into Situations.
- Connectors: list status (active/paused), last sync — actions that already exist over REST/shared handlers (test/pause/resume) if safe; otherwise deep-link copy for CLI/TUI.
- Jobs: queue depth + recent job kinds (`cognize_batch`, consolidate, backfill) read-only or enqueue if REST already supports it.

Keeps Sense vs Cognize wall visible: this pane is **I/O and queue**, not meaning.

### Exit criteria

- [x] Percept list+show in Explore or Sense pane.
- [x] Connectors and Jobs visible without leaving `/`.
- [x] UI copy never calls percepts “memories.”

### Assumptions

- Full connector setup wizards may stay TUI/CLI; web is visibility + light controls.

### Expected QA

- Empty connectors state guides to `twin connector setup` / TUI without dead ends.

### Resources

- `docs/v2.md` §1, §12.2 · `docs/INTERFACES.md` · Center `actions.py`

---

## T-136 — Unify Review + Commit inside web Center

**Twin version:** `v2.4` · **Phase:** P13 · **Status:** `done`  
**Depends on:** T-130, T-133, T-041, T-101  
**Blocks:** T-139

### Description

Fold today’s Review workbench + `#narratives` commit into the Center:

- Review queue = **Interpretations** (+ always-visible Open Reflections), not Memory candidates as product.
- Commit Narrative: preview token → commit (existing API), reachable from Review and from Interpretation detail.
- Keyboard/a11y: keep efficient queue stepping; do not regress T-101 gates.
- Remove or demote memory-resolve UX (merge/split as Narrative dual-read helpers only if still required — label honestly, not as product Memory).

### Exit criteria

- [x] Operator can review → commit Narrative entirely in `/` without the old Memories flow.
- [x] Open Reflections visible on Review pane at all times.
- [x] Commit requires preview token when `--require-token` semantics apply.

### Assumptions

- CLI `twin review` remains for TTY; web is the rich surface.

### Expected QA

- End-to-end browser or API+DOM test: competing Interpretation → commit → Narrative appears in Explore.

### Resources

- `docs/v2.md` stages 8–9, §9.4 · existing `/api/narratives/commit*`

---

## T-137 — Visual language — entity-coherent design system

**Twin version:** `v2.4` · **Phase:** P13 · **Status:** `done`  
**Depends on:** T-130  
**Blocks:** T-139

### Description

One composition for the web Center (not a dashboard of unrelated cards):

- Define CSS variables / type roles: **account** (Narrative body), **question** (Reflection), **candidate** (Interpretation), **posture** (Stance), **warrant** (Evidence), **observation** (Percept).
- Status color language shared with epistemic badges (fresh/stale/tombstoned) and job health.
- Motion: 2–3 intentional transitions (pane switch, detail open, toast) — no noise.
- Follow project frontend rules: expressive type (already Outfit / Source Serif), avoid purple-on-white AI-slop defaults if redesigning tokens; brand Twin mark remains hero of Home, not buried.
- Mobile: rail collapses; entity detail usable on narrow viewports.

### Exit criteria

- [x] Documented token map in `docs/WEB_CENTER.md` (or CSS comment block referenced from docs).
- [x] Each entity type visually distinguishable by purpose, not only by icon tint.
- [x] Lighthouse/a11y smoke: focus order, contrast on badges.

### Assumptions

- No new npm design-system package required; evolve `app.css`.

### Expected QA

- Side-by-side: Reflection vs Narrative vs Stance screenshots reviewed against §2.2 definitions.

### Resources

- `docs/v2.md` §9.4 Tone · `twin/interfaces/web/static/app.css`

---

## T-138 — Docs: WEB_CENTER + REST/COMMAND_CENTER sync

**Twin version:** `v2.4` · **Phase:** P13 · **Status:** `done`  
**Depends on:** T-130, T-131  
**Blocks:** T-139

### Description

1. Add `docs/WEB_CENTER.md` — single-route IA, entity map, how it relates to TUI Command Center (TUI = supervise processes; Web = see substrate + human gates).
2. Update `docs/COMMAND_CENTER.md` with pointer to web Center (not duplicate screen tables).
3. Update `docs/REST.md` for entity list/show.
4. Update `docs/OPERATIONS.md` / `docs/CLI.md` serve section: open web Center as primary visibility surface.
5. ROADMAP / tracker already list v2.4 — keep links honest.

### Exit criteria

- [x] WEB_CENTER.md exists and links from COMMAND_CENTER + REST + OPERATIONS.
- [x] No doc teaches Memories tab as product UI.
- [x] README stays architecture-layer only (link to WEB_CENTER, no stage dump).

### Assumptions

- Editorial only plus link audit; no PyPI notes beyond CHANGELOG at cut time.

### Expected QA

- Link check for new doc paths.
- Fresh-reader: can find “where do I see Reflections?” in under a minute.

### Resources

- `docs/v2.md` §§0−, 12 · existing doc set

---

## T-139 — QA gate — entity routes, no Memory product UI

**Twin version:** `v2.4` · **Phase:** P13 · **Status:** `done`  
**Depends on:** T-130–T-138  
**Blocks:** none (release gate for `2.4.0`)

### Description

Release checklist for package `2.4.0`:

1. Automated: every §2.2 entity list+show 200; shell has no Memories nav; Stance approve token negative test; Narrative stale badge.
2. Manual: walk Sense → Cognize halt/status → Review commit → Explore Narrative/Stance → Inject pack pane.
3. Regression: TUI Center still launches; aliases stay absent (`extract` etc.).
4. CHANGELOG + `__version__ = 2.4.0` + tag.

### Exit criteria

- [x] All T-130–T-138 exit criteria checked off.
- [x] CI green on entity REST + web smoke.
- [x] Package `2.4.0` recorded in CHANGELOG.

### Assumptions

- Patch releases after 2.4.0 use normal hardening PRs, not new tracker versions unless scope expands.
- **`2.4.1`** closed exit-criteria gaps that were marked done too early at `2.4.0`: Narrative derived confidence/relations/open Reflections, Situation purpose UI, Stance Ops preview→approve, commit requiring preview token, empty-list REST contracts, WEB_CENTER visual token map.

### Expected QA

- Full `pytest` slice for interfaces/web + REST entity contracts + `tests/evals` still green.
- Hardening contracts in `tests/interfaces/test_web_center_hardening.py`.

### Resources

- This tracker version map · `docs/CHANGELOG.md`

---

## Out of scope / explicit non-tasks (do not invent work)

Unless a new tracker ID is added, do **not**:

- Implement Event entity between Percept and Situation (`v2.md` §10 #14).
- Implement full Inject Observer watcher (only slot — T-074).
- Build ARCTIC code-critique product inside Cognize (`v2.md` §5.1, §10 #16) — ingest external critique outputs as percepts only if needed later.
- Make Twin a query-time KB synthesizer (GBrain mode).
- Auto-confirm Narrative/Stance.
- Store incrementable confidence scalars.
- Replace MCP/Native with the Command Center (TUI or Web).
- Remote SSH Twin home management (§12.10 #4).
- Literary L1–L4 narrative ontology as schema (§2.4).
- Full interactive force-directed graph as a v2.4 release requirement (typed Relation lists are enough).
- Re-introducing product “Memory” tabs or CLI aliases removed in 2.3.2.

---

## T-140 — Docs lock — package target layout + vocabulary

**Twin version:** `v2.5` · **Phase:** P14 · **Status:** `done`  
**Depends on:** T-139  
**Blocks:** T-141–T-149

### Description

Lock product docs to Narrative / Stance / Inject vocabulary and publish the
target package map (`sense` / `cognize` / `inject` / `store` / `llm` /
`privacy` / `interfaces`) in ARCHITECTURE. PRODUCT, GLOSSARY, MCP preference
tables, COGNITION/COGNIZE frontiers aligned.

### Exit criteria

- [x] ARCHITECTURE § Code packages matches agreed layout.
- [x] PRODUCT no longer teaches memory → judgment → action as product layers.
- [x] Tracker tasks T-141–T-149 defined and indexed.

### Resources

- `docs/ARCHITECTURE.md` · `docs/PRODUCT.md` · `docs/GLOSSARY.md`

---

## T-141 — `twin.sense` — connectors + sensory

**Twin version:** `v2.5` · **Phase:** P14 · **Status:** `done`  
**Depends on:** T-140  
**Blocks:** T-149

### Description

Create `twin/sense/` owning connectors and sensory capture. Update imports;
leave thin re-exports only where needed for one release.

### Exit criteria

- [x] `twin.sense` is the import path for connectors + sensory.
- [x] Tests that touch connectors/sensors green.

---

## T-142 — `twin.llm` — provider adapters

**Twin version:** `v2.5` · **Phase:** P14 · **Status:** `done`  
**Depends on:** T-140  
**Blocks:** T-145, T-149

### Description

Move `twin/cognition/llm/` to `twin/llm/`. Cognize and Inject depend on it;
no product LLM logic inside store or interfaces.

### Exit criteria

- [x] `from twin.llm` works for providers + usage.
- [x] No new code imports `twin.cognition.llm`.

---

## T-143 — `twin.store` — persistence facade

**Twin version:** `v2.5` · **Phase:** P14 · **Status:** `done`  
**Depends on:** T-140  
**Blocks:** T-145, T-146, T-149

### Description

Move the data layer under `twin/store/` (today’s `twin/memory/` store,
embeddings, search, mixins). Product noun remains Narrative — package name
is store. Retire `MemoryStore` name when safe, or alias during transition.

### Exit criteria

- [x] Persistence imported via `twin.store`.
- [x] Dual-read tables still work; export/backup green.

---

## T-144 — `twin.inject` — packs + Observer slot

**Twin version:** `v2.5` · **Phase:** P14 · **Status:** `done`  
**Depends on:** T-140, T-142  
**Blocks:** T-145, T-149

### Description

Move context pack, inject observer, and related Inject surfaces out of
`twin.cognition` into `twin/inject/`.

### Exit criteria

- [x] `build_context_pack` and Observer slot live under `twin.inject`.
- [x] MCP `inject_context_pack` still works.

---

## T-145 — Fold `twin.cognition` into `twin.cognize`

**Twin version:** `v2.5` · **Phase:** P14 · **Status:** `done`  
**Depends on:** T-142, T-143, T-144  
**Blocks:** T-149

### Description

Remaining cognition services (interpreter, episode pipeline, extract bridge)
move under `twin/cognize/`. Delete or shim-empty `twin/cognition/` when
imports are gone.

### Exit criteria

- [x] No required runtime import of `twin.cognition` except deprecated shim.
- [x] Cognize orchestrator + late stages still halt without LLM.

---

## T-146 — Split `twin.judgment` → cognize Stance + privacy

**Twin version:** `v2.5` · **Phase:** P14 · **Status:** `done`  
**Depends on:** T-143, T-147  
**Blocks:** T-149

### Description

Stance models, proposals, revisions, versions → `twin.cognize` (or
`twin.cognize.stance`). Firewall / PII → `twin.privacy`. Drop the public
`judgment` package name when call sites are updated.

### Exit criteria

- [x] Stance code lives under cognize; firewall under privacy.
- [x] CLI `twin stance` and approve preview still work.

---

## T-147 — `privacy` owns Firewall / PII / guardrails

**Twin version:** `v2.5` · **Phase:** P14 · **Status:** `done`  
**Depends on:** T-140  
**Blocks:** T-146, T-149

### Description

Expand `twin/privacy/` to own Domain Firewall, PII helpers, and disclosure
guardrails used by Inject.

### Exit criteria

- [x] Inject imports Firewall from `twin.privacy`.
- [x] Policy YAML paths unchanged for operators.

---

## T-148 — `interfaces` absorbs runtime + sovereignty

**Twin version:** `v2.5` · **Phase:** P14 · **Status:** `done`  
**Depends on:** T-140  
**Blocks:** T-149

### Description

Move `twin/runtime/` and `twin/sovereignty/` under `twin/interfaces/`
(workers, queue, export, backup). Keep CLI entrypoints stable.

### Exit criteria

- [x] Runtime and sovereignty import paths are under interfaces.
- [x] `twin serve` / workers / export smoke green.

---

## T-149 — QA gate — imports, MCP names, package `2.5.0`

**Twin version:** `v2.5` · **Phase:** P14 · **Status:** `done`  
**Depends on:** T-140–T-148  
**Blocks:** none (release gate)

### Description

Full import/graph check, prefer `narrative_*` / `stance_*` MCP docs and
aliases, CHANGELOG + tag `v2.5.0`.

### Exit criteria

- [x] CI green on interfaces + cognize + store slices.
- [x] Package `2.5.0` recorded; old package roots removed (no shims).

---

## T-150 — Rename dual-read types (`MemoryItem` → store claim)

**Twin version:** `v2.6` · **Phase:** P15 · **Status:** `done`  
**Depends on:** T-149  
**Blocks:** T-151, T-152

### Description

Retire dual-read **type names** that still say Memory in the Python store
API. Target vocabulary (finalize in implementation, keep one canonical set):

| Today (dual-read) | Target |
|---|---|
| `MemoryItem` | `StoreClaim` |
| `MemoryType` / `MemoryStatus` | `ClaimType` / `ClaimStatus` |
| `MemoryOperation` | `ClaimOperation` |
| `MemoryStore` | keep as store facade name |

Scope: `twin/store/models.py` and all importers. Do **not** change product
nouns Narrative / Interpretation / Stance. No transitional type aliases.

Out of scope here: physical DB column renames (T-151).

### Exit criteria

- [x] Public store models use claim vocabulary; no `MemoryItem` / `MemoryType` / `MemoryStatus` / `MemoryOperation` shims.
- [x] Docs (GLOSSARY / ARCHITECTURE store section) describe claim rows, not product “memory.”
- [x] Unit tests for models + formation/lifecycle green.

### Assumptions

- Column/FK renames completed in T-151 (`claim_id` / `store_claims`).
- MCP `claim_*` only; no `memory_*` / `judgment_*` tool shims (T-152).

### Expected QA

- `pytest tests/memory/` (or renamed test path) + cognize dual-read smoke.

### Resources

- `twin/store/models.py` · `docs/GLOSSARY.md` migration note · T-014 dual-read history

---

## T-151 — Migrate store columns / FKs (`memory_id` → claim id)

**Twin version:** `v2.6` · **Phase:** P15 · **Status:** `done`  
**Depends on:** T-150  
**Blocks:** T-152

### Description

Schema migration for SQLite + Postgres: rename dual-read tables/columns that
still use `memory` / `memories` / `claim_id` to the claim vocabulary chosen
in T-150. Preserve export/backup/restore. Evidence, relations, findings,
sessions, and connector links must keep referential integrity.

Provide a one-shot migrator (and downgrade policy: none — forward only).

### Exit criteria

- [x] Fresh DB and upgraded DB both use claim column names.
- [x] Export → restore round-trip green on SQLite and Postgres CI jobs.
- [x] No silent data loss on dual-read rows or Evidence FKs.

### Assumptions

- Cognize `cognize_*` tables already use Narrative ids — do not conflate.
- ID *prefixes* (`mem_`) may remain for existing rows; new ids may switch to `clm_` (document choice).

### Expected QA

- `tests/memory/store/` + sovereignty backup/export + postgres job.

### Resources

- `twin/store/store/sqlite.py` · `postgres.py` · `docs/OPERATIONS.md`

---

## T-152 — QA gate — API/MCP/export without Memory* product names

**Twin version:** `v2.6` · **Phase:** P15 · **Status:** `done`  
**Depends on:** T-150, T-151  
**Blocks:** none (release gate for `2.6.0`)

### Description

Finish dual-read retirement on host surfaces:

1. MCP: retarget or remove `memory_*` tools; prefer Narrative/claim search as documented.
2. REST/OpenAPI: no Memory product schemas in operator docs.
3. CHANGELOG + `__version__ = 2.6.0` + tag.

### Exit criteria

- [x] MCP tools and docs use Narrative / claim / stance language; no `memory_*` or `judgment_*` tool shims.
- [x] Grep gate: no `MemoryItem` / type aliases in `twin/`.
- [x] Package `2.6.0` recorded; focused local suites green (CI after push/PR).

### Resources

- `docs/MCP.md` · `docs/REST.md` · `docs/CHANGELOG.md`

---

## Suggested first slice (if starting cold)

**v2.0–v2.5 are shipped (or cut).** For **v2.6**:

1. T-150 rename Python dual-read types to claim vocabulary.
2. T-151 migrate DB columns/FKs.
3. T-152 MCP/docs QA gate → `2.6.0`.

---

*Tracker for Twin package line **v2.0–v2.6** — redesign intent in `docs/v2.md` (longitudinal narratives, architecture vs pipeline, TUI + Web command center, package walls, dual-read retirement).*

ATTENTION: Do not mention task numbers in any Git resource (PR/release/commit).
