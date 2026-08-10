# Roadmap

This document explains planned work — open correlation-depth gaps and next
major versions.

It is not the research program ([RESEARCH.md](RESEARCH.md)). Product
shape: [PRODUCT.md](PRODUCT.md). What shipped: [CHANGELOG.md](CHANGELOG.md).
Destination: [README](../README.md).

## Correlation depth (remainder)

Goal: deepen the correlation layer from clustered evidence into an
explainable, incrementally maintained work-episode / Situation model —
without turning correlation into Narrative or Stance.

What already shipped (episode arc, LLM cognition stages, reflect,
soft-fuse, review surfaces) is recorded in [CHANGELOG.md](CHANGELOG.md).
Runtime contract:
[ARCHITECTURE → Brain analogies and CLI stages](ARCHITECTURE.md#brain-analogies-and-cli-stages).
This section tracks only what remains.

The remainder feeds [v3 Extended Brain](#v3-extended-brain) episodic and
autobiographical depth (and is absorbed/retargeted by the **v2**
Narrative / Situation pipeline where applicable).

#### Open gaps

1. **Multi-factor confidence** — compose link strength × source diversity × independence-group count × evidence quality / source trust beyond a single rebuild-max heuristic. Twin v2 retargets “confidence” to **read-time** derivation over evidence + independence Relations ([v2.md](v2.md) §2.3).
2. **Identity as a small graph** — keep conservative auto-propose rules; let confirmed `IdentityLink`s form a vault-scoped graph that Entity resolution can consume later.
3. **Explainability as broader product surface** — Situation / Narrative relations in [Web Command Center](#v2--longitudinal-narratives-sense--cognize--inject); stable HTTP/MCP metadata for anchors, merge vs contextual edges, independence groups, finding_key claim set, vault partition.
4. **Hardening tests / evals** — full rebuild replay; incremental ≡ batch under load; multi-vault / multi-org isolation; large ConnectorRecord volumes.

#### Non-goals

- Auto-confirm Narrative, Stance, or Entity from correlation (Cognize emits candidates; humans commit).
- Cross-vault merge without an explicit, audited cross-domain action.
- Forming episodes / situations from temporal proximity alone.

## Future major versions

### v2 — Longitudinal Narratives (Sense → Cognize → Inject)

Replace memory-as-product with a **longitudinal narrative** architecture:
form, revise, and project governed Narratives across sources, models, and
interfaces — with open Reflections, competing Interpretations, EpistemicState,
and human authority over durability.

Design source of truth: [v2.md](v2.md).  
Implementable cuts: [v2-tracker.md](v2-tracker.md).

Public architecture stays three hard modules:

```text
Sense → Cognize → Inject
```

Cognize’s internal stages (Salience → … → Fade / Remarkable) are pipeline
detail, not a fourth architecture wall.

| Twin package | Theme | Ships when |
|---|---|---|
| **v2.0** | Narrative substrate | Cognize LLM-or-halt through Evidence audit; human Commit Narrative; deterministic stale floor; Inject EpistemicState; `twin cognize` / `narrative` / `stance` verbs; dual-read; stale-injection eval |
| **v2.1** | Epistemics + host surfaces | Read-time confidence / independence; open Reflections in packs; ACL ∩ + revoke tombstone; Stance drafts; MCP / REST / Native pack contract |
| **v2.2** | Consolidation & accessibility | Nightly consolidation judgment (caps); Fade / Remarkable + Trace; quiet-reversal and disagreement-attention evals |
| **v2.3** | Command Center (TUI) | Bare `twin` TUI cockpit; docs split ARCHITECTURE / COGNIZE / EPISTEMICS / RESEARCH; README architecture-layer only |
| **v2.4** | Web Command Center | Single-route web cockpit (`twin serve`): purpose-shaped UI for every Cognize entity (§2.2); Explore + Review + Sense + Inject panes; retire Memory-as-product web UI |

Non-goals for v2 (deferred to later majors or explicit follow-ons):

- Personal-domain ingest as default (finance, health, family, …) — see [v3](#v3-extended-brain).
- Full Inject Observer watcher (slot reserved in v2.1; full product later).
- Autonomous action / automations — see [v4](#v4-cognitive-automation).
- Multimodal / embodied life layer — see [v5](#v5-multimodal-life-layer) / [v6](#v6-embodied--robot-ready-memory).

### v3 — Extended Brain

Expand the stable cognitive substrate beyond professional and technical
work into a broader, compartmentalized and continuously available
representation of the user's life — **built on** the v2 Narrative /
Stance / EpistemicState substrate (not a parallel memory product).

Deepen the cognitive model with:

- robust episodic and autobiographical timelines, building on Situations /
  Narratives, causality Relations and explainability from
  [Correlation depth](#correlation-depth-remainder) and Twin v2;
- consolidated semantic structure over Narratives;
- procedural knowledge and learned workflows;
- goals, routines and hierarchical plans;
- active personas with controlled shared context;
- daily and weekly reflection and consolidation (beyond v2.2 caps);
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

Personal-domain ingestion must build on persona-aware governance, stronger
PII and entity handling, explicit consent, stricter review and physically
separable vaults where appropriate. Information about third parties must
not be assumed to be authorized for unrestricted ingestion, correlation or
use.

Reduce the distance between thought and the external cognitive layer through:

- local voice notes and transcription;
- low-latency conversational capture;
- daily reflection and Narrative / Stance review;
- meeting and environmental capture with explicit controls;
- hands-free queries over governed Narratives;
- a conversational interface that complements rather than replaces existing tools.

The Extended Brain must preserve the architectural boundaries in
[ARCHITECTURE.md](ARCHITECTURE.md), [IDENTITY.md](IDENTITY.md) and the
Sense → Cognize → Inject walls from [v2.md](v2.md): sensors capture
evidence, Cognize interprets meaning, deterministic governance controls
use, and no personal-domain or voice path may bypass authorization,
provenance or human control.

### v4 — Cognitive Automation

Transform Narratives and Stance into safe action selection:

- smart reminders;
- automatic drafts;
- follow-ups;
- commitment detection;
- action suggestions;
- reversible automations;
- approval and policy gates;
- outcome feedback that updates procedures and Stance.

### v5 — Multimodal Life Layer

Extend perception beyond text:

- voice;
- screen;
- images;
- documents;
- meetings;
- environment;
- wearable data;
- spatial and embodied context.

### v6 — Embodied / Robot-ready Memory

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

Shipped history in [CHANGELOG.md](CHANGELOG.md). Product definition in [PRODUCT.md](PRODUCT.md). Twin v2 tasks in [v2-tracker.md](v2-tracker.md).
