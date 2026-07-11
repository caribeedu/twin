# twin — Personal Cognitive OS

`twin` is a **local-first** layer of personal memory, judgment, privacy and context, queryable by any LLM/tool via **MCP**, a local HTTP API and a CLI.

The project is born from a practical question: **how do I reduce the friction of having to re-explain my life, my projects, my decisions, my style and my context every time I open a new LLM?**

The proposed answer is not "build yet another chatbot". Nor is it simply "do RAG". The goal is to build a personal, portable and evolving infrastructure: a computational representation of the user's memory, context and judgment, consumable by different tools — Cursor, Claude Desktop, Claude Code, ChatGPT, local models, future agents, voice interfaces and, eventually, physical systems.

In one sentence:

> Not building an AI that remembers me; building a personal cognitive infrastructure that any AI can safely consult.

---

## 1. Vision

The long-term vision for `twin` is to work as a **personal exocortex**: an external extension of the user's cognition, capable of maintaining continuity across tools, sessions, models and contexts.

The system must preserve:

- important facts;
- decisions made;
- rejected alternatives;
- tasks and commitments;
- technical preferences;
- communication preferences;
- judgment patterns;
- beliefs and opinions that change over time;
- relationships between people, projects, systems and events;
- evidence of where each memory came from;
- hard boundaries between life domains;
- privacy, PII and human control.

The ultimate ambition is to approach an experience of **human-machine integration**: not a distant AI, but a layer that feels cognitively coupled to the user. The aesthetic and emotional inspiration comes from science fiction, cyborgs, Matrix, Half-Life, Dexter, robotics and human-machine interfaces, but the implementation must be sober, local-first, auditable and incremental.

---

## 2. The problem

Modern LLMs are extremely useful, but they usually operate with incomplete context. Even with long windows and product memory, the user still needs to repeat:

- who they are;
- how they prefer answers;
- what has already been decided;
- what they are trying to build;
- which constraints exist;
- which trade-offs have already been evaluated;
- which tools they use;
- which old decisions still hold;
- which domains must not mix.

For an advanced user of AI, RAG, MCP, vectorization, PII, pipelines and agents, the problem is not "how to load files into context". The problem is deeper:

> How do I create a persistent, safe, linkable, temporal and interoperable representation of my mind/context, so that different LLMs can operate with less explanation and more understanding?

The central point is that **integration does not just mean low latency**. Latency helps, but what is really missing is **operational understanding**: the AI needs to understand what a given memory means, when it holds, in which domain it may be used and how it should affect a decision.

---

## 3. What the project is not

`twin` must not be understood as:

- a chatbot;
- a note-taking app;
- generic RAG;
- an autonomous agent;
- a vector database full of markdown;
- a Jarvis clone;
- its own UI to replace ChatGPT, Claude or Cursor.

The project is an infrastructure layer:

```text
personal/professional sources
        ↓
ingestion + normalization
        ↓
PII filter + domain classification
        ↓
structured memory extraction
        ↓
temporal graph + evidence + indexes
        ↓
privacy firewall + judgment
        ↓
safe context packs
        ↓
MCP / API / CLI / LLMs / IDEs / agents
```

The main UI can remain external. The user must not lose the convenience of existing tools. That is why MCP is a central part of the architecture.

---

## 4. Academic and conceptual foundations

The project draws on several areas: philosophy of mind, cognitive science, neuroscience, psychology, symbolic AI, knowledge graphs, human-computer interaction and cognitive architectures.

### 4.1 Extended Mind — Andy Clark and David Chalmers

The **extended mind** hypothesis, proposed by Andy Clark and David Chalmers in "The Extended Mind" (1998), argues that external tools can become part of the cognitive process when they are reliable, available and integrated into behavior.

The classic example is Otto, a person with Alzheimer's who uses a notebook as external memory. If a neurotypical person consults biological memory and Otto consults the notebook in an equally reliable way, Clark and Chalmers ask: functionally, why wouldn't the notebook be part of the cognitive system?

`twin` applies that intuition to the world of LLMs:

```text
user thinks / speaks / writes
        ↓
twin retrieves relevant context, judgment and memories
        ↓
main LLM reasons over that substrate
        ↓
user keeps thinking with the machine
```

The goal is not just "storing data", but creating a system coupled to the user's cognition.

### 4.2 4E Cognition

The **4E cognition** school understands cognition as:

- embodied — incorporated in the body;
- embedded — situated in an environment;
- extended — extended through tools;
- enactive — produced in active interaction with the world.

This line matters because the project does not treat thinking as something isolated inside the brain. The user thinks with tools, IDEs, documents, meetings, Slack, email, calendar, voice, notes and LLMs. `twin` tries to turn that scattered set into a coherent computational layer.

### 4.3 Memory systems

Cognitive psychology and neuroscience distinguish multiple memory systems. This inspires the project's internal separation.

| Cognitive system | Function | Abstraction in `twin` |
|---|---|---|
| Episodic memory | events, meetings, conversations, temporal context | `event`, `source`, `evidence`, timeline |
| Semantic memory | facts, concepts, consolidated relationships | `fact`, entities, relations, graph |
| Procedural memory | ways of doing, habits, workflows | `procedure`, playbooks, scripts |
| Working memory | current task focus | current query, observer, context pack |
| Executive control | selection, inhibition, judgment | Domain Firewall, policies, judgment profile |

The hippocampus inspires the episodic capture and temporal consolidation layer. The associative cortex inspires semantic memory. The prefrontal cortex inspires the judgment, inhibition and context selection layer.

### 4.4 Hippocampus, consolidation and temporality

The hippocampus is associated with episodic memory, contextual navigation, linking between events and consolidation. Computationally, this suggests the system should not store only raw documents, but events with:

- date;
- source;
- participants;
- evidence;
- domain;
- validity;
- relationship to previous memories.

Example:

```text
2026-07-01
Atlas kickoff meeting
Participants: Edu, Marina, Rafael
Decision: use Postgres outbox + dedicated worker
Rejected alternative: Kafka
Future condition: revisit Kafka if volume > 50k events/day
```

This is more useful than an entire transcript dumped into context.

### 4.5 Prefrontal cortex, judgment and inhibition

The prefrontal cortex is associated with planning, executive control, inhibition, action selection, goals and decision making. The computational inspiration is clear: memory alone is not enough.

Without judgment, each LLM interprets the user in its own way. With explicit judgment, different models can operate with more consistent principles.

Example:

```yaml
principles:
  - privacy > convenience for personal data
  - maintainability > beautiful architecture in personal projects
  - never mix intimate context with work
  - prefer direct clarity over empty politeness
```

This is different from a factual memory. It is a decision model.

### 4.6 Amygdala, salience and risk

The amygdala and limbic circuits are associated with emotional salience, fear, risk, reward and affective relevance. In a future version, `twin` should represent something analogous to **salience**:

- is this urgent?
- is this emotionally sensitive?
- can this cause harm if leaked?
- is this important for future decisions?
- should this become a memory or be discarded?

In the MVP, this function partially shows up as `sensitivity`, `confidence`, `needs_review` and `review_reason`.

### 4.7 Basal ganglia and action selection

The basal ganglia are frequently associated with action selection, habits and decision loops. For the project, this inspires future versions with safe automations:

```text
memory + context + judgment
        ↓
selection of a possible action
        ↓
draft / reminder / suggestion / automation with approval
```

The MVP deliberately does not execute autonomous actions. Before acting, the system needs to learn to remember, filter and judge.

### 4.8 Global Workspace Theory — Bernard Baars, Stanislas Dehaene

**Global Workspace Theory** proposes that several specialized modules operate in parallel, but only some information becomes globally available for attention, language, working memory and action.

This directly inspires the **Memory Observer**:

```text
main LLM talks with the user
        ↓
a parallel observer reads the task/conversation
        ↓
searches possibly related memories
        ↓
filters by domain, confidence and privacy
        ↓
suggests context to the main AI
```

The desired experience resembles "remembering" something: the user does not want to manually query a database. The system should suggest what looks relevant, without leaking forbidden content.

### 4.9 ACT-R — John R. Anderson

ACT-R is a cognitive architecture that separates declarative and procedural components, with activation, retrieval and production mechanisms. The project draws on that separation:

- declarative memory: facts, events, decisions;
- procedural memory: how the user usually does something;
- production/action: rules and decision criteria;
- activation: memory relevance for the current context.

`twin` does not implement ACT-R, but adopts the idea that memory and procedure are distinct categories.

### 4.10 Predictive Processing and Active Inference — Karl Friston

Predictive processing and active inference models treat the brain as a system that maintains internal models, predicts the world and updates beliefs upon receiving prediction error.

For `twin`, this implies the system should not store only loose sentences like "Edu prefers X". It should track the evolution of mental models:

```text
2023: Edu considered microservices preferable for almost everything.
2026: Edu came to prefer a modular monolith when maintainability and simplicity matter more.
Reason: hands-on experience with operational complexity.
```

This calls for temporality, contradiction, supersedence and belief history.

### 4.11 Self-complexity and social roles

Psychology discusses that a person does not operate with a single homogeneous "self". There are social and contextual roles:

- the developer self;
- the boyfriend self;
- the son self;
- the friend self;
- the manager self;
- the patient self;
- the investor self;
- the private-individual self.

These roles share some memories, but not all. This point is crucial for privacy.

`twin` must not model only `Edu -> everything`. It must model:

```text
Edu
 ├── persona: developer
 │    └── domain: work/technical
 ├── persona: partner
 │    └── domain: relationship
 ├── persona: son
 │    └── domain: family
 ├── persona: individual
 │    └── domain: personal/health/finance
 └── persona: assistant-user
      └── domain: assistant_preferences
```

### 4.12 Symbolic AI: semantic networks, frames and scripts

Before LLMs, symbolic AI already represented knowledge with semantic networks, frames and scripts.

`twin` reuses those ideas:

- triples/edges: `Edu -> prefers -> pt-BR answers`;
- frames: a technical decision with slots for context, alternatives, risks and consequence;
- scripts: recurring sequences of how the user decides or works;
- policies: explicit privacy and judgment rules.

Frame example:

```json
{
  "frame": "TechnicalDecision",
  "project": "Atlas",
  "decision": "Use Postgres outbox + dedicated worker",
  "alternatives_rejected": ["Kafka", "trigger + pg_notify"],
  "rationale": "Current volume does not justify operational complexity",
  "revisit_when": "volume > 50k events/day"
}
```

---

## 5. Central concept: memory is not enough

A memory store can help an LLM retrieve facts. But that does not guarantee it acts as an extension of the user.

The project needs three layers:

```text
memory → judgment → action
```

### 5.1 Memory

Memory answers:

- what happened?
- what was decided?
- who participated?
- which source proves it?
- when was it true?

### 5.2 Judgment

Judgment answers:

- how does the user think?
- which trade-offs do they value?
- what do they never want mixed?
- which tone do they prefer?
- when does privacy beat convenience?
- when does simplicity beat elegant architecture?

### 5.3 Action

Action answers:

- should I suggest something?
- should I produce a draft?
- should I remind the user?
- should I stay silent?
- should I block a memory?
- should I ask for explicit confirmation?

The MVP focuses mainly on memory + firewall + initial judgment. Autonomous action is left for future versions.

---

## 6. Domain separation

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

---

## 7. MVP architecture

