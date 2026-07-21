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

### 3.1 Non-goals

`twin` is not trying to:

- replace ChatGPT;
- replace Claude;
- become another IDE;
- become another note-taking app;
- become another vector database;
- fine-tune the user;
- automate every task;
- store the user's entire reality for archival purposes.

These non-goals are important because they protect the project from expanding into every adjacent product category. `twin` should remain the cognitive substrate that other tools consult, not the place where all interaction must happen.

### 3.2 Why not RAG?

`twin` is not RAG. RAG retrieves documents; `twin` retrieves cognition.

A typical RAG system is organized around chunks:

```text
query
  ↓
vector search
  ↓
chunks
  ↓
LLM
```

`twin` is organized around cognitive context:

```text
query
  ↓
project
  ↓
domain
  ↓
persona
  ↓
firewall
  ↓
graph
  ↓
judgment
  ↓
observer
  ↓
context pack
```

The difference matters. RAG can find text that looks similar to a query, but it usually does not know whether that text is current, allowed, evidenced, project-specific, contradicted, sensitive or relevant to the user's decision model. `twin` may use retrieval techniques, including vectors, but retrieval is only one step inside a larger memory, privacy and judgment pipeline.

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
| Executive control | selection, inhibition, judgment | Domain Firewall, policies, evolving judgment model |

The hippocampus inspires the episodic capture and temporal consolidation layer. The associative cortex inspires semantic memory. The prefrontal cortex inspires the judgment, inhibition and context selection layer.

### 4.4 Computational Neuroscience Mapping

`twin` does not attempt to reproduce the brain. The mapping below is an engineering analogy: cognitive and neuroscience concepts inspire separations of responsibility inside the system, but the implementation remains pragmatic, auditable and software-native.

| Brain concept | Purpose | `twin` abstraction |
|---|---|---|
| Hippocampus | Episodic encoding | Percepts + Events |
| Cortex | Semantic consolidation | Knowledge Graph |
| Prefrontal Cortex | Executive control | Judgment + Domain Firewall |
| Basal Ganglia | Action selection | Action Policy (future) |
| Amygdala | Salience/Risk | Sensitivity + Priority |
| Working Memory | Current reasoning | Context Pack |
| Global Workspace | Conscious integration | Memory Observer |
| Long-term Memory | Stable knowledge | Graph + Evidence |
| Procedural Memory | Habits | Procedures / Workflows |

This table connects the philosophical motivation, the academic foundations and the technical architecture. It also gives implementers a quick way to understand why `twin` separates events, graph, firewall, judgment, observer and context packs instead of collapsing everything into one retrieval layer.

### 4.5 Hippocampus, consolidation and temporality

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

### 4.6 Prefrontal cortex, judgment and inhibition

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

### 4.7 Amygdala, salience and risk

The amygdala and limbic circuits are associated with emotional salience, fear, risk, reward and affective relevance. In a future version, `twin` should represent something analogous to **salience**:

- is this urgent?
- is this emotionally sensitive?
- can this cause harm if leaked?
- is this important for future decisions?
- should this become a memory or be discarded?

In the MVP, this function partially shows up as `sensitivity`, `confidence`, `needs_review` and `review_reason`.

### 4.8 Basal ganglia and action selection

The basal ganglia are frequently associated with action selection, habits and decision loops. For the project, this inspires future versions with safe automations:

```text
memory + context + judgment
        ↓
selection of a possible action
        ↓
draft / reminder / suggestion / automation with approval
```

The MVP deliberately does not execute autonomous actions. Before acting, the system needs to learn to remember, filter and judge.

### 4.9 Global Workspace Theory — Bernard Baars, Stanislas Dehaene

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

### 4.10 ACT-R — John R. Anderson

ACT-R is a cognitive architecture that separates declarative and procedural components, with activation, retrieval and production mechanisms. The project draws on that separation:

- declarative memory: facts, events, decisions;
- procedural memory: how the user usually does something;
- production/action: rules and decision criteria;
- activation: memory relevance for the current context.

`twin` does not implement ACT-R, but adopts the idea that memory and procedure are distinct categories.

### 4.11 Predictive Processing and Active Inference — Karl Friston

Predictive processing and active inference models treat the brain as a system that maintains internal models, predicts the world and updates beliefs upon receiving prediction error.

For `twin`, this implies the system should not store only loose sentences like "Edu prefers X". It should track the evolution of mental models:

```text
2023: Edu considered microservices preferable for almost everything.
2026: Edu came to prefer a modular monolith when maintainability and simplicity matter more.
Reason: hands-on experience with operational complexity.
```

This calls for temporality, contradiction, supersedence and belief history.

### 4.12 Self-complexity and social roles

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

### 4.13 Symbolic AI: semantic networks, frames and scripts

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
MCP / API / CLI                    judgment store (DB) + YAML bootstrap/export
```

---


## 8. Architecture Principles

These principles are the constitution of `twin`. Roadmaps can change, backends can change and interfaces can change, but new features should remain compatible with these rules. When an implementation choice is ambiguous, the preferred option is the one that preserves cognition, autonomy, evidence, safety and portability.

### 8.1 Twin is a cognitive infrastructure

`twin` is not a memory database. It is an attempt to externalize part of a person's cognition without externalizing their autonomy.

That first principle changes the meaning of every technical decision in the project. The system is not valuable because it stores many facts; it is valuable if it helps the user continue thinking with less friction, fewer repeated explanations and stronger continuity across tools. The database, graph, embeddings, API and MCP server are implementation details in service of that larger goal.

Autonomy is the boundary. `twin` may remember, organize, retrieve, suggest and explain, but it must not quietly take ownership of the user's values or decisions. The project succeeds when it gives external tools access to a safer cognitive substrate while keeping the user in control of durable memory, judgment and action.

### 8.2 Knowledge is not understanding

A million perfectly indexed facts do not produce good decisions. Knowledge answers what is known; understanding emerges from the interaction between memory, context, temporal state, constraints, relationships, consequences and judgment.

`twin` therefore stores facts, but optimizes for understanding. A useful context pack should not merely say "this fact matched the query". It should help an LLM understand why the fact matters now, whether it is still valid, which project or persona it belongs to, what evidence supports it and how it should affect the next decision.

This is the difference between a retrieval layer and a cognitive layer. Retrieval can return information; understanding requires organizing information so that future reasoning improves.

### 8.3 Memory is compression

The system should never try to store reality itself. The brain does not preserve every signal; it compresses experience into patterns, episodes, concepts, salience and decision-relevant traces. `twin` should do the same.

A memory is worth keeping when it can change future action: a decision, constraint, preference, rejected alternative, relationship, risk, commitment, lesson or contextual fact that will matter later. Raw artifacts can be stored or referenced when useful, but durable memory should be a compressed representation of what the system may need in order to reason better in the future.

This principle changes the ingestion pipeline. The goal is not maximum capture. The goal is selective consolidation: preserve what has future cognitive value, keep evidence links for auditability and avoid turning the user's life into an indiscriminate archive.

### 8.4 Artifact ≠ Percept ≠ Memory ≠ Judgment

The backbone of the project is a pipeline from reality to action:

```text
Reality
    ↓
