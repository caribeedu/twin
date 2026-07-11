# twin — Personal Cognitive OS

`twin` is a **local-first** layer of personal memory, judgment, privacy and context, queryable by any LLM or tool through **MCP**, a local HTTP API and a CLI.

The project starts from a practical problem:

> How can a person stop re-explaining their life, projects, decisions, constraints, preferences and way of thinking every time they open a new LLM?

The answer is not another chatbot, generic RAG pipeline or autonomous agent. The goal is to build a portable and evolving cognitive substrate that can be consumed by Cursor, Claude Code, Claude Desktop, local models, future agents, voice interfaces and eventually embodied systems.

> Not an AI that remembers the user, but a personal cognitive infrastructure that any AI can safely consult.

---

## 1. Vision

The long-term vision for `twin` is a **personal exocortex**: an external extension of cognition that preserves continuity across tools, sessions, models and contexts.

It must represent and maintain:

- facts and events;
- decisions and rejected alternatives;
- tasks, promises and commitments;
- technical and communication preferences;
- procedures and recurring ways of working;
- beliefs that may change over time;
- judgment principles and decision criteria;
- relationships between people, projects, systems and events;
- temporal validity and explicit supersedence;
- evidence and provenance;
- hard boundaries between life domains;
- privacy, PII and human control.

The desired experience is not merely low latency. The missing property is **operational understanding**: an AI should know what a memory means, whether it is still valid, where it came from, when it may be used and how it should affect a decision.

---

## 2. What the project is not

`twin` is not:

- a chatbot;
- a note-taking app;
- generic RAG;
- a vector database full of documents;
- an autonomous agent;
- a proprietary replacement for existing AI clients;
- an attempt to imitate the user from unstructured conversation history alone.

It is infrastructure:

```text
personal/professional sources
        ↓
sensors and normalized percepts
        ↓
PII filtering and source qualification
        ↓
structured memory extraction
        ↓
temporal memory + graph + evidence + indexes
        ↓
review, lifecycle and judgment
        ↓
privacy firewall and safe context construction
        ↓
MCP / API / CLI / IDEs / LLMs / agents
```

The main interaction surface may remain external. MCP is therefore a central architectural boundary.

---

## 3. Academic and conceptual foundations

The project draws from philosophy of mind, cognitive science, neuroscience, psychology, symbolic AI, knowledge representation and human-computer interaction.

### 3.1 Extended Mind — Andy Clark and David Chalmers

In **“The Extended Mind”** (1998), Andy Clark and David Chalmers argue that external tools can become part of a cognitive system when they are reliably available and tightly integrated into behavior.

`twin` applies this intuition to LLM-mediated work:

```text
user thinks, speaks or writes
        ↓
twin retrieves relevant memory and judgment
        ↓
a primary LLM reasons over that substrate
        ↓
the user continues thinking with the machine
```

The target is not merely storage. It is cognitive coupling.

### 3.2 4E cognition

The 4E tradition describes cognition as:

- **embodied**;
- **embedded**;
- **extended**;
- **enactive**.

A person already thinks through tools, IDEs, documents, meetings, messages, calendars, notes and LLMs. `twin` attempts to turn this distributed environment into a coherent and controlled computational layer.

### 3.3 Memory systems

Cognitive psychology and neuroscience distinguish several memory systems:

| Cognitive role | `twin` abstraction |
|---|---|
| Episodic memory | events, percepts, evidence, timelines |
| Semantic memory | facts, entities, relations and consolidated knowledge |
| Procedural memory | procedures, playbooks and recurring workflows |
| Working memory | the active task, observer and context pack |
| Executive control | firewall, policies, judgment and selection |

The hippocampus inspires episodic linking and consolidation. Associative cortical systems inspire semantic knowledge. Prefrontal control inspires judgment, inhibition and context selection.

### 3.4 Global Workspace Theory — Bernard Baars and Stanislas Dehaene

Global Workspace Theory proposes that many specialized processes operate in parallel while only selected information becomes globally available for attention, language and action.

This directly motivates the **Memory Observer**:

```text
primary AI handles the conversation or task
        ↓
a parallel observer interprets the current context
        ↓
it retrieves possibly relevant memories
        ↓
privacy and relevance gates filter them
        ↓
selected memories are suggested to the primary AI
```

The intended experience resembles spontaneous remembering rather than manually querying a database.