The current MVP proves one thing:

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
MCP / API / CLI                    judgment profile (YAML)
```

---


## 8. Architecture Principles

These principles are the constitution of `twin`. Roadmaps can change, backends can change and interfaces can change, but new features should remain compatible with these rules. When an implementation choice is ambiguous, the preferred option is the one that preserves safety, evidence, portability and cognitive continuity.

### 8.1 Artifact ≠ Percept ≠ Memory ≠ Judgment

An artifact is a source object: a transcript, document, email, note, issue, code file or message. A percept is what the system notices from that artifact. A memory is a durable structured claim extracted from one or more percepts. A judgment is a decision rule, preference, value or trade-off that influences future reasoning.

Keeping these categories separate prevents the system from treating raw text as truth or treating a temporary interpretation as a stable belief. A meeting transcript may contain noise, jokes, contradictions and tentative ideas; a memory should preserve only what can be represented with evidence, confidence, time and domain. Judgment is even more sensitive: it changes how future tools act on behalf of the user and therefore requires a higher bar.

This separation also gives implementers a practical test. If a feature stores everything it sees as memory, it is probably wrong. If it lets an LLM infer a durable judgment from one casual sentence without review, it is unsafe. If it can explain which artifact produced which percept, which percept became which memory and which memory influenced which judgment, it is aligned with the architecture.

### 8.2 Canonical memory > embeddings

The canonical memory of `twin` is structured, temporal, evidenced and exportable. It is made of memory items, entities, relations, evidence, domains, validity windows, confidence and status. Embeddings can help retrieve this memory, but they are not the memory itself.

This matters because embeddings are opaque and model-dependent. They cannot reliably answer why a memory exists, when it was true, which source supports it or whether it is allowed in a given domain. A vector can make something searchable; it cannot be the authoritative representation of the user's life, projects or judgment.

When there is a conflict between preserving clean canonical memory and improving vector search convenience, canonical memory wins. The system should be able to delete every embedding, regenerate indexes and still preserve the user's actual cognitive substrate.

### 8.3 Embeddings are disposable indexes

Embeddings are an implementation detail for retrieval. They are useful, powerful and often necessary, but they should be treated like cache files, search indexes or compiled artifacts: valuable for performance, not authoritative for truth.

This principle protects the project from vendor lock-in and from accidental ontology drift. If a future embedding model is better, cheaper, more private or more local, `twin` should be able to re-embed everything without rewriting its memory model. If an embedding is corrupted, stale or produced by a deprecated model, the system should degrade search quality, not lose memory.

Every embedding should therefore be reproducible from canonical content and metadata. Implementations should record enough information to know how an index was produced, but they should never require that index to be permanent.

### 8.4 Firewall before the LLM

Privacy and domain separation must happen before the main LLM sees context. The system must not retrieve everything and ask the model to be careful. The model should receive only the memories that are allowed for the current target domain, persona, sensitivity level and task.

This is one of the project's hard safety boundaries. Once sensitive context enters a model prompt, the leak has already happened. Even if the model behaves well, the system has lost the ability to prove that forbidden content was not considered. A firewall is therefore not a formatting layer; it is an access-control layer.

Features that bypass the firewall for convenience are architectural regressions. The right flow is retrieval, classification, filtering, logging and then context packing. The LLM reasons over the safe pack, not over the raw memory universe.

### 8.5 Memory and judgment evolve independently

Memory describes what happened, what was decided, what exists and what evidence supports it. Judgment describes how the user tends to decide, prioritize, reject, approve or communicate. They are related, but they should not be collapsed into the same mechanism.

A new memory can be added without changing judgment. For example, a project may adopt PostgreSQL without changing the user's general preference for simple infrastructure. Conversely, judgment can evolve after many memories accumulate: repeated operational pain may change the user's preference away from distributed systems. The evolution paths are different.

This independence makes the system safer and more explainable. Durable judgment changes should usually require stronger evidence, aggregation across sessions or explicit human approval. Memory can be frequent; judgment should be conservative.

### 8.6 Sessions are the unit of cognitive change

A session is where context, intention, evidence and interpretation meet. It may be a conversation, work block, meeting, debugging run or planning episode. `twin` should treat sessions as the primary unit for observing cognitive change.

This prevents the system from overreacting to isolated sentences. A single utterance may be exploratory, emotional or provisional. A session gives the system enough surrounding context to understand whether something was a decision, a rejected option, a preference, a temporary constraint or just brainstorming.

Session-based change also improves auditability. Instead of asking "why does the system believe this?", the user can inspect which session produced the candidate memory or judgment update, what evidence was present and whether the conclusion still holds.

### 8.7 Evidence is mandatory

Every durable memory must point back to evidence. Evidence can be a source document, transcript segment, commit, issue, note, calendar event, message or explicit user confirmation. Without evidence, the system may hold a hypothesis, but it should not promote it to confirmed memory.

Evidence is what makes the system inspectable. It lets the user correct bad extraction, distinguish fact from interpretation and understand why a future LLM received a particular context pack. It also gives implementers a defense against silent hallucinated memory.

This principle does not mean all evidence must be public or exposed to every tool. Evidence has its own sensitivity and domain. But the link must exist inside the local system so the user can audit, export, revise or delete it.

### 8.8 Every memory has temporal validity

Memories are not timeless strings. Preferences change, projects end, relationships evolve, architectures are replaced and old decisions become invalid under new constraints. A useful cognitive system must know not only what was true, but when it was true and when it may need review.

Temporal validity can be explicit, such as `valid_from` and `valid_until`, or conditional, such as "revisit Kafka if volume exceeds 50k events/day". It can also be represented through supersedence: a newer memory may replace or narrow an older one without deleting history.

This is essential for avoiding stale personalization. The system should not keep telling future tools that the user prefers something merely because it was true years ago. It should preserve history while making current context clear.

### 8.9 Project-first cognition

Much of the user's practical cognition is organized around projects. A project carries goals, constraints, decisions, rejected alternatives, people, artifacts, timelines, risks and conventions. `twin` should therefore make project context a first-class retrieval and organization unit.

Project-first cognition avoids generic personalization. The same user may prefer different trade-offs in different projects: speed in a prototype, maintainability in a long-lived system, privacy in a personal tool, compliance in professional work. The project is often the missing boundary that tells the system which memories are relevant.

Implementations should make it easy to ask: what does `twin` know about this project, what decisions are still valid, what alternatives were rejected and what context must not cross into other projects?

### 8.10 MCP is the primary interface

`twin` should be useful from many tools, not trapped inside a custom UI. MCP is the primary interface because it lets IDEs, desktop assistants, coding agents and future tools safely request memory, context and judgment through explicit capabilities.

This keeps the project aligned with its role as infrastructure. The goal is not to replace ChatGPT, Claude, Cursor or future interfaces. The goal is to make them better by giving them a portable, filtered and auditable cognitive substrate.

A feature that only works in one UI is less valuable than a capability exposed through MCP, API and CLI. Interfaces may differ, but the same memory and firewall semantics should be available everywhere.

### 8.11 Local-first by default

The default assumption is that personal memory, judgment, evidence and indexes live locally under user control. Cloud services may be useful for specific extraction, backup or collaboration flows, but they should not become mandatory for the core system to function.

Local-first is not nostalgia; it is a safety and agency requirement. The data in `twin` can contain private life context, third-party information, work constraints, health hints, relationship details and decision patterns. The user must be able to inspect it, back it up, delete it, move it and run the core system without asking a vendor for permission.

This principle also improves longevity. A personal cognitive OS should outlive model providers, SaaS pricing changes and product shutdowns. Local data plus open export paths are what make that possible.

### 8.12 Exportability over lock-in

The user must be able to leave. Exportability is not a nice-to-have; it is a moral and architectural requirement for a system that stores personal cognition. Memories, evidence, entities, relations, policies, judgment profiles and indexes metadata should be representable in formats that can be inspected and migrated.

This protects the user from the project itself. If `twin` succeeds, it may become deeply integrated into the user's thinking and work. That makes lock-in especially dangerous. The more important the system becomes, the easier it must be to audit and exit.

Implementers should prefer boring, documented and portable representations over clever storage tricks that only one runtime understands. Performance optimizations are welcome when they do not compromise export.

### 8.13 Human approval for durable judgment changes

Judgment changes affect future behavior. They can change what the system recommends, blocks, prioritizes, summarizes or exposes. For that reason, durable changes to judgment should require explicit human approval or a conservative review workflow.

The system may propose judgment updates. It may notice repeated patterns, contradictions or stable preferences. But proposing is different from deciding. A user saying "this project is messy" during a frustrating session should not automatically become a durable belief that the user hates complexity everywhere.

This principle preserves agency. `twin` can learn with the user, but it should not silently rewrite the user's values, boundaries or decision model.

### 8.14 Deterministic pipeline first; LLM where it adds measurable value

The default architecture should be deterministic where correctness, safety and auditability matter: schema validation, domain filtering, policy enforcement, evidence links, status transitions, exports and logging. LLMs should be used where they add measurable value: extraction, summarization, classification assistance, semantic interpretation and candidate generation.

This avoids building a system whose core behavior is impossible to reproduce or debug. If a memory was blocked, accepted, exported or marked as sensitive, the user should be able to understand the rule path. LLM output may inform the pipeline, but it should not replace the pipeline.

A good implementation asks: what part must be reliable and testable, and what part benefits from language understanding? The answer should shape the boundary between code and model.

### 8.15 Progressive sophistication (MVP before brain)

`twin` is inspired by ambitious ideas: exocortex, cognitive architectures, memory systems and human-machine integration. But the implementation must progress through small, useful, testable stages. The project should earn complexity only after the simpler layer works.

This protects the project from premature "brain-building". A reliable importer, memory schema, firewall, context pack and MCP tool are more valuable than an impressive but unsafe agent loop. The system should first remember accurately, filter safely and explain itself clearly.

Progressive sophistication does not reduce the vision; it makes the vision survivable. Each version should create practical value while preserving the path toward deeper cognition.


## 9. Stack and technical decisions

### 9.1 Local-first

Everything lives in `~/.twin` or `$TWIN_HOME`:

- SQLite;
- policies YAML;
- judgment YAML;
- exportable data;
- simple backups.

Backup = copy the folder.

Full export = `twin export`.

### 9.2 SQLite as a light graph

The MVP uses SQLite with tables for:

- sources;
- memories;
- evidence;
- entities;
- memory_entities;
- relations;
- embeddings;
- firewall_log;
- FTS5.

That choice avoids heavy infrastructure too early. Today the storage lives
behind a single interface (`MemoryStore`): **PostgreSQL + pgvector is the
primary backend** (server-side vector search, tsvector/GIN for full-text,
JSONB) and SQLite remains the zero-config backend for dev/tests.
Neo4j, FalkorDB or Graphiti may come later, but the canonical memory must
remain exportable.

### 9.3 Vectors as index, not as memory

Embeddings are useful for semantic search, but they are not the true memory.

Project rule:

```text
graph + events + evidence = canonical memory
vectors = regenerable index
LLM = extractor/interpreter
MCP = interface
```

This avoids lock-in and allows reindexing in the future.

### 9.4 Hybrid search

Search combines:

- FTS5/BM25;
- embeddings;
- entity boost;
- firewall filtering.

Search must answer not only "what looks semantically similar?", but "what is relevant, allowed and trustworthy for this context?".

### 9.5 MCP-first

The project must not depend on its own UI. MCP lets external tools query `twin`.

Exposed tools:

| tool | function |
|---|---|
| `memory_safe_context_pack` | main: compact pack filtered by the firewall |
| `memory_search` | hybrid search with domain filtering |
| `memory_get` | memory by id with evidence |
| `memory_related` | entity neighborhood in the graph |
| `memory_project_context` | context about a project |
| `memory_recent_decisions` | recent decisions |
| `memory_user_preferences` | stable preferences |
| `memory_judgment_profile` | judgment profile |
| `memory_observe` | memory observer for the current text/task |

---

## 10. Data model

### 10.1 Memory Item

A memory item must contain:

```json
{
  "id": "mem_...",
  "type": "event | fact | decision | preference | belief | task | procedure | relationship | communication_act | constraint",
  "title": "...",
  "summary": "...",
  "domain": "work | technical | personal_preferences | assistant_preferences | relationship | family | health | finance | legal | emotional | general",
  "persona": "developer | individual | partner | son | friend | manager | assistant-user",
  "sensitivity": "public | internal | private | restricted",
  "confidence": 0.0,
  "status": "candidate | confirmed | rejected | deprecated | contradicted",
  "valid_from": "YYYY-MM-DD",
  "valid_until": null,
  "payload": {},
  "needs_review": true,
  "review_reason": "...",
  "source_ids": ["src_..."],
  "entities": ["Atlas", "FastAPI", "Postgres"]
}
```

### 10.2 Memory types

| Type | Meaning |
|---|---|
| `event` | something that happened |
| `fact` | relatively objective fact |
| `decision` | decision made, with rationale and consequence |
| `preference` | stable or semi-stable preference |
| `belief` | belief/opinion that may change |
| `task` | task, commitment or promise |
| `procedure` | way of doing something |
| `relationship` | relationship between people/contexts |
| `communication_act` | communicative act: request, promise, refusal, apology, decision |
| `constraint` | rule, limit or prohibition |

### 10.3 Mandatory evidence

Every memory must carry evidence, preferably a verbatim excerpt from the source.

Without evidence, a memory is suspect.

This reduces memory hallucination and enables human review.

### 10.4 Temporality

Memories must have temporal validity.

Example:

```text
2025: works at Ambev
2026: works at Shippo
```

Both can be true, but not simultaneously.

Desired future:

- `supersedes`;
- `contradicts`;
- `deprecated_by`;
- automatic `valid_until`;
- belief timeline.

---

## 11. Ingestion and extraction pipeline

Flow:

```text
raw source
        ↓