Artifact
(file, transcript, message, note, issue, commit)
    ↓
Percept
(normalized observation)
    ↓
Memory
(consolidated knowledge with evidence and temporal validity)
    ↓
Judgment
(how future decisions change)
    ↓
Action
(suggestion, draft, reminder, automation or silence)
```

An artifact is a source object. A percept is what the system notices from that artifact. A memory is a durable structured claim extracted from one or more percepts. A judgment is a decision rule, preference, value or trade-off that influences future reasoning. Action is downstream from all of them and must not be confused with memory.

Keeping these categories separate prevents the system from treating raw text as truth or treating temporary interpretation as stable belief. If a feature stores everything it sees as memory, it is probably wrong. If it jumps directly from a percept to action without evidence, firewall and judgment, it is unsafe.

### 8.5 The graph is truth; embeddings are indexes

Embeddings answer similarity. They do not answer truth. They cannot explain why a memory exists, when it was true, which source supports it, whether it supersedes another memory or whether it is allowed in the current domain. They are indexes, not memory.

The canonical memory of `twin` is the temporal graph: memory items, entities, relations, evidence, domains, validity windows, confidence and status. Embeddings can make this graph easier to search, but the graph remains the authoritative representation of what the system knows.

This is both a technical and philosophical decision. The user must be able to delete every embedding, regenerate indexes with a different model and still preserve the cognitive substrate. Similarity is useful; truth requires structure, evidence and time.

### 8.6 Evidence before memory

Every durable memory must point back to evidence. Evidence can be a source document, transcript segment, commit, issue, note, calendar event, message or explicit user confirmation. Without evidence, the system may hold a hypothesis, but it should not promote it to confirmed memory.

Evidence is what makes the system inspectable. It lets the user correct bad extraction, distinguish fact from interpretation and understand why a future LLM received a particular context pack. It also gives implementers a defense against silent hallucinated memory.

This principle does not mean all evidence must be exposed to every tool. Evidence has its own sensitivity and domain. But the link must exist inside the local system so the user can audit, export, revise or delete it.

### 8.7 Memory evolves

`twin` is an evolving cognitive model, not a static database. It is expected to change continuously as projects, preferences, constraints, relationships and beliefs change. Static memories are a bug when they pretend old context is still current.

Memories should carry temporal validity through dates, conditions, supersedence or review triggers. A newer memory may replace or narrow an older one without deleting history. The system should preserve what used to be true while making clear what is true now.

This protects the user from stale personalization. A tool that remembers the user well in 2026 but keeps applying 2023 preferences without context is not intelligent; it is outdated with confidence.

### 8.8 Sessions are units of cognition

A session is where context, intention, evidence and interpretation meet. It may be a conversation, work block, meeting, debugging run or planning episode. `twin` should treat sessions as the primary unit for observing cognitive change.

This prevents the system from overreacting to isolated sentences. A single utterance may be exploratory, emotional or provisional. A session gives enough surrounding context to understand whether something was a decision, a rejected option, a preference, a temporary constraint or just brainstorming.

Session-based change also improves auditability. Instead of asking "why does the system believe this?", the user can inspect which session produced the candidate memory or judgment update, what evidence was present and whether the conclusion still holds.

### 8.9 Firewall before reasoning

Privacy and domain separation must happen before reasoning, not after. The main LLM should receive only the memories that are allowed for the current target domain, persona, sensitivity level and task.

This is one of the project's hard safety boundaries. Once sensitive context enters a model prompt, the leak has already happened. Even if the model behaves well, the system has lost the ability to prove that forbidden content was not considered. A firewall is therefore not a formatting layer; it is an access-control layer.

Features that bypass the firewall for convenience are architectural regressions. The right flow is retrieval, classification, filtering, logging and then context packing. The LLM reasons over the safe pack, not over the raw memory universe.

### 8.10 Judgment evolves independently

Memory describes what happened, what was decided, what exists and what evidence supports it. Judgment describes how the user tends to decide, prioritize, reject, approve or communicate. They are related, but they should not be collapsed into the same mechanism.

A new memory can be added without changing judgment. Conversely, judgment can evolve after many sessions reveal a stable pattern. The evolution paths are different, and judgment changes should usually require stronger evidence, aggregation across sessions or explicit human approval.

This independence makes the system safer and more explainable. Memory can be frequent; judgment should be conservative because it changes how future tools act on behalf of the user.

### 8.11 Native integration where possible, MCP everywhere

`twin` should integrate directly into a host application's UI when the host provides supported APIs, hooks or protocols. Native integration offers the best experience because it can surface memory and context within the tool the user is already using.

When native integration is not available, MCP remains the universal and interoperable interface for safely requesting memory, context and judgment. The two modes share the same cognitive core and data; native integration must not create a proprietary memory silo.

This keeps the project aligned with its role as infrastructure. The goal is not to replace ChatGPT, Claude, Cursor or future interfaces, but to improve them through native integration where possible and MCP everywhere else.

### 8.12 Exportability over lock-in

The user must be able to leave. Exportability is not a nice-to-have; it is a moral and architectural requirement for a system that stores personal cognition. Memories, evidence, entities, relations, policies, judgment profiles and index metadata should be representable in formats that can be inspected and migrated.

This protects the user from the project itself. If `twin` succeeds, it may become deeply integrated into the user's thinking and work. That makes lock-in especially dangerous. The more important the system becomes, the easier it must be to audit and exit.

Implementers should prefer boring, documented and portable representations over clever storage tricks that only one runtime understands. Performance optimizations are welcome when they do not compromise export.

### 8.13 Progressive cognition

The system should never jump directly from observation to autonomy. Each cognitive layer must become reliable before the next one exists:

```text
observe
  ↓
remember
  ↓
understand
  ↓
judge
  ↓
suggest
  ↓
