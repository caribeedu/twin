[← README](../README.md) · [FOUNDATIONS](FOUNDATIONS.md) · [PRODUCT](PRODUCT.md) · [ROADMAP](ROADMAP.md) · [CHANGELOG](CHANGELOG.md) · [ARCHITECTURE](ARCHITECTURE.md) · [INTERFACES](INTERFACES.md) · [SETUP](SETUP.md) · [OPERATIONS](OPERATIONS.md)

# Product

**Source of truth for:** what Twin delivers — memory / judgment / action layers, domain separation, initial concept shape, related projects and success criteria.

Twin is a personal, local-first cognitive layer: structured memory, evolving judgment, domain firewall and interoperable access (MCP / CLI / API) so tools can reason with your context without becoming a chat replacement. Architecture principles and brain analogies live in [ARCHITECTURE.md](ARCHITECTURE.md). Delivered releases: [CHANGELOG.md](CHANGELOG.md). Future versions: [ROADMAP.md](ROADMAP.md). Overview: [README](../README.md).

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

The initial concept focuses mainly on memory + firewall + initial judgment. Autonomous action is left for future versions.

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

## initial concept architecture

The current initial concept proves one thing:

> It is possible to drastically reduce context re-explanation in technical work, without leaking domains, using structured memory, a light temporal graph, vectors, FTS and MCP.

Architecture:

```text
sources (docs, meetings, Slack)
        │  ingestion + normalization
        ▼
PII filter ──────────────► nothing sensitive leaves for the cloud unmasked
        │  extraction (local LLM via Ollama or heuristic)
        ▼
candidate memories ──► dedupe ──► selective review queue
        │  human approval when needed
        ▼
store (Postgres+pgvector primary | SQLite dev): memories + entities + relations + evidence + embeddings + FTS
        │
        ▼
hybrid search ──► Domain Firewall ──► compact context pack
        │                                    ▲
        ▼                                    │
MCP / API / CLI                    judgment store (DB) + YAML bootstrap/export
```

## Initial scope

Includes:

- technical/professional memory;
- technical docs;
- meetings;
- technical Slack;
- decisions;
- tasks;
- preferences;
- light graph;
- hybrid search;
- MCP;
- selective review;
- initial judgment.

Deliberately does not include:

- personal WhatsApp;
- social networks;
- health/family/relationship as sources;
- continuous voice;
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

### Slack MCP / Slack connectors

Source of decisions, blockers, team context and commitments. High value, high leakage risk. Must come in with strict domain and policies.

### Screenpipe

Inspiration for continuous local capture of screen/audio/context. Not an initial concept priority, but relevant for the multimodal version.

## Success metrics

### Concept

The concept is successful if it:

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

See also: [FOUNDATIONS.md](FOUNDATIONS.md), [ARCHITECTURE.md](ARCHITECTURE.md), [CHANGELOG.md](CHANGELOG.md), [ROADMAP.md](ROADMAP.md), [README.md](../README.md).