normalization
        ↓
PII filter
        ↓
local LLM extraction (Ollama) or heuristic
        ↓
schema normalization
        ↓
dedupe
        ↓
review classification
        ↓
graph + evidence + embedding
```

MVP sources:

- markdown;
- `.txt` transcripts;
- Fireflies/Meetily-style `.json` meetings;
- Slack `.json` exports;
- technical documents.

Future sources:

- Gmail;
- Outlook;
- WhatsApp;
- calendar;
- social networks;
- personal notes;
- local screen/voice;
- wearables;
- robotics/home automation.

---

## 12. PII and privacy

The project assumes that leaking personal data can cause real harm.

Before any cloud LLM, text must go through PII masking.

Classes covered today:

- emails;
- phone numbers;
- CPF / CNPJ / RG / CEP;
- street addresses (Rua/Av./…);
- cards, IBAN, PIX keys;
- IPs;
- API keys (OpenAI-style, GitHub/GitLab PATs, Slack, AWS, Google);
- JWTs and bearer tokens;
- passwords and secret assignments;
- private keys.

Before real personal sources, expand to:

- sensitive proper names;
- family member names;
- partner names;
- addresses;
- banking data;
- medical data;
- private URLs;
- internal company identifiers;
- private Jira/GitHub links;
- customer names;
- third-party data.

Rule: sensitive data must be blocked, masked, hashed or kept local.

---

## 13. Selective review

The user must not review everything manually. Review should happen by exception.

A memory goes to review when:

- confidence < threshold;
- sensitivity is `private` or `restricted`;
- domain is outside the MVP;
- type is judgment-adjacent (`belief`, `procedure`);
- the memory seems to update/contradict another;
- there is partial duplication;
- the memory has high impact;
- the source has low trustworthiness;
- the memory may affect future behavior.

States:

```text
candidate → confirmed
candidate → rejected
confirmed → deprecated
confirmed → contradicted
confirmed → superseded (future)
```

---

## 14. Judgment profile

Memories say **what happened**.

Judgment says **how the user thinks**.

Example:

```yaml
principles:
  - privacy > convenience for personal data
  - maintainability > beautiful architecture in personal projects
  - never mix intimate context with work
  - prefer direct clarity over empty politeness