act
```

This principle defines the roadmap more clearly than a feature list. A reliable importer, memory schema, firewall, context pack and MCP tool are more valuable than an impressive but unsafe agent loop. The system should first remember accurately, filter safely and explain itself clearly.

Progressive cognition does not reduce the vision; it makes the vision survivable. Each version should create practical value while preserving the path toward deeper cognition and safer action.

### 8.14 Local-first by default

The default assumption is that personal memory, judgment, evidence and indexes live locally under user control. Cloud services may be useful for specific extraction, backup or collaboration flows, but they should not become mandatory for the core system to function.

Local-first is not nostalgia; it is a safety and agency requirement. The data in `twin` can contain private life context, third-party information, work constraints, health hints, relationship details and decision patterns. The user must be able to inspect it, back it up, delete it, move it and run the core system without asking a vendor for permission.

This principle also improves longevity. A personal cognitive OS should outlive model providers, SaaS pricing changes and product shutdowns. Local data plus open export paths are what make that possible.

### 8.15 Human approval for durable judgment

Judgment changes affect future behavior. They can change what the system recommends, blocks, prioritizes, summarizes or exposes. For that reason, durable changes to judgment should require explicit human approval or a conservative review workflow.

The system may propose judgment updates. It may notice repeated patterns, contradictions or stable preferences. But proposing is different from deciding. A user saying "this project is messy" during a frustrating session should not automatically become a durable belief that the user hates complexity everywhere.

This principle preserves agency. `twin` can learn with the user, but it should not silently rewrite the user's values, boundaries or decision model.

### 8.16 Memory exists to improve future action

Memory is not archival for its own sake. `twin` remembers because future thinking, decisions and actions can become better when the right context is available at the right moment.

Action does not need to mean autonomous execution. It can mean a better answer, a safer refusal, a more relevant suggestion, a draft, a reminder, a question for clarification or silence. The point is that memory should eventually reduce cognitive latency: the time between a thought and the information required to continue that thought.

Reducing cognitive latency is one of `twin`'s primary goals. The system should make relevant context feel close to thought without sacrificing evidence, privacy or user control.


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
| `memory_judgment_profile` | active judgment items (DB) + YAML bootstrap |
| `judgment_applicable` | scoped applicable pack for the current context |
| `judgment_simulate` / `judgment_proposals` / `judgment_conflicts` / `judgment_version` | judgment application and governance |
| `judgment_proposal_preview` / `judgment_proposal_approve` / `judgment_proposal_reject` | human-gated proposal lifecycle |
| `memory_observe` | memory observer for the current text/task |
| `memory_quality` | quality analysis + review priority |
| `memory_neighbors` | neighborhood for side-by-side review |
| `memory_provenance` | memory → evidence → percept → artifact |
| `review_queue` | priority-ordered review queue |
| `review_suggest_action` | suggest curation without mutating |
| `memory_confirm` / `memory_reject` / `memory_archive` / `memory_merge` / `memory_split` | gated mutations (`confirm=true`) |
| `session_start` / `session_observe` / `session_complete` / `session_feedback` | cognitive session lifecycle |

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
candidate → confirmed | rejected | merged | split | archived
confirmed → deprecated | contradicted | superseded | stale | unsupported | archived
```

Review answers richer questions than binary approve/reject: is it new, a
paraphrase, more specific, more current, contradictory, mergeable, splittable?
Suggested actions include confirm, reject, edit, merge, split, supersede,
contradict, defer, archive and request_more_evidence.

---

## 14. Evolving judgment model

Memories say **what happened**.

Judgment says **how the user thinks** — preferences, beliefs, principles, values, heuristics and hard constraints.

YAML under `~/.twin/judgment.yaml` remains bootstrap and export. The operational source of truth is the judgment store (SQLite/PostgreSQL): immutable revisions, versioned composition, proposals and snapshots.

Bootstrap example (still valid as seed):

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

Durable changes require human approval. Twin may observe and propose; only the user constitutes. Constitutional items need an extra confirmation flag. Heuristic conflict detection never deactivates active judgment on its own.

Context packs receive an **applicable** judgment section (scoped by domain, persona, project, audience, client, stage and conditions), not the full profile. Sessions that consumed judgment mark extracted memories as `judgment_influenced` so Twin cannot quietly self-confirm its own recommendations.

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
twin review --analyze        # quality findings + priority scores
twin review --priority high  # keyboard/terminal review
twin review --conflicts
twin serve                   # Review Workbench at http://127.0.0.1:8765

# 4. Query
twin search "which stack do we use in the webhooks service"
twin pack "write the Atlas architecture RFC" --domain technical
twin observe "I'm reviewing the webhooks retry"

# 5. Curation and lifecycle
twin promote mem_xxx           # opens a judgment proposal (does not auto-write)
twin judgment import           # bootstrap YAML → versioned store
twin judgment proposals
twin judgment preview jprop_xxx
twin judgment approve jprop_xxx --token <preview_token>
twin judgment simulate "PostgreSQL vs Neo4j?" --domain technical
twin judgment conflicts --refresh
twin supersede mem_new mem_old
twin contradict mem_a mem_b
twin memory merge mem_a mem_b
twin memory split mem_x "part one" "part two"
twin memory provenance mem_x
twin memory archive mem_x
twin undo op_xxx
twin stats                     # memory quality metrics
twin eval extraction
twin eval retrieval
twin retention --dry-run
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
/api/memories/{id}/neighbors
/api/memories/{id}/quality
/api/memories/{id}/provenance
/api/memories/{id}/split
/api/memories/{id}/archive
/api/memories/merge
/api/review/queue
/api/review/batches
/api/artifacts/{id}
/api/evals/extraction
/api/evals/retrieval
/api/search
/api/context_pack
/api/observer
/api/judgment
/api/judgment/items
/api/judgment/versions
/api/judgment/proposals
/api/judgment/proposals/generate
/api/judgment/proposals/{id}/preview
/api/judgment/proposals/{id}/approve
/api/judgment/proposals/{id}/reject
/api/judgment/import
/api/judgment/applicable
/api/judgment/simulate
/api/judgment/conflicts
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

Close the loop between retrieving context and capturing what changed during real technical work.

Delivered:

- cognitive sessions with start, observe, complete and feedback over MCP, API and CLI;
- task-aware context packs (coding, architecture, debugging, writing, planning, review, meeting prep);
- first-class projects with repos, aliases, goals and session/percept linkage;
- product usefulness feedback and session/product metrics;
- multi-stage retrieval with graph expansion, firewall and source-trust weighting;
- fast and deep observer modes with domain/project/task uncertainty;
- `twin doctor` and `twin setup` for ollama, postgres and MCP clients;
- incremental developer sensors (Git, watch) preserving artifact ≠ percept ≠ memory.

### v0.3 — Memory Quality, Consolidation and Review at Scale

Keep memory quality, coherence and auditability as ingestion scales beyond manual curation.

Delivered:

- quality analyzer with neighborhood discovery, claim-aware findings and recomputable review priority (with conflict/privacy floors);
- Review Workbench with priority queue, side-by-side diffs, keyboard shortcuts and batch preview/apply;
- transactional merge and split with compatibility gates, evidence mapping on split, provenance and full undo;
- artifact provenance chain via explicit artifact↔percept links (no content-hash cascade);
- source×type calibration and soft confidence adjustment at extraction;
- safe duplicate-group automation (single canonical survivor) and policy-gated task archival;
- retention and deletion propagation with tombstones and dry-run;
- isolated extraction/retrieval eval harness (firewall/consolidation evals scaffolded, not delivered);
- API, CLI and MCP surfaces for review, consolidation, provenance and evals;
- retrieval that excludes merged, split, archived, unsupported and stale memories by default.

### v0.4 — Evolving Judgment Model

Make different LLMs apply a stable yet evolving model of how the user evaluates trade-offs — without confusing observed behavior with personal principle, and without silent identity changes.

Delivered:

- first-class `JudgmentItem` taxonomy (preference, belief, principle, value, heuristic, constraint) with confidence, strength, stability and typed scope;
- canonical judgment store (SQLite/PostgreSQL) with YAML as bootstrap/export only;
- immutable `JudgmentRevision`s; versions and snapshots point at revision IDs (restore clones history, never rewrites it);
- proposal engine (`propose_from_memory` / demo pattern detector) — observation may propose, only the user constitutes;
- state-aware preview tokens covering final payload, edits and supporting-memory fingerprints;
- all proposal actions (`create`, `update` as patch, `weaken`, `strengthen`, `supersede`, `add_exception`, `deprecate`) with transactional approve/versioning;
- constitutional mutations require `confirm_constitutional`, including when the target is already constitutional;
- application engine with `JudgmentContext` (domain, persona, project, audience, client, stage, conditions) and exception effects (`disable`, `reduce_strength`, `replace_with`, `require_confirmation`);
- explainable `simulate` / counterfactual (`evaluate` without side effects); abstention when judgment signal is insufficient;
- conflict detection that records open conflicts without deactivating active judgment;
- Twin-influenced evidence down-weighted; sessions that consumed judgment auto-mark extracted memories;
- structured applicable judgment section in context packs (not the full profile);
- CLI (`twin judgment …`), HTTP API and MCP tools for proposals, applicable packs, simulate and approve;
- `evals/judgment/` fixtures for scope/precedence scenarios.

### v0.5 — Persona-aware Privacy and Governance

Transform the domain firewall into contextual, verifiable governance independent of the main LLM.

Delivered:

- authorization context (`AccessRequest`: principal, persona, purpose, audience, tool) shared across pack/session surfaces;
- governance policy engine with precedence (constitutional deny → deny → grant/redact → allow → default-deny in restricted mode);
- `PrivacyDecision` audit trail with per-resource effects and policy-set version references;
- field/domain/ownership classification and ephemeral `RedactionPlan` transforms (canonical store untouched);
- temporary `PermissionGrant`s with TTL, max-uses and compare-and-set consumption;
- prompt-injection quarantine before extraction (quarantined content cannot become memory/judgment);
- logical vault labels and employer-ownership policies (no work data to personal cloud);
- deletion preview/execute with lineage accounting; leakage canaries;
- context packs evaluate privacy after retrieval (deny/redact before assembly; evidence skipped for redacted items);
- sessions capture persona/purpose/tool and privacy decision ids;
- CLI (`twin privacy …`) for simulate, explain, grants, quarantine and delete-preview;
- `tests/privacy/test_engine.py` covering deny/redact/grant/quarantine/canary invariants.

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

Phase 1 — Connector Framework (done):

- shared `ProfessionalConnector` contract + adapter manifest/registry (with declared `auth_mode`); no real providers yet;
- `SourceAccount` / `ConnectorInstance` with declared ownership (`personal | employer | client | opensource | shared | unknown`), a mandatory owner principal, per-organization work vaults (`ensure_org_vault`) and preview-first, audited reclassification;
- `CredentialStore` (encrypted file, fail-closed — no crypto backend means no connector) with locked atomic writes and backup recovery; the DB keeps only a `credential_ref`, never the secret; provisioning is compensable and `revoke` is resumable (`revoked_with_residual_secret` is reported, never claimed clean);
- idempotent ingest spine: `RawConnectorItem` → staged `ConnectorRecord` → quarantine gate → `Percept`, keyed by `connector:account:type:id:revision`; the same revision with different content is a `revision_collision` dead letter, never an overwrite, and persisted records are immutable (processing state lives in columns);
- nothing becomes cognitively visible before a consistent commit: records, percepts, the committed batch and the CAS-versioned checkpoint land in one transaction; partial batches persist only raw items + dead letters; per-(connector, stream) leases keep concurrent workers out;
- edits (new revision, old retained); deletions resolve prior lineage into a `ConnectorDeletionEvent` for the deletion planner; auth-expiry and rate-limit handling; sanitized persisted errors; dead-letter retry/replay from raw items;
- `FakeConnector` proving the full path; CLI (`twin connector …`), REST (`/api/connectors`) and MCP tools, all gated by `connector:*` capabilities. Confirmation model: the agent-facing MCP surface is preview/confirm with state-fingerprinted tokens (`connector_sync`), and ownership reclassification is state-fingerprinted on every surface; the authenticated HTTP API is otherwise a direct command surface for administrators — capability-gated, but without preview tokens;
- per-(connector, stream) leases carry a monotonic fencing token, are renewed after every fetched page, and the finalize transaction re-asserts ownership — a worker that outlived its lease cannot publish results;
- `tests/connectors/test_service.py` + `tests/connectors/test_authz.py` contract suites (SQLite and Postgres) + `evals/connectors/` scenarios (normalization, replay, partial batch, revision collision, checkpoint failure, quarantine, source deletion). Connectors capture evidence; cognition still creates understanding — no connector path writes confirmed Memory or Judgment.

Phase 2 — GitHub Connector (done):

