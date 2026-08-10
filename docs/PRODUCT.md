# Product

This document explains what Twin delivers — Narrative / Stance / Inject
layers, domain separation, product shape, related projects and success
criteria.

It does not redefine identity ([IDENTITY.md](IDENTITY.md)) or cognitive
concepts ([COGNITION.md](COGNITION.md)). Twin is a personal, local-first
cognitive layer so authorized tools can reason with governed context
without becoming a chat replacement. Product vs research tracks:
[IDENTITY.md](IDENTITY.md#core-claim-and-value-proposition).
Architecture: [ARCHITECTURE.md](ARCHITECTURE.md). Releases:
[CHANGELOG.md](CHANGELOG.md). Roadmap: [ROADMAP.md](ROADMAP.md).
Destination: [README](../README.md).

## Central concept: retrieval is not enough

A store that retrieves facts can help an LLM. That does not make Twin an
extension of the user’s understanding.

The product loop is three hard modules:

```text
Sense → Cognize → Inject
```

Inside Cognize and Inject, three durable concerns stay distinct:

```text
Narrative → Stance → governed action (Inject)
```

### Narrative

Narrative answers:

- what happened?
- what was decided?
- who participated?
- which evidence proves it?
- when was it true?
- is this account still fresh?

### Stance

Stance answers:

- how does the user think?
- which trade-offs do they value?
- what do they never want mixed?
- which tone do they prefer?
- when does privacy beat convenience?
- when does simplicity beat elegant architecture?

### Inject (governed action)

Inject answers:

- should I suggest something?
- should I produce a draft?
- should I remind the user?
- should I stay silent?
- should I block this account from the pack?
- should I ask for explicit confirmation?

The product boundary focuses mainly on Narrative + Domain Firewall + Stance.
Autonomous action stays out of scope until later majors
([ROADMAP.md](ROADMAP.md)). Older docs said “memory → judgment → action”;
those nouns are retired as product terms — see [GLOSSARY.md](GLOSSARY.md).

## Domain separation

A core requirement of the project is preventing improper mixing between contexts.

Examples of serious failure:

- generating a work document that mentions a relationship problem;
- using health context in a technical task;
- mixing professional problems into a family conversation;
- exposing third-party data to a cloud LLM;
- turning a competing Interpretation into a committed Narrative.

That is why every durable claim carries identity and policy fields such as:

```text
type / kind
+ domain
+ persona
+ sensitivity
+ status
+ valid_from / valid_until (when applicable)
+ evidence
```

Confidence is derived at read / Inject time — not stored as an incrementable
scalar on Narratives. The Domain Firewall decides whether an account may
enter a given context.

Example:

```yaml
rules:
  - name: relationship_not_allowed_outside_own_domain
    if:
      content_domain: [relationship, family, health, emotional]
      target_domain: [work, technical, assistant_preferences, general]
    action: block
```

The rule must not be "retrieve everything and trust the LLM". The correct approach is to block before the main LLM ever receives the content.

## Initial concept shape

The core delivery loop:

> Reduce context re-explanation in technical work, without leaking domains, using committed Narratives, revisable Situations, typed Relations, Evidence, hybrid search and Native/MCP/CLI/API surfaces.

```text
sources (connectors + files: docs, meetings, Slack, GitHub, mail, …)
        │  Sense — ingestion + normalization
        ▼
PII / privacy gates ──────► nothing sensitive leaves for the cloud unmasked
        │  Cognize — LLM-or-halt (or hard stop)
        ▼
Reflections + Interpretations ──► selective Review
        │  human commit / Stance approve when needed
        ▼
store: Narratives + EpistemicState + Stance + Evidence + Relations
      (+ embeddings + FTS as indexes)
        │
        ▼
hybrid search ──► Domain Firewall ──► Inject context pack
        │                                    ▲
        ▼                                    │
Native / MCP / CLI / API           Stance store + YAML bootstrap/export
```

Code packages are being reorganized to match these walls — see
[ARCHITECTURE.md — Code packages](ARCHITECTURE.md#code-packages-target-layout).

## Product boundary

In scope:

- technical / professional Narratives and Evidence;
- connectors and file ingest for work sources (docs, meetings, Slack, GitHub, mail, calendar, …);
- decisions, tasks, preferences (as Narratives / Stance);
- Situation / WorkEpisode correlation while Cognize situates;
- temporal graph + hybrid search;
- Native / MCP / CLI / local API;
- selective Review and evolving Stance.

Explicitly out of scope:

- personal WhatsApp;
- social networks;
- health / family / relationship as default sources;
- continuous voice or screen capture;
- autonomous automations;
- robotics;
- its own chat;
- executing actions without confirmation;
- fully imitating the user's personality.

## Related projects

### Graphiti / Zep

Relevant for temporal graphs, agent continuity, invalidation of old facts and search combining graph, text and vectors.

A possible evolution of the graph backend.

### Mem0

Relevant for consolidation and the "does this deserve to become durable?" decision. Inspires lifecycle, extraction and multi-session retrieval — mapped in Twin to Cognize + human commit, not to a product “memory” noun.

### Letta / MemGPT

Relevant for stateful agents, working vs long-term substrate and architectures where the agent manages its own continuity.

### Meetily

Relevant for local meeting capture, transcription and privacy. Can feed the episodic / Sense layer.

### Fireflies

Useful source of already-existing transcripts. Good for retrospective ingestion, as long as it is filtered for PII and confidentiality.

### Slack connectors

Source of decisions, blockers, team context and commitments. High value, high leakage risk — ownership, vault partition and domain policies are mandatory.

### Screenpipe

Inspiration for continuous local capture of screen/audio/context. Outside the current product boundary; relevant for a later multimodal layer.

## Success metrics

### Product

The product is successful if it:

- identifies and catalogues real decisions from docs and meetings;
- distinguishes decisions from proposals, questions, hypotheses and rejected alternatives;
- attributes claims to the correct participant or source;
- produces evidence for every committed Narrative;
- retrieves useful context via Inject / MCP;
- does not leak sensitive domains;
- reduces re-explanation in technical tasks;
- enables practical human Review;
- keeps data exportable.

### Possible metrics

- semantic interpretation precision;
- decision and task recall;
- proposal-versus-decision accuracy;
- speaker and participant attribution accuracy;
- evidence-span accuracy;
- duplicate rate;
- useless-candidate rate;
- correct-block rate;
- deferred-interpretation recovery rate;
- average context pack size;
- response time;
- number of manual reviews per week;
- number of times the user had to re-explain context;
- subjective satisfaction: "does it feel like the AI understood where I am?".

---

See also [FOUNDATIONS.md](FOUNDATIONS.md), [ARCHITECTURE.md](ARCHITECTURE.md), [CHANGELOG.md](CHANGELOG.md), [ROADMAP.md](ROADMAP.md), [README.md](../README.md).
