# Product

This document explains what Twin delivers — memory / judgment / action
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

## Central concept: memory is not enough

A memory store can help an LLM retrieve facts. But that does not guarantee it acts as an extension of the user.

The project needs three layers:

```text
memory → judgment → action
```

### Memory

Memory answers:

- what happened?
- what was decided?
- who participated?
- which source proves it?
- when was it true?

### Judgment

Judgment answers:

- how does the user think?
- which trade-offs do they value?
- what do they never want mixed?
- which tone do they prefer?
- when does privacy beat convenience?
- when does simplicity beat elegant architecture?

### Action

Action answers:

- should I suggest something?
- should I produce a draft?
- should I remind the user?
- should I stay silent?
- should I block a memory?
- should I ask for explicit confirmation?

The product boundary focuses mainly on narrative + firewall + judgment. Autonomous action stays out of scope until later majors ([ROADMAP.md](ROADMAP.md)).

## Domain separation

A core requirement of the project is preventing improper mixing between contexts.

Examples of serious failure:

- generating a work document that mentions a relationship problem;
- using health context in a technical task;
- mixing professional problems into a family conversation;
- exposing third-party data to a cloud LLM;
- turning a false candidate memory into a confirmed fact.

That is why every memory carries:

```text
type
+ domain
+ persona
+ sensitivity
+ confidence
+ status
+ valid_from/valid_until
+ evidence
```

The Domain Firewall decides whether a memory may enter a given context.

Example:

```yaml
rules:
  - name: relationship_not_allowed_outside_own_domain
    if:
      memory_domain: [relationship, family, health, emotional]
      target_domain: [work, technical, assistant_preferences, general]
    action: block
```

The rule must not be "retrieve everything and trust the LLM". The correct approach is to block before the main LLM ever receives the content.

## Initial concept shape

The core delivery loop:

> Reduce context re-explanation in technical work, without leaking domains, using structured memory, revisable episode structure, a temporal graph, vectors, FTS and Native/MCP/CLI/API surfaces.

```text
sources (connectors + files: docs, meetings, Slack, GitHub, mail, …)
        │  ingestion + normalization
        ▼
PII filter ──────────────► nothing sensitive leaves for the cloud unmasked
        │  extract and/or correlate → reflect
        ▼
candidates (atomic + trajectory) ──► selective review
        │  human approval when needed
        ▼
store (Postgres+pgvector primary | SQLite local): memories + entities + relations + evidence + embeddings + FTS
        │
        ▼
hybrid search ──► Domain Firewall ──► compact context pack
        │                                    ▲
        ▼                                    │
Native / MCP / CLI / API           judgment store (DB) + YAML bootstrap/export
```

## Product boundary

In scope:

- technical / professional memory;
- connectors and file ingest for work sources (docs, meetings, Slack, GitHub, mail, calendar, …);
- decisions, tasks, preferences;
- WorkEpisode correlation and trajectory candidates;
- temporal graph + hybrid search;
- Native / MCP / CLI / local API;
- selective review and evolving judgment.

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

Relevant for temporal graphs, agent memory, invalidation of old facts and search combining graph, text and vectors.

A possible evolution of the graph backend.

### Mem0

Relevant for memory consolidation and the "does this deserve to become a memory?" decision. Inspires lifecycle, extraction and multi-session retrieval.

### Letta / MemGPT

Relevant for stateful agents, working vs long-term memory and architectures where the agent manages its own memory.

### Meetily

Relevant for local meeting capture, transcription and privacy. Can feed the episodic layer.

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
- produces evidence for every memory;
- retrieves useful context via MCP;
- does not leak sensitive domains;
- reduces re-explanation in technical tasks;
- enables practical human review;
- keeps data exportable.

### Possible metrics

- semantic interpretation precision;
- decision and task recall;
- proposal-versus-decision accuracy;
- speaker and participant attribution accuracy;
- evidence-span accuracy;
- duplicate rate;
- useless-memory rate;
- correct-block rate;
- deferred-interpretation recovery rate;
- average context pack size;
- response time;
- number of manual reviews per week;
- number of times the user had to re-explain context;
- subjective satisfaction: "does it feel like the AI understood where I am?".

---

See also [FOUNDATIONS.md](FOUNDATIONS.md), [ARCHITECTURE.md](ARCHITECTURE.md), [CHANGELOG.md](CHANGELOG.md), [ROADMAP.md](ROADMAP.md), [README.md](../README.md).