- REST v3 adapter (`twin/connectors/github/`) over the Phase 1 framework: `GitHubClient` (Link-header pagination, per-stream page budget, rate-limit → structured `retry_after` the scheduler respects), read-only PAT auth (`awaiting_auth` without a token; write scopes detected via `X-OAuth-Scopes` degrade health with a least-privilege warning);
- dynamic streams per repository — `repo:{owner}/{name}:{issues|pulls|commits|releases}` from the new optional `plan_streams()` protocol method — each with its own checkpoint/lease; incremental cursor is the provider's `updated_at` watermark re-fetched with a lookback window and deduplicated by revision; PRs are detected via the `since`-capable issues listing, then re-fetched from `/pulls` as the authoritative object;
- nine external types normalized to `ConnectorRecord`s (`repository`, `issue`, `issue_comment`, `pull_request`, `review`, `review_comment`, `commit`, `release`, `check_summary`) with `github:{login}` actor ids, a shared `thread_key`/`lineage_root` per issue/PR, and honest affordances (`deletions: false` — not observable via REST polling);
- lifecycle-aware source trust (merged PR 0.95 > approved review 0.90 > commit 0.85 > body/release 0.80 > human comment 0.75 > check 0.70; bots 0.50 — below the review threshold, marked `derived=likely_notification`); every PR lifecycle revision is retained so the merged state wins without erasing rejected alternatives, and the heuristic extractor now captures "decided against / instead of X use Y" as decisions carrying `payload.rejected_alternative`;
- per-source candidate policy at extraction (`twin/cognition/source_policy.py`): GitHub proposes decisions/constraints/procedures/facts/events/tasks, never preferences or beliefs; tasks are born needing review; instances can narrow the policy via `configuration.ingestion_policy`;
- setup and backfill preview surfaces: `twin connector github repositories`, `twin connector backfill --preview` / `POST /api/connectors/{id}/backfill?preview=true` / MCP `connector_backfill_preview` (capability `connector:backfill`) — previews report scope, vault, policy and volume signals and never ingest; Phase 2 backfill itself is the first unwatermarked sync bounded by `configuration.backfill_since` (the partitionable BackfillJob is Phase 4);
- optional webhook receiver `POST /api/webhooks/github/{connector_id}`: HMAC-authenticated (`X-Hub-Signature-256` against a dedicated secret in the CredentialStore, uniform 401 on every failure), it only marks the sync state due with a `targeted_streams` hint the scheduler consumes — the payload never becomes canonical state and polling remains the authoritative reconciliation;
- `tests/connectors/github/test_adapter.py` contract suite against an offline API double (`tests/connectors/github/github_mock.py`), a Postgres mirror test, and `evals/connectors/` scenarios `github_pr_lifecycle` and `github_bot_lineage`.

Phase 3 — Slack Connector (done):

- Web API adapter (`twin/connectors/slack/`) over the Phase 1 framework: `SlackClient` (cursor pagination, per-stream page budget, rate-limit → structured `retry_after`), `auth_mode=slack_bot_token` with honest "privilege unverified via auth.test" health detail; read-only operation (no chat:write);
- dynamic streams per allowlisted channel — `channel:{id}` from `plan_streams()` — each with its own checkpoint/lease; incremental cursor is the maximum observed Slack event `ts` across history roots and thread replies (not a pure history cursor) plus lookback; substreams `history` then `threads`; durable continuation when the page budget is exhausted;
- activity on roots older than the lookback window is recovered via durable Events API hints (`pending_threads`, `pending_message_refreshes`, `pending_tombstones`) — the webhook never becomes canonical content; each hint generation has an `id` (`event_id` or synthetic) so a fetch only consumes generations it observed; consumption uses commit-free `consume_connector_sync_hints_cas` inside finalize (CAS conflict aborts the whole batch);
- external types `channel` / `message` / `thread_reply` with workspace-qualified ids (`slack:{team_id}:{user}`, `thread_key=slack:{team_id}:{channel}:{thread_ts}`); edit revisions via `edited.ts`+content hash; reply deletions preserve `external_type=thread_reply` for lineage; file bytes are not fetched — messages may carry `slack_file` artifact refs with `download_status=metadata_only`;
- channel metadata revalidated via `conversations.info` each sync (TTL cache, default 1h); `channel_kind` fails closed — stale metadata with a failed refresh never authorizes as public; `include_private_channels` / `include_direct_messages` enforced at sync time;
- conservative source trust (human root 0.70 / reply 0.65; bots 0.45 marked `derived=likely_notification`, with GitHub-ref extraction); Slack source policy requires review for every allowed candidate type;
- setup helpers: `twin connector slack channels`, backfill preview, optional Events API webhook `POST /api/webhooks/slack/{connector_id}` (HMAC `X-Slack-Signature`, url_verification, `event_id` dedupe);
- `tests/connectors/slack/test_adapter.py` against `tests/connectors/slack/slack_mock.py` and `evals/connectors/` scenario `slack_thread_bot_lineage`.

Phase 4 — Professional Email (done):

- shared cognitive mail layer (`twin/connectors/mail/`): MIME split (authored/quoted/signature), HTML kept only as `body_html_untrusted_stub` (never safe-to-render), source-heuristic classification, conservative trust, and one `ConnectorRecord` normalizer (`actor_ids` = sender only; `participant_ids` = sender+to+cc; `thread_key=mail:{provider}:{account}:{thread_id}`); attachment mode is explicit (`metadata_only` / discovery — bytes not downloaded by default);
- Gmail adapter (`gmail.readonly`): bootstrap captures `bootstrap_history_id` *before* the time-range scan, then History catch-up seals `history_id` (no gap for concurrent arrivals); label removal tombs only when no allowlisted label remains; tombstones resolve `thread_message` vs `message`;
- Outlook/Graph adapter (`Mail.Read`): continuous sync bootstraps via delta enumeration (all `value`s processed, never discarded); `@removed`/`changed` resolves current folder membership before global tombstone; attachment discovery + shared nextLink/deltaLink error decoder;
- partitionable `BackfillJob`: `SyncExecutionContext` bounds; namespaced streams; per-stream partition progress; claim CAS + finalize fence + heartbeat renew (stale workers cannot publish); completes only when every stream is `done`;
- email source policy stricter than Slack; notifications marked `derived=likely_notification`;
- `tests/connectors/gmail/test_adapter.py` + `tests/connectors/outlook/test_adapter.py` + `tests/connectors/mail/test_normalize.py` and eval `gmail_thread_lineage`.

Phase 5 — Calendar and meetings (done):