### 3.5 ACT-R — John R. Anderson

ACT-R distinguishes declarative memory, procedural knowledge, activation and production rules. `twin` does not implement ACT-R, but it adopts the idea that facts, procedures, current activation and action-selection rules are different computational objects.

### 3.6 Predictive processing and active inference — Karl Friston

Predictive-processing and active-inference perspectives treat cognition as maintenance and revision of internal models.

For `twin`, this means that a changing opinion should not simply overwrite an old string. The system should preserve a temporal sequence:

```text
old belief
        ↓
new evidence or experience
        ↓
updated belief
        ↓
explicit supersedence and rationale
```

### 3.7 Social roles and self-complexity

A person does not operate as one homogeneous context. Different roles activate different knowledge and constraints:

```text
person
 ├── developer / technical and work
 ├── partner / relationship
 ├── family member / family
 ├── private individual / health and finance
 └── AI user / assistant preferences
```

This is why domain separation is not merely a metadata tag. It is part of identity, privacy and executive control.

### 3.8 Symbolic AI, frames and scripts

`twin` combines LLM extraction with older knowledge-representation ideas:

- typed entities and relations;
- frames for decisions and events;
- scripts for recurring procedures;
- policies for privacy and judgment;
- explicit temporal transitions;
- evidence-backed claims.

Vectors assist retrieval, but they are not canonical memory.

---

## 4. Core principle: memory is not enough

The project requires three layers:

```text
memory → judgment → action
```

### Memory

Memory answers:

- what happened?
- what was decided?
- who participated?
- what evidence supports this?
- when was it true?

### Judgment

Judgment answers:

- how does the user evaluate trade-offs?
- which principles dominate?
- what must never be mixed?
- which communication style is preferred?
- when does privacy outweigh convenience?

### Action

Action answers:

- should the system suggest something?
- should it create a draft?
- should it stay silent?
- should it request confirmation?
- may it execute an automation?

The current project is strongest in memory, review, privacy and initial judgment. Autonomous action remains deliberately out of scope.

---

## 5. Current architecture and implemented state

The current implementation already includes more than the original v0.1 roadmap anticipated.

### Implemented

- local-only extraction through Ollama, with offline heuristic fallback;
- local embeddings through Ollama, with deterministic hash fallback;
- PostgreSQL + pgvector as the primary backend;
- SQLite as a zero-config development and testing backend;
- normalized percepts and sensors;
- source qualification:
  - `source_trust`;
  - `source_scope`;
  - `source_confidentiality`;
- structured memory types;
- mandatory evidence;
- graph relations and temporal validity;
- hybrid lexical, vector and entity search;
- confirmed-only context packs by default;
- context-pack sections for judgment, decisions, constraints, open tasks, preferences, facts/events and evidence;
- Domain Firewall and audit logging;
- explicit supersedence and contradiction;
- promotion of confirmed memories into the judgment profile;
- memory quality metrics;
- expanded PII detection;
- optional encryption of raw percept content and evidence;
- Memory Observer with keyword and graph-based domain signals;
- MCP, HTTP API, CLI and review UI;
- client-specific MCP documentation;
- exportability and embedding reindexing.

### Architectural rule

```text
percepts + memories + graph + evidence = canonical cognitive record
vectors and text indexes = regenerable retrieval indexes
LLMs = replaceable extractors, classifiers and rerankers
MCP = interoperability boundary
```

---

## 6. Local-first privacy model

All extraction runs locally. Ollama is the default extraction path, with an offline heuristic fallback.

The system supports detection or masking of:

- email addresses and phone numbers;
- CPF, CNPJ, RG and CEP;
- street addresses;
- cards, IBAN and PIX keys;
- IP addresses;
- API keys and personal access tokens;
- JWT and bearer tokens;
- passwords and secret assignments;
- private keys.

`TWIN_ENCRYPTION_KEY` enables encryption at rest for raw percept content and evidence. Titles and summaries remain searchable plaintext, a deliberate and documented trade-off.

Privacy rules are applied before context reaches the primary LLM. The architecture does not rely on the LLM to ignore forbidden information after retrieval.

---

## 7. Installation

```bash
pip install -e ".[dev]"
# or granular:
pip install -e ".[api,mcp,postgres,crypto]"

twin init
```

Configuration:

| Variable | Default | Effect |
|---|---|---|
| `TWIN_HOME` | `~/.twin` | configuration directory |
| `TWIN_DB_URL` | `sqlite:///~/.twin/twin.db` | SQLite or PostgreSQL backend |
| `TWIN_OLLAMA_URL` | `http://127.0.0.1:11434` | local Ollama endpoint |
| `TWIN_OLLAMA_MODEL` | `qwen3:8b` | extraction model |
| `TWIN_OLLAMA_EMBED_MODEL` | `nomic-embed-text` | embedding model |
| `TWIN_EXTRACTOR` | `auto` | `auto`, `ollama` or `heuristic` |
| `TWIN_EMBEDDER` | `auto` | `auto`, `ollama` or `hash` |
| `TWIN_ENCRYPTION_KEY` | unset | encrypt raw percepts and evidence |

---

## 8. Basic workflow

```bash
# Ingest sources
twin ingest ./docs ./transcripts ./meetings

# Extract memories
twin extract

# Review candidates
twin review
twin serve

# Query and construct context
twin search "which stack is used in the webhook service"
twin pack "write the Atlas architecture RFC" --domain technical
twin observe "I am reviewing webhook retries"

# Curate lifecycle and judgment
twin promote mem_xxx
twin supersede mem_new mem_old
twin contradict mem_a mem_b

# Inspect quality and rebuild indexes
twin stats
twin reindex
```

---

## 9. MCP

```bash
twin mcp
```

Example client configuration:

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

Current tools include:

| Tool | Purpose |
|---|---|
| `memory_safe_context_pack` | create a compact privacy-filtered context pack |
| `memory_search` | hybrid memory search |
| `memory_get` | memory and evidence by id |
| `memory_related` | graph neighborhood for an entity |
| `memory_project_context` | project-related context |
| `memory_recent_decisions` | recent decisions |
| `memory_user_preferences` | stable preferences |
| `memory_judgment_profile` | principles and decision criteria |
| `memory_observe` | suggest context for the current text or task |

See [`docs/mcp-clients.md`](docs/mcp-clients.md) for client-specific setup.

---

## 10. Roadmap status

The original roadmap divided context-pack improvements, source trust, lifecycle, metrics, judgment promotion and stronger privacy into later versions. Those items are now already implemented or substantially implemented.

The roadmap has therefore been updated around actual product maturity rather than preserving obsolete version boundaries.

### v0.1 — Local Cognitive Memory Foundation — implemented

Proved that `twin` can:

- ingest normalized percepts;
- extract structured memories locally;
- preserve evidence and provenance;
- review and confirm memories;
- search through text, embeddings and graph signals;
- enforce domain and privacy rules;
- expose memory to external tools via MCP;
- represent initial judgment;
- support multiple storage backends.

The implementation also includes several capabilities originally planned for later versions:

- source qualification;
- confirmed-only context packs;
- structured context sections;
- supersedence and contradiction;
- judgment promotion;
- quality metrics;
- expanded PII;
- optional encryption;
- improved Observer domain inference.

---

## 11. v0.2 — Operational Cognitive Workflow

### Goal

Turn `twin` from a capable memory subsystem into a tool that can be used continuously in real technical work.

The central product loop becomes:

```text
start task
        ↓
identify client, project, domain and task profile
        ↓
load a safe task-specific context pack
        ↓
perform work in the primary AI client
        ↓
record outputs and changes
        ↓
extract new candidate memories
        ↓
review and consolidate
        ↓
measure whether the context was useful
```

The v0.1 foundation primarily enables:

```text
twin → LLM
```

v0.2 must close the loop:

```text
twin → LLM → work result → new percepts and candidate memories → twin
```

### 11.1 Cognitive sessions

Introduce a first-class `CognitiveSession`:

```json
{
  "id": "session_...",
  "client": "cursor | claude-code | claude-desktop | cli",
  "project_id": "project_...",
  "domain": "technical",
  "task_profile": "architecture",
  "started_at": "...",
  "ended_at": null,
  "initial_query": "...",
  "context_memory_ids": [],
  "produced_artifacts": [],
  "candidate_memory_ids": [],
  "status": "active | completed | abandoned"
}
```

A session must make it possible to answer:

- which context was supplied to the primary AI?
- which project and task were active?
- what artifacts were produced?
- what changed during the task?
- which memories were created afterward?
- was the supplied context useful or incorrect?