technical_preferences:
  - avoid overengineering
  - prefer a simple stack for an MVP
  - evaluate lock-in before adopting a tool
  - canonical data in an open, exportable format

decision_criteria:
  - compare maintenance cost before performance
  - evaluate decision reversibility
  - measure real usefulness before expanding scope

communication_style:
  language: pt-BR by default
  tone: direct, technical, no basic tips
```

Important next step: allow the system to propose changes to the judgment profile from confirmed memories, but **never write automatically without human approval**.

---

## 15. Memory Observer

The Memory Observer is a parallel AI/module that follows the current text and suggests related memories.

It does not answer for the user. It must not act. It only remembers.

Flow:

```text
current text / task / draft
        ↓
domain inference
        ↓
candidate memory search
        ↓
firewall
        ↓
ranking
        ↓
compact suggestion for the main AI
```

This is inspired by Global Workspace Theory: many modules operate in parallel, but only some information enters the global workspace.

Desired format:

```json
{
  "inferred_domain": "technical",
  "suggested_context": [
    {
      "memory_id": "mem_...",
      "summary": "...",
      "why_relevant": "semantic similarity + entity match",
      "confidence": 0.87,
      "allowed": true
    }
  ],
  "blocked_context": [
    {
      "memory_id": "mem_...",
      "reason": "relationship_not_allowed_outside_own_domain"
    }
  ]
}
```

---

## 16. Installation

```bash
pip install -e ".[dev]"        # everything (api + mcp + postgres + crypto + tests)
# or granular:
pip install -e ".[api,mcp,postgres,crypto]"