- shared meeting cognitive layer (`twin/connectors/meeting/`): provider-agnostic `MeetingRecord` / `TranscriptSegment` / `SpeakerIdentity`; speaker mapping with explicit confidence (never auto-merge `Speaker N`); account-scoped speaker ids; `actor_ids` = speakers who spoke at ≥0.70 confidence (silent attendees stay in `participant_ids` only); calendar↔meeting correlation via `calendar_event_id` / `iCalUID` / `conference_url` / `correlation_fingerprint` on metadata + artifact_refs (no WorkEpisode yet);
- long transcripts emit `meeting_manifest` + `meeting_transcript_chunk` records (segment-aligned chunking — never silent truncation); provider summary is a separate derived record with its own content hash revision;
- Calendar adapter (Google Calendar v3, read-only): calendar-qualified event ids (`google_calendar:{calendar_id}:{event_id}`); allowlist (empty → `awaiting_configuration`); `updated` watermark + lookback; cancelled → tombstone; `freebusy_only` redacts the persisted raw payload (not only record content); paginated calendarList discovery; `max_pages_per_stream` honored;
- Fireflies adapter talks real GraphQL (`POST https://api.fireflies.ai/graphql`); stream `meetings`; `creation_watermark` is meeting-creation only (`fromDate`), not update time — incomplete IDs stay in durable `pending_transcripts` and are re-fetched by ID until terminal; recent completes are periodically reconciled for late edits; page `skip` advances with overlap; processing/live/partial marked incomplete; chunk/summary shrinks emit tombstones; recording artifact id is the transcript id (signed media URLs are not persisted); **deletion feed not offered by provider** (`deletions=false` — retain until offboarding/reconcile);
- source policies require review for every allowed candidate type; scheduler intervals `calendar: 15m`, `fireflies: 30m`;
- setup helpers: `twin connector calendar calendars`, `twin connector fireflies meetings`;
- `tests/connectors/calendar/test_adapter.py` + `tests/connectors/fireflies/test_adapter.py` + `tests/connectors/meeting/test_normalize.py` and eval `calendar_meeting_correlation`.

Phase 6 — Shared documents (done):

- shared document cognitive layer (`twin/connectors/documents/`): provider-agnostic `DocumentRecord` / `DocumentRevision` + `DocumentProvider` protocol for future Drive / OneDrive / Notion; long bodies emit `document_manifest` + `document_revision_chunk` (heading/paragraph/line chunking — never silent truncation); oversized files (`max_file_bytes`) emit metadata-only manifests (`content_available=false`, `evidence_role=artifact_metadata`); decode-lossy content is `operational` + `requires_review`; prior revisions remain addressable after edits;
- document identity for the folder adapter is **path-stable, not rename-stable** (rename = delete + create unless a future correlator links them);
- authorship: email → `mail:{email}` actors; plain front-matter names stay account-scoped `author_label` metadata (confidence 0.30) and are never auto-promoted to global person ids;
- local folder adapter (`twin/connectors/folder/`): explicit watch roots (empty → `awaiting_configuration`); duplicate root ids and overlapping roots fail closed (`allow_overlapping_roots=true` to permit); include/exclude globs (defaults: md/markdown/txt/rst — json/yaml recognized as text only when included); **full scan** each sync (content-hash skips unchanged files; `max_pages_per_stream` is not a work budget); checkpoint `known_files` capped by `max_known_files` (default 50k); deletes / chunk shrinks → tombstones; `auth_mode=none`; symlinks rejected by default (`follow_symlinks=true` requires target inside the same root); POSIX permission bits inspected (Windows → `permission_inspection=not_evaluated`);
- source policy requires review for decision/constraint/procedure/fact/task; scheduler interval `folder: 5m`;
- setup helper: `twin connector folder roots`;
- `tests/connectors/folder/test_adapter.py` + `tests/connectors/documents/test_normalize.py` and eval `folder_document_revisions`.

Phase 7 — Cross-source cognition (done):

- cognitive correlation layer (`twin/cognition/correlation/`): `ExternalIdentity` / `IdentityLink`, `ProjectLink`, `WorkEpisode` / `EpisodeLink` — connectors still only capture evidence; correlation proposes structure, never confirmed Memory or Judgment;
- vault partition: every correlation pass clusters per `vault_id`; anchors and `correlation_key` are vault-qualified — no WorkEpisode / IdentityLink / finding may mix vaults without explicit cross-domain action;
- episode identity: idempotent via `correlation_key` + `episode_anchors` (lineage, calendar id, fingerprint, thread) — repeated passes attach sources, do not duplicate episodes;
- reconciliation: EpisodeLinks carry `active|removed` lifecycle; tombstones drop membership and rebuild participants / dates / source_refs / confidence from active links only (`max(active EpisodeLink.confidence)`; empty → `closed` + 0.0) — still not full multi-factor scoring;
- independence: per-`EpisodeLink` `independence_group` + `directness` (episode keeps aggregate count / primary lineage); derived notifications/summaries do not inflate corroboration;
- identity: upsert from actor ids within the same vault; email → candidate links only inside a vault; never merge by display name; cross-vault confirm refused without explicit flag; confirm / unconfirm / reject with `ExternalIdentity.confirmed` cleared when no confirmed edges remain;
- project mapping: exact `Project.repos` / aliases → `ProjectLink` with lifecycle `candidate | confirmed | historical | rejected` (`confirmed` bool kept as mirror); soft hint matches stay candidates; `historical` / `rejected` never attach `episode.project_id` and block auto-recreating a fresh candidate for the same container;
- clustering: merge anchors (lineage, PR/issue refs, calendar ids) form components; fingerprint / thread are contextual (attach or candidate-only, no transitive overmerge of distinct merge components); soft temporal co-occurrence alone does not merge;
- conflict findings: true cross-source only (distinct sources must disagree); idempotent via `finding_key` (reuse / supersede / close); never auto-resolved;
- explainability CLI (read-only): `twin episode explain`, `twin identity why`, `twin project explain` over anchors / links / findings already stored;
- CLI: `twin correlate`, `twin episode list|show|explain`, `twin identity list|links|confirm|unconfirm|reject|why`, `twin project link|links|confirm|reject|historical|explain`;
- `tests/cognition/correlation/test_service.py`, `tests/cognition/correlation/test_lifecycle.py`, and eval `cross_source_work_episode`.

Still deferred to **Correlation depth** (planned vX — not a Phase 10 blocker): episode phases, full multi-factor confidence, identity graphs + Entity resolution, intra-episode causality, incremental correlation, HTTP/MCP explain APIs, scale/replay evals.

Phase 8 — Native proof (done):

