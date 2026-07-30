[← README](../README.md) · [FOUNDATIONS](FOUNDATIONS.md) · [PRODUCT](PRODUCT.md) · [ROADMAP](ROADMAP.md) · [CHANGELOG](CHANGELOG.md) · [ARCHITECTURE](ARCHITECTURE.md) · [INTERFACES](INTERFACES.md) · [SETUP](SETUP.md) · [OPERATIONS](OPERATIONS.md)

# Roadmap

**Source of truth for:** planned work — deferred correlation depth and next major versions.

Product shape in [PRODUCT.md](PRODUCT.md). What shipped in [CHANGELOG.md](CHANGELOG.md).

## Correlation depth (v1.3.0 delivered; remainder 1.3.x / 1.4)

Goal: deepen the correlation layer from “clustered evidence” into an explainable, incrementally maintained work-episode model — without turning correlation into Memory or Judgment.

**Slot.** The episode-arc + reflect slice shipped in [v1.3.0](CHANGELOG.md#v130--correlation-depth-episode-arc-and-reflect); the remainder feeds [v2 Extended Brain](#v2--extended-brain) episodic and autobiographical memory. It is not a blocker for cognitive interpretation or parallel consolidation.

Phase 7 established: connectors capture evidence; correlation proposes revisable structure (`WorkEpisode`, `IdentityLink`, `ProjectLink`, `ReviewFinding`); vault partition; idempotent keys; membership reconciliation; project/identity lifecycle; true cross-source conflicts; thin explain CLI.

#### Delivered in v1.3.0

- **Episode phases** — `EpisodePhase` gives each episode a `goal → decision → execution → outcome` arc, rebuilt on membership change; a decision reversal stays visible as two decision phases instead of collapsing the pivot.
- **Causal / narrative edges** — revisable `EpisodeEdge`s (`motivated | superseded | resolved | continues | contradicts`) proposed from the arc + member language, with human `confirm`/`reject` that survives rebuilds; edges never alone create Memory.
- **Incremental correlation MVP** — a `correlation_dirty` index (marked from the connector commit/tombstone path) drives `twin correlate --incremental`; full rebuild (`--full`) remains the correctness oracle; parity-tested incremental ≡ batch on fixtures.
- **`episode reflect` → MemoryCandidates** — the cognitive layer reads phases + edges and synthesizes trajectory claims ("intended X → chose Y") as candidates only (`review_reason=episode_reflect`), `valid_from` tracking the decision phase; CLI + weekly stage; confirm-snapshot invariant unchanged.
- **Judgment from episode patterns** — `propose_from_episode` / `propose_from_episode_patterns` seed pending `JudgmentProposal`s (`provenance.source=episode_pattern`) from confirmed trajectory memories; human approval only.

#### Remainder (1.3.x / 1.4)

2. **Multi-factor confidence** — compose link strength × source diversity × independence-group count × evidence quality / source trust beyond today’s rebuild max.
3. **Identity as a small graph** — keep conservative auto-propose rules; let confirmed `IdentityLink`s form a vault-scoped graph that Entity resolution can consume later.
6. **Explainability as broader product surface** — `twin episode graph`; stable HTTP/MCP metadata for anchors, merge vs contextual edges, independence groups, finding_key claim set, vault partition.
7. **Hardening tests / evals** — full rebuild replay; incremental ≡ batch under load; multi-vault / multi-org isolation; large ConnectorRecord volumes.

#### Non-goals

- Auto-confirm Memory, Judgment, or Entity from correlation (reflect emits candidates; proposals need human approval).
- Cross-vault merge without an explicit, audited cross-domain action (Phase 7 invariant stays).
- Forming episodes from temporal proximity alone.

## Future major versions

### v2 — Extended Brain

Expand the stable cognitive substrate beyond professional and technical memory into a broader, compartmentalized and continuously available representation of the user's life.

Deepen the cognitive model with:

- robust episodic memory and autobiographical timelines, building on WorkEpisode phases, causality edges and explainability from [Correlation depth](#correlation-depth-v130-delivered-remainder-13x--14);
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

Shipped history in [CHANGELOG.md](CHANGELOG.md). Product definition in [PRODUCT.md](PRODUCT.md).