Proposed MCP/API/CLI capabilities:

```text
session_start
session_observe
session_complete
session_feedback
```

`session_start` returns a session id and a safe context pack. `session_complete` accepts a task summary and produced artifacts, converts them into percepts and sends them through the existing extraction/review pipeline.

### 11.2 Task-aware context packs

The current context pack is structured by memory type. v0.2 adds task-specific composition.

Task profiles:

```text
coding
architecture
debugging
writing
planning
review
meeting
```

Examples:

#### Architecture

```text
judgment criteria
prior decisions
rejected alternatives
constraints
open questions
risks
evidence
```

#### Coding

```text
active project context
architecture decisions
implementation constraints
code conventions
known risks
open tasks
evidence
```

#### Writing

```text
audience
communication style
relevant facts
decisions to preserve
forbidden or sensitive details
sources
```

Implementation direction:

```python
build_context_pack(
    query=...,
    target_domain="technical",
    task_profile="architecture",
)
```

Task profiles control section ordering, memory-type weighting and token budgets.

### 11.3 Projects as first-class cognitive units

Projects should no longer be inferred only as graph entities.

Introduce a `Project` model:

```json
{
  "id": "project_twin",
  "name": "twin",
  "status": "active",
  "domain": "technical",
  "repositories": ["caribeedu/twin"],
  "aliases": [],
  "goals": [],
  "constraints": [],
  "open_questions": [],
  "milestones": []
}
```

Projects group:

- repositories;
- percepts;
- memories;
- sessions;
- artifacts;
- goals;
- decisions;
- constraints;
- risks;
- timelines.

Expected interfaces:

```text
twin project show twin
twin project sync twin
twin project pack twin --task architecture
```

### 11.4 Operational feedback and cognitive metrics

Current metrics primarily measure extraction and review mechanics. v0.2 adds product-level feedback.

Feedback categories:

```text
useful
partially_useful
irrelevant
incorrect
missing_context
privacy_overblock
privacy_underblock
```

New metrics:

```text
context_relevance_rate
memory_usage_rate
false_memory_rate
missing_memory_rate
domain_misclassification_rate
context_pack_token_efficiency
session_reexplanation_rate
```

The core product metric is:

> How often did the user need to explain something that `twin` should already have known?

### 11.5 Multi-stage retrieval and local reranking

Evolve retrieval into explicit stages:

```text
project/domain/task detection
        ↓
lexical candidate generation
        ↓
vector candidate generation
        ↓
graph expansion
        ↓
temporal filtering
        ↓
privacy firewall
        ↓
source-trust weighting
        ↓
local reranking
        ↓
task-specific context budgeting
```

A local Ollama reranker may evaluate whether each candidate is relevant, mandatory or distracting. Fixed BM25/vector/entity weights remain a deterministic fallback.

### 11.6 Two-stage Memory Observer

The Observer becomes two-tiered:

#### Fast observer

- keywords;
- mentioned entities;
- current repository or directory;
- project hints;
- graph votes;
- deterministic and inexpensive.

#### Deep observer

- local LLM classification;
- invoked for ambiguous input;
- predicts domain, project, task profile and intent;
- returns confidence and uncertainty.

Desired output:

```json
{
  "domain": "technical",
  "domain_confidence": 0.94,
  "project": "twin",
  "project_confidence": 0.88,
  "task_profile": "architecture",
  "suggested_memories": [],
  "uncertainties": []
}
```

### 11.7 Tested MCP client workflows

v0.2 must validate real workflows rather than only expose generic MCP tools.

Priority clients:

1. Claude Code;
2. Cursor;
3. Claude Desktop;
4. CLI as the reference integration.

Compatibility matrix:

| Client | Start session | Context pack | Observe | Complete session |
|---|---:|---:|---:|---:|
| Claude Code | required | required | supported | required |
| Cursor | required | required | supported | required |
| Claude Desktop | supported | required | supported | manual or supported |
| CLI | required | required | required | required |
| Generic MCP | optional | required | optional | optional |

### 11.8 Installation and diagnostics

Add operational commands:

```text
twin doctor
twin setup ollama
twin setup postgres
twin setup mcp cursor
twin setup mcp claude-code
```

`twin doctor` should verify:

- Ollama connectivity;
- required local models;
- PostgreSQL and pgvector;
- migrations;
- encryption configuration;
- MCP client configuration;
- policy and judgment validity;
- index consistency;
- filesystem permissions.