- one host-native adapter: Claude Code Hooks (`twin/interfaces/native/claude_code/`) — observes session start, user messages, tool request/completion, file/project context, session end; does **not** assemble Context Packs or create a parallel memory store;
- `HostSessionBinding` (`hsb_…`) links `(host_type, external_session_id, occurrence)` ↔ `CognitiveSession`; after Stop, the same external id opens occurrence N+1 (history preserved); **cwd never identifies a conversation** — missing session id is rejected;
- security freeze: domain / project / persona / purpose / audience / vault captured at bind; refresh cannot widen scope silently;
- observations are idempotent only with a trustworthy id (`event_id` / `delivery_id` / `tool_call_id+phase` / `sequence`); equal text alone never collapses events; only UNIQUE/PRIMARY KEY conflicts map to `duplicated` (never generic IntegrityError / NOT NULL / FK / CHECK);
- concurrent SessionStart: unique binding wins; loser abandons its orphan `CognitiveSession` and returns the winner;
- tool inputs pass redaction; unknown hooks → `unsupported_host_event` (never forged `user_message`); `transcript_path` → `transcript:{hash}` identity;
- fail-open hooks: Twin failures return `ok=false` + `error_id` (no traceback on stdout) and exit 0 with `--fail-open`; stderr/logger hold diagnostics; Context Pack only for SessionStart/pack_request;
- orphan policy: Stop without binding is a no-op; observations without / after an active binding are rejected; duplicate SessionStart reuses the open binding;
- `InterventionRecommendation` is a display-only *possible decision reversal cue* (heuristic; may false-positive) — no host interruption/action in v0.6; `HostCapabilities` declare what Claude Code can accept;
- MCP remains simultaneous: `native_bindings` / `native_session_status` expose the same Sessions/Projects/Memories; native path never confirms Memory;
- CLI: `twin native install|event|bindings`; `tests/interfaces/native/test_service.py` and eval `evals/native`.

Phase 9 — Evals and operations (done):

- connector observability (§58): durable `*_total` counters on `ConnectorSyncState`, applied **exactly once per `batch.id`** via `connector_counter_batches` ledger — claim + bump share one `store.transaction()` (claim never commits alone); `reconcile_connector_counters` recovers crash undercounts and can repair divergence with audit; summary metrics separated from high-cardinality `instances_detail`; `connector_percepts_total` counts Percepts (not Memory candidates); nested under `twin stats` / `GET /api/metrics`;
- health snapshot (§57): `lag_seconds` ≡ `schedule_lag_seconds` (`max(0, now - next_run_at)`, `null` when unscheduled); `checkpoint_age_seconds` and optional `source_lag_seconds` are separate; never-run connectors report `health=unknown`; `pending_items` counts DLQ + backlog queues only (not `targeted_streams` scope);
- setup plan (§77): `twin connector setup <type> --source-owner …` prints ownership→authenticate→scope→preview→confirm (never ingests) and surfaces ownership/vault/org warnings; backfill preview remains the historical import gate;
- scheduler ops: `twin connector due` / `twin connector sync-due`; `twin doctor` resolves credentials (ref must decrypt), classifies due by schedule grace, and reports unhealthy / lagged instances;
- §88 contract matrix: evidence-based cells (`pass|fail|not_supported|not_applicable|not_tested|partial|framework_only`) with test pointers; framework Fake proof is a separate layer and never auto-passes real adapters; `ok` fails closed on required `not_tested`/`fail`/`partial`;
- `tests/connectors/test_ops.py` and eval `ops_health_metrics`; per-adapter behavioural suites remain the real proof.

Phase 10 — Final Review (done):

- attests §93 Critérios de conclusão via evidence-based `completion_matrix()` (`twin/connectors/completion.py`) — criteria cells carry test/eval pointers; `pass` without evidence demoted; `ok` fails closed on `fail` / `not_tested` / `partial`;
- behavioural proofs live with their modules: lifecycle supersede after meeting candidate (`tests/memory/test_lifecycle.py`); authorized work pack (`tests/privacy/test_engine.py`); completion matrix mechanics (`tests/connectors/test_completion.py`);
- CLI: `twin connector completion` (exit 1 when matrix not ok);
- documents §94 out-of-scope and §95 thesis alongside the matrix payload;
- eval `connector_completion`.

v0.6 is complete when `twin connector completion` reports `ok: true` and the connector/correlation/native suites remain green. Correlation depth (episode phases, multi-factor confidence, identity graphs, causality, incremental correlation, HTTP/MCP explain, scale evals) stays deferred to later `vX` — not a Phase 10 blocker.

### Correlation depth (planned vX — after Phase 7)

Goal: deepen the correlation layer from “clustered evidence” into an explainable, incrementally maintained work-episode model — without turning correlation into Memory or Judgment.