twin init                      # creates ~/.twin (policies.yaml, judgment.yaml)
```

---

## 17. Basic flow

```bash
# 1. Ingestion: markdown, .txt transcripts, .json meetings, Slack .json exports
twin ingest ./docs ./transcripts ./meetings

# 2. Memory extraction
twin extract

# 3. Selective review
twin review            # terminal
twin serve             # web UI at http://127.0.0.1:8765

# 4. Query
twin search "which stack do we use in the webhooks service"
twin pack "write the Atlas architecture RFC" --domain technical
twin observe "I'm reviewing the webhooks retry"

# 5. Curation and lifecycle
twin promote mem_xxx           # memory becomes part of the judgment profile
twin supersede mem_new mem_old
twin contradict mem_a mem_b
twin stats                     # memory quality metrics
twin reindex                   # after switching embedders
```

---

## 18. MCP

```bash
twin mcp
```

Configuration in compatible clients:

```json
{
  "mcpServers": {
    "twin": {
      "command": "twin",
      "args": ["mcp"]
    }
  }
}
```

Recommended usage for clients:

1. at the start of technical tasks, call `memory_safe_context_pack`;
2. use the correct `target_domain`;
3. respect `blocked`;
4. do not request sensitive memories without explicit authorization;
5. cite sources/memories when using specific content;
6. do not treat `candidate` as established fact (by default, packs already contain only confirmed memories).

Per-client integration guide (Claude Code, Claude Desktop, Cursor,
troubleshooting): [docs/mcp-clients.md](docs/mcp-clients.md).

---

## 19. Local API

`twin serve` starts:

- a minimal review UI;
- a JSON API;
- interactive docs.

Main endpoints:

```text
/api/ingest
/api/extract
/api/percepts
/api/memories
/api/memories/{id}/review
/api/memories/{id}/promote
/api/memories/{id}/supersede/{old_id}
/api/memories/{id}/contradict/{other_id}
/api/search
/api/context_pack
/api/observer
/api/judgment
/api/metrics
/api/export
```

---

## 20. Configuration

| variable | default | effect |
|---|---|---|
| `TWIN_HOME` | `~/.twin` | config directory (policies/judgment) |
| `TWIN_DB_URL` | `sqlite:///~/.twin/twin.db` | `postgresql://…` selects the primary backend (pgvector) |
| `TWIN_OLLAMA_URL` | `http://127.0.0.1:11434` | local Ollama server |
| `TWIN_OLLAMA_MODEL` | `qwen3:8b` | local extraction model |
| `TWIN_OLLAMA_EMBED_MODEL` | `nomic-embed-text` | local embedding model |
| `TWIN_EXTRACTOR` | `auto` | `auto` / `ollama` / `heuristic` |
| `TWIN_EMBEDDER` | `auto` | `auto` / `ollama` / `hash` |
| `TWIN_ENCRYPTION_KEY` | — | when set, encrypts raw content and evidence at rest |

Everything runs on local models; there is no cloud LLM option. Embeddings
are not the source of truth: they are regenerable (`twin reindex`) and never
mix across different models.

---

## 21. Tests

```bash
python -m pytest
```

Expected coverage:

- PII;
- ingestion;
- extraction;
- dedupe;
- firewall;
- search;
- context pack;
- observer;
- API;
- MCP.

---

## 22. MVP scope

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

---

## 23. Roadmap

### v0.1 — Local Technical Memory

Prove the system reduces re-explanation in technical work.

Delivered:

- local ingestion with normalized percepts;
- local extraction through Ollama with an offline heuristic fallback;
- selective review and confirmed-only context packs by default;
- sectioned context packs with judgment, decisions, constraints, tasks, preferences, facts/events and evidence;
- source qualification through trust, scope and confidentiality;
- explicit promotion, supersedence and contradiction lifecycle operations;
- memory quality metrics;
- expanded PII detection and optional local encryption;
- PostgreSQL + pgvector and zero-config SQLite backends;
- MCP, API, CLI and per-client MCP documentation;
- initial observer domain inference using keywords and graph signals;
- initial judgment profile.

### v0.2 — Operational Cognitive Workflow

Goal: move `twin` from a demonstrable memory service into a tool that can be used continuously in real technical work. v0.2 closes the loop between retrieving existing context and capturing what changed during the task.

The target workflow is:

```text
start a real task in an MCP client
        ↓
identify project, domain and task profile
        ↓
load a compact, task-aware context pack
        ↓
perform the work in the external LLM/IDE
        ↓
complete the cognitive session
        ↓
turn decisions, constraints and changes into candidate memories
        ↓
review and consolidate
```

#### Cognitive session lifecycle

Introduce a first-class `CognitiveSession` that records:

- client and project;
- active domain and task profile;
- initial task/query;
- memories supplied to the client;
- artifacts produced or changed;
- candidate memories created at completion;
- explicit usefulness feedback;
- start, completion and abandonment states.

Expose the lifecycle through MCP, API and CLI operations equivalent to:

```text
session_start
session_observe
session_complete
session_feedback
```

The session boundary must close the current read-only flow:

