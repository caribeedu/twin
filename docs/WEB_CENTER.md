# Web Command Center

Operator web cockpit for Twin — Sense → Cognize → Inject — served by
`twin serve` at a single route (`/`).

The TUI Command Center ([COMMAND_CENTER.md](COMMAND_CENTER.md)) supervises
long-lived processes. This surface is **visibility and human gates**: browse
every Cognize entity, review Interpretations, commit Narratives, inspect
Sense I/O, and build Inject packs.

## Rail

| Pane | Role |
|---|---|
| Home | Counts, Cognize halt, shortcuts |
| Explore | List + detail for all substrate entities |
| Review | Open Reflections, competing Interpretations, Narrative commit |
| Cognize | Halt / health (runs stay CLI or TUI) |
| Sense | Percepts, connectors, jobs |
| Inject | Context pack builder |
| Ops | Health, runtime queue, Stance proposals |

Deep-links stay in-shell: `#explore/narrative/<id>`, `#review`, `#sense`, …

## Entities (Explore)

Purpose-shaped views — not a generic CRUD grid:

| Entity | Emphasizes |
|---|---|
| Narrative | Account body, epistemic badges, grain, evidence, derived confidence, relations |
| Reflection | Open question / tension |
| Interpretation | Competing explanation → Review |
| Situation | Working cluster |
| Stance | Evaluative posture (≠ factual account); Ops preview→approve |
| Evidence | Anchored warrant |
| Relation | Typed edges |
| Trace | Accessibility / retrieval ledger |
| Percept | Immutable observation (Sense) |

No product **Memories** tab.

## REST (read)

List + show under `/api/situations`, `/api/reflections`, `/api/interpretations`,
`/api/relations`, `/api/evidence`, `/api/traces`, `/api/stances`,
`/api/percepts/{id}`, plus `/api/center/summary` and `/api/runtime/jobs`.
Narrative show embeds `derived_confidence`, relations, evidence, and open
Reflections. Commit requires `preview_token` from commit-preview. Stance
proposal preview/approve live under `/api/stances/proposals/{id}/…`.

Empty connectors state guides to CLI/TUI setup without inventing wizards here.

## Visual tokens

| Role | CSS cue | Entity |
|---|---|---|
| account | serif body + purple rule | Narrative |
| question | blue rule / dashed strip | Reflection |
| candidate | orange rule | Interpretation |
| posture | green rule | Stance |
| warrant | blue rule | Evidence |
| observation | Sense pane rows | Percept |
| cluster | gray rule | Situation |
| edge / ledger | typed chips | Relation / Trace |

Epistemic badges share `.tag.ok` / `.tag.warn` / `.tag.err` (fresh / stale / tombstoned).