**Slot.** Later `v0.x` or v2, naturally before or alongside [v0.8 Parallel Memory](#v08--parallel-memory-and-consolidation), and feeding [v2 Extended Brain](#v2--extended-brain) episodic and autobiographical memory. It is not a blocker for cognitive interpretation or parallel consolidation.

Phase 7 correctly established: connectors capture evidence; correlation proposes revisable structure (`WorkEpisode`, `IdentityLink`, `ProjectLink`, `ReviewFinding`); vault partition; idempotent keys; membership reconciliation; project/identity lifecycle; true cross-source conflicts; thin explain CLI. What remains is the deeper path.

#### Accepted debt (what Phase 7 still is)

- **WorkEpisode = one cluster.** An episode is still a correlated set of `ConnectorRecord`s, not a structured arc (goal → decision → execution → outcome). PR + Slack + meeting + deploy collapse into one node.
- **Confidence ≈ link type (+ rebuild max).** Episode/link confidence still follows anchor kind / max active link; not source diversity × independence × source trust as a composed score.
- **IdentityLink is pairwise.** Email/candidate edges + confirm/unconfirm/reject exist; there is no first-class identity graph that consolidates GitHub ↔ email ↔ Slack ↔ meeting ↔ calendar into one Entity-facing structure.
- **No causality inside an episode.** Membership says “same episode,” not “A caused B / B motivated C / C resolved D.”
- **Correlation is a batch pass.** `run_correlation_pass()` rescans records; there is no incremental path driven only by new/changed/tombstoned records.
- **Explainability is CLI-first.** Anchors/links/findings are inspectable via `episode explain` / `identity why` / `project explain`; no HTTP/MCP graph API yet.
- **Eval / load gaps.** Missing: full rebuild replay, incremental-only passes, multi-vault / multi-org stress, large ConnectorRecord volumes.

#### Path forward

1. **Episode phases** — `WorkEpisode → EpisodePhase → Evidence` (or equivalent) so the system can answer when a decision changed and when a plan became execution, without splitting every phase into a separate episode by default.
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

### v0.7 — Cognitive Interpretation

Goal: ensure that meaning is identified and catalogued by a cognitive interpreter rather than inferred from shallow lexical patterns.

Connectors and sensors already normalize heterogeneous sources into Percepts while preserving provenance, ownership, confidentiality and lineage. This version strengthens the next boundary: cognition must interpret what a Percept means before proposing any change to memory.

Build:

- an LLM-based cognitive interpreter as the production path for semantic identification and cataloguing;
- explicit interpretation outcomes for decisions, tasks, facts, events, preferences, beliefs, constraints, procedures and rejected alternatives;
- correct distinction between statements, questions, hypotheses, proposals, decisions, opinions and third-party claims;
- participant, speaker, entity, temporal and project references grounded in source evidence;
- evidence spans linking every interpreted item back to the Percept;
- unresolved-reference and ambiguity reporting instead of unsupported semantic guesses;
- interpretation metadata identifying model, prompt version, schema version and execution status;
- deferred and retryable interpretation when the configured cognitive interpreter is unavailable;
- clear separation between semantic interpretation and deterministic governance;
- evaluation fixtures for semantic classification, speaker attribution, evidence grounding and proposal-versus-decision distinction.

The interpreter may use source metadata, session context, project context, participants and related evidence to understand a Percept. Deterministic code remains responsible for authorization, quarantine, confidentiality floors, provenance, persistence integrity, idempotency and review policy.

Lexical rules may support routing, operational optimization and conservative detection signals, but they must not independently establish semantic memory types, domains, entities or cognitive confidence.

A Percept that has not been interpreted remains pending or deferred. It must not be treated as successfully understood merely because a cognitive model was temporarily unavailable.

Implemented:

- a cognitive interpreter (`twin/cognition/interpreter/`) as the production path: the local LLM reads a Percept and emits grounded, act-aware `InterpretedItem`s — each with a cognitive act (statement, question, hypothesis, proposal, decision, opinion, third-party claim), a memory type (including rejected alternatives), a speaker/attribution, and a verbatim `evidence_span`; items the model cannot ground in the source are dropped rather than stored;
- deferral as a first-class outcome: in interpreting modes (`auto`/`ollama`) an unavailable or failing model records the Percept as `deferred` (or `error`) and catalogues nothing — lexical rules never fabricate cognitive conclusions in the production path. A `percept_interpretations` record tracks execution status, model, prompt and schema versions and attempt count, so *never interpreted*, *interpreted and empty*, and *deferred* are three distinct, non-conflated states; `extract_pending` selects by interpretation state, so a returning model resumes cleanly and settled Percepts are never re-interpreted (bounded retries via `MAX_INTERPRETATION_ATTEMPTS`);
- cognitive-act governance: a proposal is not a decision, and a question, hypothesis, opinion or third-party claim is born needing review regardless of the classifier's confidence; deterministic gates (quarantine, source policy, confidentiality floor, dedupe, calibration, review) still run exactly as before — the interpreter decides meaning, deterministic code decides use;
- lexical rules are detection-only: `heuristic` mode records `DetectionSignal`s (routing/prioritization hints — a candidate category and the source span) and creates no `MemoryItem` at all; establishing a memory type, domain, entity or cognitive confidence is the interpreter's job alone. The deterministic offline test/CI double is a **stub interpreter**, not the heuristic — it exercises the real interpreter path (grounding, acts, governance) with no model. `TWIN_EXTRACTOR` is honoured at Config construction;
- evidence is validated deterministically: every catalogued item's `evidence_span` must appear verbatim (Unicode/quote/whitespace-normalized, no paraphrase) in the *masked* text the interpreter read — an invented span, even a non-empty one, is dropped, closing the hallucinated-evidence path; validation runs against masked text so PII placeholders line up and removed PII cannot return;
- a service outage is separated from a Percept-specific failure: availability and the HTTP client are resolved once per batch by an `InterpretationRuntime`; a `deferred`/`unavailable` outage never consumes a Percept's retry budget and is never abandoned, while a reachable-but-failing interpreter is an `error` with a failure class (transient/schema/permanent) bounded by `MAX_INTERPRETATION_ATTEMPTS` and `next_attempt_at` backoff before going terminal;
- no silent semantic fallbacks: an out-of-vocabulary memory type is dropped (never coerced to `fact`); an unrecognized domain becomes `unknown` and is routed to review (never silently `technical`); a speaker attribution is grounded against the Percept's known actors — an unknown speaker is flagged `attribution_unresolved` and an unverified owner claim `owner_claim_unverified`, both review-bound;
- quarantine is recorded as a pipeline/governance terminal with `interpretation_attempted = false`, not as an "interpretation"; per-stage counters (emitted / grounded / ungrounded / policy-dropped / deduplicated / inserted / review-bound / invalid) are persisted for observability;
- surfaces: `twin extract` reports deferrals, `twin interpret status` / `deferred` / `signals` inspect the queue and detection hints, and `POST /api/extract` returns `deferred`/`interpretation_status`/`unresolved_references`;
- `tests/cognition/test_interpreter.py` (deferral, outage-never-abandons, poison-input bounded, grounding incl. invented/paraphrase/masked-source, invalid type/domain, attribution), a Postgres mirror test, `evals/interpretation/` contract scenarios via the scripted interpreter (no model/network in CI), and an optional `evals/interpretation_model/` layer that scores the real local model (act classification, type precision, attribution, evidence literality, invented-item rate) — skipped unless `TWIN_EVAL_MODEL=1`. Connectors and sensors still capture evidence; the interpreter now creates the understanding, and no interpretation path writes confirmed Memory or Judgment on its own.

### v0.8 — Parallel Memory and Consolidation

Goal: move from an on-demand observer toward a continuously updated extended-memory process inspired by the Global Workspace model.

Build on the fast/deep observer introduced in v0.2 and the cognitive interpretation established in v0.7 with:

- real-time observation of supported sessions;
- proactive but non-intrusive memory suggestions;
- confidence-aware spontaneous recall;
- parallel interpretation of what changed during conversation;
- daily and weekly consolidation cycles;
- temporal belief and goal updates;
- salience, novelty and contradiction detection;
- silent blocking of forbidden memories;
- clear separation between interpretation, suggestion, memory candidate and durable consolidation.

Natural consumer of [Correlation depth](#correlation-depth-planned-vx--after-phase-7): incremental correlation passes and episode-phase updates should feed consolidation without full rescans.

### v1.0 — Personal Cognitive OS

A trustworthy, daily-usable version of the infrastructure with:

- closed cognitive sessions;
- reliable cognitive interpretation, memory formation and consolidation;
- evidence-grounded identification and cataloguing of relevant perceptions;
- evolving judgment with human control;
- persona-aware privacy and auditability;
- mature MCP interoperability;
- mature professional connectors;
- parallel observation and controlled consolidation;
- export, backup, deletion and recovery;
- measurable reduction in context re-explanation;
- enough operational reliability to act as the user's persistent cognitive substrate.

---

## 24. Future major versions

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
cognitive interpretation > lexical classification
deferred understanding > simulated understanding
structured memory > raw text
explicit judgment > implicit imitation
temporal graph > infinite markdown
vectors as index > vectors as truth
MCP > mandatory own UI
deterministic governance > policy delegated to the LLM
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
