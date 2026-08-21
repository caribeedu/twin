# Web Command Center

Operator web cockpit for Twin — Cognize → Review → Inject — served by
`twin serve` at a single route (`/`).

The TUI Command Center ([COMMAND_CENTER.md](COMMAND_CENTER.md)) supervises
long-lived processes on one screen (**Health · Services · MCP rail**). This
surface is **visibility and human gates**: browse every Cognize entity, review
Interpretations, commit Narratives, run Cognize batches, and build Inject packs.

## Shell

No side rail. Home is a dashboard of linked sections; deep links stay in-shell
(`#explore/narrative/<id>`, `#review`, `#review/reflection/<id>`, `#cognize`, `#ops`, `#sessions`, …).
A brand bar + **← Home** recovers navigation from any pane.

| Home section | Role | Full view |
|---|---|---|
| Sessions | Open sessions by provider (mock until telemetry) | `#sessions` |
| Jobs | Running / pending | `#cognize` |
| Substrate | Entity counts | `#explore` |
| To review | Open Reflections + competing Interpretations | `#review` (one-at-a-time deck) |
| Search | Fuzzy match across entity types | `#explore` |
| Inject | Inline context pack builder (no deep-link) | `#inject` |
| Health | Cognize gate + connectors | `#ops` |

## Former rail panes

| Pane | Role |
|---|---|
| Home | Dashboard above |
| Explore | List + detail for all substrate entities |
| Review | One-at-a-time deck: Open Reflections + competing Interpretations; lineage graph; commit Narrative in-card |
| Cognize | Run batch, live stage progress (bar · ETA · entities), token estimate, jobs, integrity |
| Inject | Context pack builder (domain select) |
| Ops | Doctor, runtime queue, integrity (no raw JSON) |

## Cognize pane

Home-style sections (not raw JSON): **Run** (execute / dry-run enqueue of
`cognize_batch`), **Estimate** (heuristic tokens + USD by model), **Items
to execute**, **Active jobs**, **Past jobs**, and **Integrity** stats.
Endpoints: `GET /api/cognize/status`, `GET /api/cognize/plan`,
`POST /api/cognize/run`.

## Entities (Explore)

Purpose-shaped accordion list — click a row to expand in place (no separate
detail page). A per-type search bar filters the current pill; when the query
is non-empty the chrome title becomes **Search in {Entity}** (e.g. Search in
Relations). Status sits left of the title (PascalCase); expansion shows
description, metadata, and a pan/zoom **Lineage** graph (multi-hop Past /
Here / Next). Percepts split into **Observed** (Sense) and **Derived**
(Cognize-synthesized). Relations is a flowchart-only pill (last). Clicking a
lineage node stays in Explore and switches the entity-type pill when needed.

| Entity | Emphasizes |
|---|---|
| Narrative | Account body, epistemic badges, grain, evidence, derived confidence, relations |
| Reflection | Open question / tension |
| Interpretation | Competing explanation → Review |
| Situation | Working cluster |
| Stance | Evaluative posture (≠ factual account); Explore + API preview→approve |
| Evidences | Anchored warrant |
| Trace | Accessibility / retrieval ledger |
| Percept | Observed Sense input, or **Derived** Cognize-synthesized percepts (episode/pattern arcs); PR meta is structured, not a card |
| Relation | Full entity flowchart (last pill) — no accordion list |

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
| observation | Explore Percept rows | Percept |
| cluster | gray rule | Situation |
| edge / ledger | typed chips | Relation / Trace |

Epistemic badges share `.tag.ok` / `.tag.warn` / `.tag.err` (fresh / stale / tombstoned).