```text
Twin → LLM
```

into a maintained cognitive loop:

```text
Twin → LLM → completed work → new percepts → candidate memories → Twin
```

#### Task-aware context packs

Evolve the existing sectioned context pack into profiles tailored to the current work:

- coding;
- architecture;
- debugging;
- writing;
- planning;
- review;
- meeting preparation.

Each profile should preserve the same firewall and evidence guarantees while changing ordering and token allocation. An architecture pack, for example, should prioritize prior decisions, rejected alternatives, constraints, judgment criteria, open questions and evidence; a coding pack should prioritize active project context, implementation constraints, conventions, known risks and relevant decisions.

#### Projects as first-class cognitive units

Promote projects from loosely inferred graph entities into explicit structures connected to:

- repositories and aliases;
- goals and milestones;
- active and superseded decisions;
- constraints;
- open questions;
- sessions;
- percepts and artifacts;
- people and systems;
- project timeline.

The current repository/directory should be usable as a strong signal for project inference in developer clients.

#### Product-level feedback and evaluation

Extend current pipeline metrics with explicit context-usefulness feedback:

```text
useful
partially_useful
irrelevant
incorrect
missing_context
privacy_overblock
privacy_underblock
```

Track product metrics such as:

- context relevance rate;
- false-memory rate;
- missing-memory rate;
- project/domain misclassification rate;
- context-pack token efficiency;
- memory usage rate;
- session re-explanation rate.

The central product metric is: **how often did the user need to explain something that `twin` should already have known?**

#### Multi-stage retrieval and local reranking

Make retrieval an explicit pipeline:

```text
project/domain/task detection
        ↓
lexical + vector candidate generation
        ↓
graph expansion and temporal filtering
        ↓
Domain Firewall and source-trust weighting
        ↓
local reranking
        ↓
task-aware context construction
```

Keep deterministic hybrid search as the baseline and fallback. Add a local reranker only where it measurably improves relevance.

#### Fast and deep observer modes

Split observation into two levels:

- **fast observer:** deterministic keywords, entity matches, project/repository context and graph votes; cheap enough to run routinely;
- **deep observer:** local LLM classification used only when domain, project, task or intent remains ambiguous.

Observer output should include confidence and uncertainty for domain, project and task profile, not only a single inferred domain.

#### Real MCP workflow validation

Treat MCP compatibility as a tested product surface rather than documentation alone. Validate complete workflows in:

- Claude Code;
- Cursor;
- Claude Desktop;
- the CLI reference client;
- generic MCP clients where possible.

The compatibility matrix should cover session start, context loading, observation, session completion and feedback, while accounting for capabilities each client may not expose automatically.

#### Installation and operations ergonomics

Add operational commands such as:

```text
twin doctor
twin setup ollama
twin setup postgres
twin setup mcp <client>
```

`twin doctor` should verify models, stores, pgvector, migrations, encryption configuration, policies, judgment profile, embeddings and MCP client configuration.

#### Incremental developer sensors

Add continuous but controlled ingestion for technical work before broader external connectors:

- filesystem/document watching;
- Git commits, branches and repository metadata;
- changed ADRs and technical documentation;
- optional session-produced artifact summaries.

Preserve the distinction:

```text
artifact != percept != memory
```

An artifact is the original file, commit, PR or transcript; a percept is the normalized observation emitted by a sensor; a memory is consolidated knowledge extracted from evidence.

#### v0.2 completion criteria

v0.2 is complete when the following scenario works end to end:

1. open a repository in Cursor or Claude Code;
2. begin a task without re-explaining the complete architecture;
3. `twin` identifies the project, domain and task profile;
4. it supplies relevant decisions, constraints, preferences and evidence;
5. the external tool completes the task;
6. the cognitive session is completed;
7. changes become percepts and candidate memories;
8. the user can review and consolidate them;
9. usefulness feedback is recorded;
10. equivalent context remains available from another MCP client.

### v0.3 — Memory Quality and Review at Scale

Goal: make memory curation reliable as the number of sources and sessions grows.

The first lifecycle primitives, source trust and quality metrics already exist. v0.3 should deepen them through:

- batch review and keyboard-efficient review workflows;
- side-by-side diffs for similar, conflicting and superseding memories;
- merge and split operations beyond the existing supersede/contradict actions;
- source-specific extraction calibration and trust adjustment;
- review prioritization by impact, uncertainty and sensitivity;
- evaluation datasets and repeatable extraction/retrieval benchmarks;
- richer provenance chains from memory to percept to original artifact;
- retention, archival and deletion propagation policies.

### v0.4 — Evolving Judgment Model

Goal: make different LLMs apply a stable yet evolving model of how the user evaluates trade-offs.

Promotion from confirmed memories into the judgment profile already exists. v0.4 should add:

- proposed judgment changes derived from repeated confirmed evidence;
- explicit separation of preference, belief, principle, value, heuristic and hard constraint;
- versioned judgment with temporal validity and provenance;
- conflict detection between principles and observed behavior;
- confidence and scope for each judgment item;
- domain-specific decision criteria;
- simulations that explain how a judgment profile affected a recommendation;
- mandatory human approval for durable judgment changes.

### v0.5 — Persona-aware Privacy and Governance

Goal: prepare the system for sensitive personal domains without relying on the main LLM to enforce boundaries.

Candidate memories are already excluded from packs by default, firewall decisions are logged, PII detection is broad and encryption is available. v0.5 should add:

- policies scoped by persona, purpose, audience, source ownership and target tool;
- explicit, time-limited permission grants;
- contextual redaction rather than only allow/block decisions;
- field-level sensitivity and encrypted searchable metadata where practical;
- stronger default-deny rules for cross-domain retrieval;
- consent and third-party-data policies;
- prompt-injection quarantine for ingested content;
- deletion propagation through memories, evidence, embeddings and exports;
- privacy regression tests and intentional leakage canaries.

