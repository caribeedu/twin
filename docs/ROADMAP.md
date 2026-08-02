# Roadmap

This document explains planned work — open correlation-depth gaps and next
major versions.

It is not the research program ([RESEARCH.md](RESEARCH.md)). Product
shape: [PRODUCT.md](PRODUCT.md). What shipped: [CHANGELOG.md](CHANGELOG.md).
Destination: [README](../README.md).

## Correlation depth (remainder)

Goal: deepen the correlation layer from clustered evidence into an
explainable, incrementally maintained work-episode model — without turning
correlation into Memory or Judgment.

What already shipped (episode arc, LLM cognition stages, reflect,
`twin meditate`, soft-fuse, review resolve surfaces) is recorded in
[CHANGELOG.md](CHANGELOG.md). Runtime contract:
[ARCHITECTURE → Brain analogies and CLI stages](ARCHITECTURE.md#brain-analogies-and-cli-stages).
This section tracks only what remains.

The remainder feeds [v2 Extended Brain](#v2-extended-brain) episodic and
autobiographical memory. It is not a blocker for cognitive interpretation
or parallel consolidation.

#### Open gaps

1. **Multi-factor confidence** — compose link strength × source diversity × independence-group count × evidence quality / source trust beyond a single rebuild-max heuristic.
2. **Identity as a small graph** — keep conservative auto-propose rules; let confirmed `IdentityLink`s form a vault-scoped graph that Entity resolution can consume later.
3. **Explainability as broader product surface** — `twin episode graph`; stable HTTP/MCP metadata for anchors, merge vs contextual edges, independence groups, finding_key claim set, vault partition.
4. **Hardening tests / evals** — full rebuild replay; incremental ≡ batch under load; multi-vault / multi-org isolation; large ConnectorRecord volumes.

#### Non-goals

- Auto-confirm Memory, Judgment, or Entity from correlation (reflect emits candidates; proposals need human approval).
- Cross-vault merge without an explicit, audited cross-domain action.
- Forming episodes from temporal proximity alone.

## Future major versions

### v2 — Extended Brain

Expand the stable cognitive substrate beyond professional and technical memory into a broader, compartmentalized and continuously available representation of the user's life.

Deepen the cognitive model with:

- robust episodic memory and autobiographical timelines, building on WorkEpisode phases, causality edges and explainability from [Correlation depth](#correlation-depth-remainder);
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

The Extended Brain must preserve the architectural boundaries in
[ARCHITECTURE.md](ARCHITECTURE.md) and [IDENTITY.md](IDENTITY.md): sensors
capture evidence, the cognitive layer interprets meaning, deterministic
governance controls use, and no personal-domain or voice path may bypass
authorization, provenance or human control.

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