### 11.9 Incremental technical sensors

v0.2 does not yet require Gmail, WhatsApp or personal-domain connectors. It should introduce incremental technical ingestion:

```text
filesystem watcher
git sensor
meeting-directory watcher
session-result sensor
```

Proposed command:

```bash
twin watch ./docs ./transcripts
```

A Git sensor may capture:

- commits;
- commit messages;
- branch context;
- pull-request descriptions;
- ADR changes;
- documentation changes.

### 11.10 Artifact, percept and memory separation

Make the distinction explicit:

```text
artifact != percept != memory
```

- **Artifact:** a file, commit, PR, transcript or generated output.
- **Percept:** the normalized representation produced by a sensor.
- **Memory:** consolidated knowledge derived from percepts.

Sessions should link all three so the system can trace:

```text
session → artifact → percept → memory → evidence
```

### v0.2 completion criteria

v0.2 is complete when the following works end to end:

1. open a repository in Claude Code or Cursor;
2. start a task without re-explaining the full project;
3. infer project, domain and task profile;
4. supply relevant decisions, constraints and judgment;
5. perform the task in the primary client;
6. complete the cognitive session;
7. convert outputs into percepts;
8. extract new candidate memories;
9. review and consolidate them;
10. record whether the supplied context was useful;
11. reproduce the same cognitive continuity in another MCP client.

---

## 12. v0.3 — Memory Quality, Consolidation and Maintenance

Several originally planned v0.3 capabilities are already implemented:

- source trust;
- approval metrics;
- duplicate metrics;
- explicit supersedence;
- explicit contradiction.

The remaining v0.3 scope should focus on scalable curation:

- batch review;
- side-by-side comparison of similar memories;
- memory merge and evidence consolidation;
- automatic contradiction and update proposals;
- temporal consistency checks;
- stale-memory detection;
- source disagreement analysis;
- sampled human review instead of exhaustive review;
- evaluation datasets and regression benchmarks;
- deletion propagation from artifact/percept to evidence and memory.

Expected outcome:

> Memory quality remains acceptable as the volume of percepts and sessions grows.

---

## 13. v0.4 — Evolving Judgment Model

Basic judgment profiles and manual promotion are already implemented.

v0.4 evolves judgment from a static YAML profile into a versioned, evidence-backed model.

Scope:

- distinguish preference, belief, principle, value and decision criterion;
- propose judgment updates from repeated confirmed memories;
- require explicit approval for judgment changes;
- preserve judgment history and rationale;
- support context-specific judgment;
- identify conflicts between principles;
- model trade-off ordering;
- compare behavior across different LLM clients;
- evaluate whether different models reach consistent recommendations.

Expected outcome:

> Different LLMs may reason differently, but they receive a stable representation of how the user evaluates decisions.

---

## 14. v0.5 — Persona-aware Domain Firewall

The current firewall, PII controls, candidate filtering, source confidentiality and audit logs provide a strong foundation.

v0.5 focuses on fine-grained personal-domain readiness:

- persona-aware rules;
- purpose-based access control;
- source-owner and audience constraints;
- explicit temporary permissions;
- contextual redaction rather than only allow/block;
- physical or cryptographic separation between work and personal vaults;
- policy simulation and leak testing;
- prompt-injection quarantine for ingested content;
- deletion and retention policies;
- stricter rules for health, relationship, family, legal and finance domains.

Expected outcome:

> The project can begin handling personal domains without treating PII masking as sufficient protection.

---

## 15. v0.6 — Professional Connectors

Add governed connectors and adapters for:

- Slack;
- professional Gmail;
- Outlook;
- Google Calendar;
- GitHub;
- Fireflies;
- Meetily;
- technical document stores.

Each connector must provide:

- incremental sync;
- authorization scope;
- source trust and confidentiality defaults;
- provenance;
- retention and deletion behavior;
- domain assignment;
- failure recovery;
- rate-limit handling.

Professional and employer-owned data must remain physically and logically separated when required by policy.

---

## 16. v0.7 — Personal Domains

Expand carefully into:

- finance;
- home and property;
- personal goals;
- relationships;
- family;
- health;
- personal communication;
- personal email and calendars.

Requirements:

- stricter default-deny;
- mandatory review for high-impact memories;
- stronger entity-sensitive PII;
- consent and third-party-data rules;
- separate encryption domains;
- retention and forgetting;
- persona-aware retrieval;
- leakage benchmarks.

---

## 17. v0.8 — Parallel Cognitive Workspace

The current Observer is a request/response memory suggestion tool. v0.8 turns it into a continuous parallel cognitive process.

Scope:

- real-time observation of active conversations and tasks;
- asynchronous memory suggestion;
- salience and urgency scoring;
- attention budgets;
- interruption policies;
- silent blocking of forbidden memories;
- detection of missing context;
- tracking of unresolved questions and goals;
- continuous working-memory state.

Expected outcome:

> `twin` begins to behave less like a database and more like an extended remembering system.

---

## 18. v0.9 — Voice and Low-friction Interaction

Scope:

- local voice notes;
- low-latency transcription;
- daily reflection;
- meeting capture;
- spoken session start and completion;
- ambient input only with explicit controls;
- no forced replacement of existing LLM clients.

Projects such as Meetily may serve as sensory adapters rather than as the memory kernel.

---

## 19. v1.0 — Personal Cognitive OS

v1.0 represents a trustworthy daily-use system with:

- mature memory lifecycle;
- versioned judgment;
- persona-aware privacy;
- session continuity;
- task-aware context packs;
- project models;
- continuous technical and personal sensors;
- parallel observation;
- export, backup, deletion and recovery;
- client interoperability;
- measurable reduction in re-explanation;
- real daily usage across multiple LLM clients.

---

## 20. Future major versions

### v2 — Extended Brain

- robust episodic consolidation;
- semantic and procedural memory maintenance;
- goals and planning;
- daily and weekly reflection;
- active personas;
- salience and attention;
- long-term mental-model evolution.

### v3 — Cognitive Automation

- reminders;
- follow-ups;
- drafts;
- commitment detection;
- action proposals;
- execution only through governed approval.

### v4 — Multimodal Life Layer

- voice;
- screen;
- images;
- documents;
- meetings;
- spatial and environmental context;
- optional wearable data.

### v5 — Embodied and Robot-ready Cognition

- memory portability to physical agents;
- spatial memory;
- household routines;
- robotics and home automation;
- embodiment-specific safety policies;
- continuity across software and physical interfaces.

---

## 21. Related projects and references

Relevant implementations and inspirations include:

- **Graphiti / Zep** — temporal graph memory and agent context;
- **Mem0** — extraction, consolidation and multi-session memory;
- **Letta / MemGPT** — stateful agents and hierarchical memory;
- **Meetily** — privacy-first local meeting capture;
- **Fireflies** — meeting transcripts as episodic input;
- **Screenpipe** — local multimodal capture inspiration;
- **MCP clients and servers** — interoperability with existing tools.

These projects may provide sensors, algorithms or implementation references. None should become the canonical owner of the user's memory or judgment.

---

## 22. Product success metrics

Pipeline metrics:

- approval rate;
- duplicate rate;
- average confidence;
- review backlog;
- firewall block count;
- extraction and retrieval latency.

Cognitive product metrics:

- context relevance;
- missing-memory rate;
- false-memory rate;
- re-explanation rate;
- context token efficiency;
- domain classification accuracy;
- cross-client consistency;
- privacy overblocking and underblocking;
- percentage of sessions that produce useful consolidated memories.

The primary success criterion remains experiential:

> Does the system feel as though it understands where the user is, what has already happened and how the user tends to decide — without leaking the wrong part of their life?

---

## 23. Engineering principles

```text
local-first > cloud-first
structured memory > raw context dumping
evidence-backed claims > unsupported summaries
judgment explicitness > personality imitation
vectors as indexes > vectors as truth
temporal graph > endless markdown
MCP interoperability > mandatory proprietary UI
firewall before the LLM > trusting the LLM to self-censor
selective review > reviewing everything
open canonical formats > vendor lock-in
incremental product proof > premature artificial-general-cognition architecture
```

---

## 24. Final definition

`twin` is a local-first, temporal and interoperable layer of personal memory, judgment, privacy and context.

Its immediate purpose is to reduce repeated explanation in real technical work.

Its long-term purpose is more ambitious:

> To make machine intelligence feel cognitively integrated with the user by preserving memory, judgment, boundaries and continuity outside the biological brain — without surrendering ownership or control.