### v0.6 — Professional Connectors

Goal: capture operational knowledge from work through authorized, incremental connectors rather than manual exports alone.

Prioritize:

- GitHub repositories, commits, pull requests, issues and review discussions;
- Slack channels and threads;
- professional Gmail and Outlook;
- Calendar;
- Fireflies;
- Meetily;
- shared technical documents.

Each connector must preserve authorization, source ownership, incremental checkpoints, provenance, confidentiality and deletion behavior. Employer data should remain physically and cryptographically separable from personal data when policy requires it.

### v0.7 — Personal Domains

Goal: expand carefully from technical memory into a compartmentalized representation of personal life.

Potential domains:

- finance;
- home;
- personal goals;
- relationships;
- family;
- health;
- social identity.

This version requires the governance work from v0.5, stronger PII/entity handling, explicit consent, stricter review and preferably physically separate vaults. It should not assume that information about third parties is automatically authorized for unrestricted ingestion or use.

### v0.8 — Parallel Memory and Consolidation

Goal: move from an on-demand observer toward a continuously updated extended-memory process inspired by the Global Workspace model.

Build on the fast/deep observer introduced in v0.2 with:

- real-time observation of supported sessions;
- proactive but non-intrusive memory suggestions;
- confidence-aware spontaneous recall;
- parallel extraction of what changed during conversation;
- daily and weekly consolidation cycles;
- temporal belief and goal updates;
- salience, novelty and contradiction detection;
- silent blocking of forbidden memories;
- clear separation between suggestion, memory candidate and durable consolidation.

### v0.9 — Voice Companion

Goal: reduce the distance between thought and the external cognitive layer.

Possibilities:

- local voice notes and transcription;
- low-latency conversational capture;
- daily reflection and memory review;
- meeting and environmental capture with explicit controls;
- hands-free memory queries;
- a conversational interface that complements rather than replaces existing tools.

### v1.0 — Personal Cognitive OS

A trustworthy, daily-usable version of the infrastructure with:

- closed cognitive sessions;
- reliable memory extraction and consolidation;
- evolving judgment with human control;
- persona-aware privacy and auditability;
- mature MCP interoperability;
- professional and selected personal connectors;
- parallel observation and controlled consolidation;
- export, backup, deletion and recovery;
- measurable reduction in context re-explanation;
- enough operational reliability to act as the user's persistent cognitive substrate.

---

## 24. Future major versions

### v2 — Extended Brain

Deepen the cognitive model beyond the initial memory lifecycle:

- robust episodic memory and autobiographical timelines;
- consolidated semantic memory;
- procedural memory and learned workflows;
- goals, routines and hierarchical plans;
- active personas with controlled shared context;
- daily/weekly reflection and consolidation;
- uncertainty-aware mental-model evolution;
- attention and salience mechanisms;
- counterfactual reasoning over prior decisions.

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

## 25. Related projects

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

Inspiration for continuous local capture of screen/audio/context. Not an MVP priority, but relevant for the multimodal version.

---

## 26. Success metrics

### MVP

The MVP is successful if it:

- extracts real decisions from docs/meetings;
- produces evidence for every memory;
- retrieves useful context via MCP;
- does not leak sensitive domains;
- reduces re-explanation in technical tasks;
- enables practical human review;
- keeps data exportable.

### Possible metrics

- extraction precision;
- duplicate rate;
- useless-memory rate;
- correct-block rate;
- average context pack size;
- response time;
- number of manual reviews per week;
- number of times the user had to re-explain context;
- subjective satisfaction: "does it feel like the AI understood where I am?".

---

## 27. Risks

### 27.1 Privacy

Maximum risk. The system may contain intimate and professional information. Mitigations:

- local-first;
- PII masking;
- firewall;
- logs;
- review;
- default-deny in sensitive domains;
- export/delete;
- future encryption.

### 27.2 Memory hallucination

LLMs can extract false memories. Mitigations:

- mandatory evidence;
- confidence;
- candidate status;
- selective review;
- blocking candidates in critical contexts;
- internal citations.

### 27.3 Domain mixing

The most dangerous operational risk. Mitigations:

- mandatory domain/persona/sensitivity;
- firewall before the LLM;
- block logs;
- explicit target_domain;
- tested policies.

### 27.4 Overengineering

The risk of trying to build the whole brain before the MVP. Mitigation:

- start with technical work;
- avoid WhatsApp/intimate life at the beginning;
- do not build a chat of its own;
- use MCP;
- measure real usefulness.

### 27.5 Vendor dependency

Mitigation:

- canonical data in an open format;
- regenerable embeddings;
- replaceable LLM;
- SQLite/JSON export;
- MCP as the interface.

---

## 28. Practical philosophy of the project

`twin` must follow these principles:

```text
local-first > cloud-first
structured memory > raw text
explicit judgment > implicit imitation
temporal graph > infinite markdown
vectors as index > vectors as truth
MCP > mandatory own UI
firewall before the LLM > trusting the LLM
selective review > total manual curation
mandatory evidence > sourceless memory
exportability > lock-in
```

---

## 29. Final definition

`twin` is a personal, local-first, interoperable and temporal layer of memory, judgment, privacy and context.

It exists to allow different LLMs and tools to operate over a consistent representation of the user, without requiring the user to re-explain their life, their projects and their way of thinking in every new session.

The guiding sentence:

> I don't want to just use an AI. I want to feel integrated with the machine, as if part of my cognition could exist outside my brain, with safety, continuity and control.

The MVP starts small: reliable technical memory via MCP.

The destination is bigger: a personal, portable, private and evolving extended brain.
