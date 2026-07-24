[← README](../README.md) · [FOUNDATIONS](FOUNDATIONS.md) · [PRODUCT](PRODUCT.md) · [ROADMAP](ROADMAP.md) · [CHANGELOG](CHANGELOG.md) · [ARCHITECTURE](ARCHITECTURE.md) · [INTERFACES](INTERFACES.md) · [SETUP](SETUP.md) · [OPERATIONS](OPERATIONS.md)

# Roadmap

**Source of truth for:** planned work — deferred correlation depth and future major versions (v2+).

Product shape: [PRODUCT.md](PRODUCT.md). What shipped: [CHANGELOG.md](CHANGELOG.md).

## Correlation depth (planned vX — after Phase 7)

Goal: deepen the correlation layer from “clustered evidence” into an explainable, incrementally maintained work-episode model — without turning correlation into Memory or Judgment.

**Slot.** Later `v0.x` or v2, naturally before or alongside [v0.8 Parallel Memory](CHANGELOG.md#v08--parallel-memory-and-consolidation), and feeding [v2 Extended Brain](#v2--extended-brain) episodic and autobiographical memory. It is not a blocker for cognitive interpretation or parallel consolidation.

Phase 7 correctly established: connectors capture evidence; correlation proposes revisable structure (`WorkEpisode`, `IdentityLink`, `ProjectLink`, `ReviewFinding`); vault partition; idempotent keys; membership reconciliation; project/identity lifecycle; true cross-source conflicts; thin explain CLI. What remains is the deeper path.

#### Accepted debt (what Phase 7 still is)

- **WorkEpisode = one cluster.** An episode is still a correlated set of `ConnectorRecord`s, not a structured arc (goal, decision, execution, outcome). PR + Slack + meeting + deploy collapse into one node.
- **Confidence ≈ link type (+ rebuild max).** Episode/link confidence still follows anchor kind / max active link; not source diversity × independence × source trust as a composed score.
- **IdentityLink is pairwise.** Email/candidate edges + confirm/unconfirm/reject exist; there is no first-class identity graph that consolidates GitHub ↔ email ↔ Slack ↔ meeting ↔ calendar into one Entity-facing structure.
- **No causality inside an episode.** Membership says “same episode,” not “A caused B / B motivated C / C resolved D.”
- **Correlation is a batch pass.** `run_correlation_pass()` rescans records; there is no incremental path driven only by new/changed/tombstoned records.
- **Explainability is CLI-first.** Anchors/links/findings are inspectable via `episode explain` / `identity why` / `project explain`; no HTTP/MCP graph API yet.
- **Eval / load gaps.** Missing: full rebuild replay, incremental-only passes, multi-vault / multi-org stress, large ConnectorRecord volumes.

#### Path forward

1. **Episode phases** — `WorkEpisode`, then `EpisodePhase`, then `Evidence` (or equivalent) so the system can answer when a decision changed and when a plan became execution, without splitting every phase into a separate episode by default.
2. **Multi-factor confidence** — compose link strength × source diversity × independence-group count × evidence quality / source trust beyond today’s rebuild max.
3. **Identity as a small graph** — keep conservative auto-propose rules; let confirmed `IdentityLink`s form a vault-scoped graph that Entity resolution can consume later.
4. **Causal / narrative edges (optional layer)** — after membership is stable, propose revisable “motivated / resolved / superseded” links between sources or phases; never auto-write Judgment.
5. **Incremental correlation** — index dirty records / tombstones; update only affected partitions and episodes; keep full rebuild as the correctness oracle.
6. **Explainability as broader product surface** — `twin episode graph`; stable HTTP/MCP metadata for anchors, merge vs contextual edges, independence groups, finding_key claim set, vault partition.
7. **Hardening tests / evals** — rebuild ≡ replay; incremental ≡ batch; multi-vault isolation under load; large ConnectorRecord volumes.

#### Non-goals for that vX

- Auto-confirm Memory, Judgment, or Entity from correlation.
- Cross-vault merge without an explicit, audited cross-domain action (Phase 7 invariant stays).
- Forming episodes from temporal proximity alone.

## Future major versions

### v2 — Extended Brain

Expand the stable cognitive substrate beyond professional and technical memory into a broader, compartmentalized and continuously available representation of the user's life.

Deepen the cognitive model with:

- robust episodic memory and autobiographical timelines, building on WorkEpisode phases, causality edges and explainability from [Correlation depth](#correlation-depth-planned-vx--after-phase-7);
- consolidated semantic memory;
- procedural memory and learned workflows;
- goals, routines and hierarchical plans;
- active personas with controlled shared context;
- daily and weekly reflection and consolidation;
- uncertainty-aware mental-model evolution;
- attention and salience mechanisms;
- counterfactual reasoning over prior decisions.

Expand into carefully governed personal domains such as:

- finance;
- home;
- personal goals;
- relationships;
- family;
- health;
- social identity.

Personal-domain ingestion must build on persona-aware governance, stronger PII and entity handling, explicit consent, stricter review and physically separable vaults where appropriate. Information about third parties must not be assumed to be authorized for unrestricted ingestion, correlation or use.

Reduce the distance between thought and the external cognitive layer through:

- local voice notes and transcription;
- low-latency conversational capture;
- daily reflection and memory review;
- meeting and environmental capture with explicit controls;
- hands-free memory queries;
- a conversational interface that complements rather than replaces existing tools.

The Extended Brain must preserve the same architectural boundaries established before v1: sensors capture evidence, the cognitive layer interprets meaning, deterministic governance controls use, and no personal-domain or voice path may bypass authorization, provenance or human control.

### v3 — Cognitive Automation

Transform memory and judgment into safe action selection:

- smart reminders;
- automatic drafts;
- follow-ups;
- commitment detection;
- action suggestions;
- reversible automations;
- approval and policy gates;
- outcome feedback that updates procedures and judgment.

### v4 — Multimodal Life Layer

Extend perception beyond text:

- voice;
- screen;
- images;
- documents;
- meetings;
- environment;
- wearable data;
- spatial and embodied context.

### v5 — Embodied / Robot-ready Memory

Prepare the cognitive substrate for physical agents:

- personal robots;
- home assistants;
- spatial memory;
- household preferences;
- physical routines;
- object and environment models;
- interfaces with embedded systems;
- strict embodiment-specific safety and action permissions.


---

Shipped history: [CHANGELOG.md](CHANGELOG.md). Product definition: [PRODUCT.md](PRODUCT.md).
