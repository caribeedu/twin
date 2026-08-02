# Architecture

This document explains how Twin works — brain analogies, architecture
principles, stack, data model, pipeline, privacy, review, judgment,
observer and threat model.

Durable principles: [IDENTITY.md](IDENTITY.md#design-principles).
Cognitive concepts: [COGNITION.md](COGNITION.md) ·
[GLOSSARY.md](GLOSSARY.md). Academic inspirations (appendix):
[FOUNDATIONS.md](FOUNDATIONS.md). Product: [PRODUCT.md](PRODUCT.md).
Interfaces: [INTERFACES.md](INTERFACES.md). Direction loop:
[README — Direction](../README.md#direction).

## Brain analogies

Twin does **not** simulate a biological brain. Neuroscience and cognitive science supply *engineering analogies*: they explain why the system separates episodic capture, semantic structure, executive control, salience and working context instead of collapsing everything into one retrieval index. Deeper academic sources live in [FOUNDATIONS.md](FOUNDATIONS.md).

### Cognitive systems mapped to Twin layers

| Cognitive system | Function | Abstraction in Twin |
|---|---|---|
| Episodic memory | events, meetings, conversations, temporal context | `event`, sources, evidence, timeline |
| Semantic memory | facts, concepts, consolidated relationships | `fact`, entities, relations, graph |
| Procedural memory | ways of doing, habits, workflows | `procedure`, playbooks, scripts |
| Working memory | current task focus | query, Memory Observer, context pack |
| Executive control | selection, inhibition, judgment | Domain Firewall, policies, evolving judgment |

### Brain regions mapped to Twin components

| Brain concept | Purpose | Twin abstraction |
|---|---|---|
| Hippocampus | Episodic encoding & consolidation | Percepts + Events + temporal validity |
| Cortex | Semantic consolidation | Knowledge graph |
| Prefrontal cortex | Executive control | Judgment + Domain Firewall |
| Basal ganglia | Action selection | Action policy (future) |
| Amygdala | Salience / risk | Sensitivity + review priority |
| Working memory | Current reasoning | Context pack |
| Global workspace | Conscious integration | Memory Observer |
| Long-term memory | Stable knowledge | Graph + evidence |
| Procedural memory | Habits | Procedures / workflows |

How that shows up in the pipeline:

```text
Artifact / connector feed
        ↓  (hippocampus-like encoding)
Percept → candidate Memory
        ↓  (cortical consolidation)
Graph + evidence + embeddings (indexes only)
        ↓  (prefrontal / amygdala-like gates)
Firewall + sensitivity + judgment
        ↓  (working memory)
Safe context pack → MCP / CLI / API
        ↕  (global workspace)
Memory Observer (parallel suggestions)
```

If a feature blurs these boundaries — e.g. treating raw text as confirmed memory, or bypassing the firewall “for convenience” — it fights the architecture, not just a style preference.

### Brain analogies → CLI stages

Episode cognition (v1.3.0) makes the analogy literal: turning connector records into trajectory understanding is a chain of stages, each named for the region it plays. The `sensory` scaffold is structural (explicit anchors, exact identity/project); every semantic stage is an LLM (or a deterministic test override), and a missing model **defers** the stage rather than falling back to lexical rules. `twin correlate` runs up to `cortex`; `twin meditate` orchestrates the whole chain up to the human gates (`twin review`, `twin judgment approve`).

| # | Stage id (`brain_stage`) | Brain region | Job | Writes | CLI |
|---|---|---|---|---|---|
| 0 | `sensory` | encoding substrate | vault / dirty / ID anchors | partitions, membership | `twin correlate --until sensory` |
| 1 | `amygdala` | Amygdala (salience) | classify member role + salience | phase roles (`proposed`) | `twin correlate` |
| 2 | `basal` | Basal ganglia | read episode lifecycle | lifecycle (report-only) | `twin correlate` |
| 3 | `hippocampus_bind` | Hippocampus (binding) | membership consolidation | links | `twin correlate` |
| 4 | `cortex` | Cortex (semantic) | understand arc: phases + edges | phases/edges (`method=llm`) | `twin correlate` |
| 5 | `hippocampus_consolidate` | Hippocampus (consolidation) | reflect trajectory | MemoryCandidates | `twin episode reflect` / `twin meditate` |
| 6 | `prefrontal` | Prefrontal cortex | draft judgment | pending `JudgmentProposal` | `twin judgment propose-episode` / `twin meditate` |

Human inhibition gates sit between consolidation and executive control: `twin review` (confirm candidates) precedes `prefrontal`, and `twin judgment approve` is the executive gate for durable judgment. The Global Workspace (Memory Observer) runs in parallel and is **not** a stage in this chain.

## Architecture Principles

These principles are the constitution of `twin`. Roadmaps can change, backends can change and interfaces can change, but new features should remain compatible with these rules. When an implementation choice is ambiguous, the preferred option is the one that preserves cognition, autonomy, evidence, safety and portability.

### Twin is a cognitive infrastructure

`twin` is not a memory database. It is an attempt to externalize part of a person's cognition without externalizing their autonomy.

That first principle changes the meaning of every technical decision in the project. The system is not valuable because it stores many facts; it is valuable if it helps the user continue thinking with less friction, fewer repeated explanations and stronger continuity across tools. The database, graph, embeddings, API and MCP server are implementation details in service of that larger goal.

Autonomy is the boundary. `twin` may remember, organize, retrieve, suggest and explain, but it must not quietly take ownership of the user's values or decisions. The project succeeds when it gives external tools access to a safer cognitive substrate while keeping the user in control of durable memory, judgment and action.

### Knowledge is not understanding

A million perfectly indexed facts do not produce good decisions. Knowledge answers what is known; understanding emerges from the interaction between memory, context, temporal state, constraints, relationships, consequences and judgment.

`twin` therefore stores facts, but optimizes for understanding. A useful context pack should not merely say "this fact matched the query". It should help an LLM understand why the fact matters now, whether it is still valid, which project or persona it belongs to, what evidence supports it and how it should affect the next decision.

This is the difference between a retrieval layer and a cognitive layer. Retrieval can return information; understanding requires organizing information so that future reasoning improves.

### Memory is compression

The system should never try to store reality itself. The brain does not preserve every signal; it compresses experience into patterns, episodes, concepts, salience and decision-relevant traces. `twin` should do the same.

A memory is worth keeping when it can change future action: a decision, constraint, preference, rejected alternative, relationship, risk, commitment, lesson or contextual fact that will matter later. Raw artifacts can be stored or referenced when useful, but durable memory should be a compressed representation of what the system may need in order to reason better in the future.

This principle changes the ingestion pipeline. The goal is not maximum capture. The goal is selective consolidation: preserve what has future cognitive value, keep evidence links for auditability and avoid turning the user's life into an indiscriminate archive.

### Artifact ≠ Percept ≠ Memory ≠ Judgment

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

### The graph is truth; embeddings are indexes

Embeddings answer similarity. They do not answer truth. They cannot explain why a memory exists, when it was true, which source supports it, whether it supersedes another memory or whether it is allowed in the current domain. They are indexes, not memory.

The canonical memory of `twin` is the temporal graph: memory items, entities, relations, evidence, domains, validity windows, confidence and status. Embeddings can make this graph easier to search, but the graph remains the authoritative representation of what the system knows.

This is both a technical and philosophical decision. The user must be able to delete every embedding, regenerate indexes with a different model and still preserve the cognitive substrate. Similarity is useful; truth requires structure, evidence and time.

### Evidence before memory

Every durable memory must point back to evidence. Evidence can be a source document, transcript segment, commit, issue, note, calendar event, message or explicit user confirmation. Without evidence, the system may hold a hypothesis, but it should not promote it to confirmed memory.

Evidence is what makes the system inspectable. It lets the user correct bad extraction, distinguish fact from interpretation and understand why a future LLM received a particular context pack. It also gives implementers a defense against silent hallucinated memory.

This principle does not mean all evidence must be exposed to every tool. Evidence has its own sensitivity and domain. But the link must exist inside the local system so the user can audit, export, revise or delete it.

### Memory evolves

`twin` is an evolving cognitive model, not a static database. It is expected to change continuously as projects, preferences, constraints, relationships and beliefs change. Static memories are a bug when they pretend old context is still current.

Memories should carry temporal validity through dates, conditions, supersedence or review triggers. A newer memory may replace or narrow an older one without deleting history. The system should preserve what used to be true while making clear what is true now.

This protects the user from stale personalization. A tool that remembers the user well in 2026 but keeps applying 2023 preferences without context is not intelligent; it is outdated with confidence.

### Sessions are units of cognition

A session is where context, intention, evidence and interpretation meet. It may be a conversation, work block, meeting, debugging run or planning episode. `twin` should treat sessions as the primary unit for observing cognitive change.

This prevents the system from overreacting to isolated sentences. A single utterance may be exploratory, emotional or provisional. A session gives enough surrounding context to understand whether something was a decision, a rejected option, a preference, a temporary constraint or just brainstorming.

Session-based change also improves auditability. Instead of asking "why does the system believe this?", the user can inspect which session produced the candidate memory or judgment update, what evidence was present and whether the conclusion still holds.

### Firewall before reasoning

Privacy and domain separation must happen before reasoning, not after. The main LLM should receive only the memories that are allowed for the current target domain, persona, sensitivity level and task.

This is one of the project's hard safety boundaries. Once sensitive context enters a model prompt, the leak has already happened. Even if the model behaves well, the system has lost the ability to prove that forbidden content was not considered. A firewall is therefore not a formatting layer; it is an access-control layer.

Features that bypass the firewall for convenience are architectural regressions. The right flow is retrieval, classification, filtering, logging and then context packing. The LLM reasons over the safe pack, not over the raw memory universe.

### Judgment evolves independently

Memory describes what happened, what was decided, what exists and what evidence supports it. Judgment describes how the user tends to decide, prioritize, reject, approve or communicate. They are related, but they should not be collapsed into the same mechanism.

A new memory can be added without changing judgment. Conversely, judgment can evolve after many sessions reveal a stable pattern. The evolution paths are different, and judgment changes should usually require stronger evidence, aggregation across sessions or explicit human approval.

This independence makes the system safer and more explainable. Memory can be frequent; judgment should be conservative because it changes how future tools act on behalf of the user.

### Native integration where possible, MCP everywhere

`twin` should integrate directly into a host application's UI when the host provides supported APIs, hooks or protocols. Native integration offers the best experience because it can surface memory and context within the tool the user is already using.

When native integration is not available, MCP remains the universal and interoperable interface for safely requesting memory, context and judgment. The two modes share the same cognitive core and data; native integration must not create a proprietary memory silo.

This keeps the project aligned with its role as infrastructure. The goal is not to replace ChatGPT, Claude, Cursor or future interfaces, but to improve them through native integration where possible and MCP everywhere else.

### Exportability over lock-in

The user must be able to leave. Exportability is not a nice-to-have; it is a moral and architectural requirement for a system that stores personal cognition. Memories, evidence, entities, relations, policies, judgment profiles and index metadata should be representable in formats that can be inspected and migrated.

This protects the user from the project itself. If `twin` succeeds, it may become deeply integrated into the user's thinking and work. That makes lock-in especially dangerous. The more important the system becomes, the easier it must be to audit and exit.

Implementers should prefer boring, documented and portable representations over clever storage tricks that only one runtime understands. Performance optimizations are welcome when they do not compromise export.

### Progressive cognition

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

### Local-first by default

The default assumption is that personal memory, judgment, evidence and indexes live locally under user control. Cloud services may be useful for specific extraction, backup or collaboration flows, but they should not become mandatory for the core system to function.

Local-first is not nostalgia; it is a safety and agency requirement. The data in `twin` can contain private life context, third-party information, work constraints, health hints, relationship details and decision patterns. The user must be able to inspect it, back it up, delete it, move it and run the core system without asking a vendor for permission.

This principle also improves longevity. A personal cognitive OS should outlive model providers, SaaS pricing changes and product shutdowns. Local data plus open export paths are what make that possible.

### Human approval for durable judgment

Judgment changes affect future behavior. They can change what the system recommends, blocks, prioritizes, summarizes or exposes. For that reason, durable changes to judgment should require explicit human approval or a conservative review workflow.

The system may propose judgment updates. It may notice repeated patterns, contradictions or stable preferences. But proposing is different from deciding. A user saying "this project is messy" during a frustrating session should not automatically become a durable belief that the user hates complexity everywhere.

This principle preserves agency. `twin` can learn with the user, but it should not silently rewrite the user's values, boundaries or decision model.

### Memory exists to improve future action

Memory is not archival for its own sake. `twin` remembers because future thinking, decisions and actions can become better when the right context is available at the right moment.

Action does not need to mean autonomous execution. It can mean a better answer, a safer refusal, a more relevant suggestion, a draft, a reminder, a question for clarification or silence. The point is that memory should eventually reduce cognitive latency: the time between a thought and the information required to continue that thought.

Reducing cognitive latency is one of `twin`'s primary goals. The system should make relevant context feel close to thought without sacrificing evidence, privacy or user control.

## Practical philosophy

Preferences that should win when choices conflict:

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

Continue in [PRODUCT.md](PRODUCT.md) for domain rules · [ROADMAP.md](ROADMAP.md) and [CHANGELOG.md](CHANGELOG.md) for versions · [INTERFACES.md](INTERFACES.md) ([Native](NATIVE.md) / [MCP](MCP.md) / [CLI](CLI.md) / [REST](REST.md)) · [FOUNDATIONS.md](FOUNDATIONS.md) for academic roots.

## Stack and technical decisions

### Local-first

Everything lives in `~/.twin` or `$TWIN_HOME`:

- SQLite;
- policies YAML;
- judgment YAML;
- exportable data;
- simple backups.

Backup = copy the folder.

Full export = `twin export`.

### SQLite as a light graph

The initial concepts uses SQLite with tables for:

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

### Vectors as index, not as memory

Embeddings are useful for semantic search, but they are not the true memory.

Project rule:

```text
graph + events + evidence = canonical memory
vectors = regenerable index
LLM = extractor/interpreter
MCP = interface
```

This avoids lock-in and allows reindexing in the future.

### Hybrid search

Search combines:

- FTS5/BM25;
- embeddings;
- entity boost;
- firewall filtering.

Search must answer not only "what looks semantically similar?", but "what is relevant, allowed and trustworthy for this context?".

### Native where possible, MCP everywhere

The project must not depend on its own UI. Prefer **native** when a client can bind session lifecycle to Twin. **MCP** remains the universal tool surface for every MCP host — and complements native mid-task. CLI and local API expose the same cognitive core. Full reference in [INTERFACES.md](INTERFACES.md#clients) · [NATIVE.md](NATIVE.md) · [MCP.md](MCP.md).

## Data model

### Memory Item

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

### Memory types

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

### Mandatory evidence

Every memory must carry evidence, preferably a verbatim excerpt from the source.

Without evidence, a memory is suspect.

This reduces memory hallucination and enables human review.

### Temporality

Memories must have temporal validity.

Example:

```text
2025: works at Acme Corp
2026: works at Globex
```

Both can be true, but not simultaneously.

Desired future:

- `supersedes`;
- `contradicts`;
- `deprecated_by`;
- automatic `valid_until`;
- belief timeline.

## Ingestion and extraction pipeline

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

initial concept sources:

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

## PII and privacy

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

## Selective review

The user must not review everything manually. Review should happen by exception.

A memory goes to review when:

- confidence < threshold;
- sensitivity is `private` or `restricted`;
- domain is outside the initial concept;
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

## Evolving judgment model

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
  - prefer a simple stack for an initial concept
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

## Memory Observer

The Memory Observer is a parallel AI/module that follows the current text and suggests related memories.

It does not answer for the user. It must not act. It only remembers.

Flow:

```text
current text / task / draft
        ↓
candidate memory search (hybrid, vault-wide)
        ↓
firewall (consumer domain: the open session, or an explicit argument)
        ↓
ranking (semantic + text + entity, plus a soft same-domain boost)
        ↓
compact suggestion for the main AI
```

The consumer domain is never guessed from the text: it is the frozen domain of the open session or an explicit argument. With no such domain the firewall target is `unclassified` and the suggestion comes back empty — ambiguity yields *less* context, never another domain's memories.

Opening a session scope on the request path (`resolve_context_domain`) is a retrieval vote across confirmed memories only — no local LLM in the hot path. When the vote is inconclusive the session stays `unclassified` until a background `session_domain_resolve` job (multi-message evidence) or an explicit client/MCP domain freezes it. Native hosts: Claude's **Stop** is end-of-turn (observe only); **SessionEnd** closes the binding and enqueues background `session_complete` for the `session_summary` Percept (see [NATIVE.md](NATIVE.md); requires `twin-runtime`).

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

## Risks

### Privacy

Maximum risk. The system may contain intimate and professional information. Mitigations:

- local-first;
- PII masking;
- firewall;
- logs;
- review;
- default-deny in sensitive domains;
- export/delete;
- future encryption.

### Memory hallucination

LLMs can extract false memories. Mitigations:

- mandatory evidence;
- confidence;
- candidate status;
- selective review;
- blocking candidates in critical contexts;
- internal citations.

### Domain mixing

The most dangerous operational risk. Mitigations:

- mandatory domain/persona/sensitivity;
- firewall before the LLM;
- block logs;
- explicit target_domain;
- tested policies.

### Overengineering

The risk of trying to build the whole brain before the being able to handle it. Mitigation:

- start with technical work;
- avoid WhatsApp/intimate life at the beginning;
- do not build a chat of its own;
- use MCP;
- measure real usefulness.

### Vendor dependency

Mitigation:

- canonical data in an open format;
- regenerable embeddings;
- replaceable LLM;
- SQLite/JSON export;
- MCP as the interface.

---


## Threat model

Local-first personal cognitive OS. Assets: memories, judgment, connector secrets, session context, backups.

## Trust boundaries

| Boundary | Trust |
|---|---|
| User / local host | Trusted operator |
| Twin process + `$TWIN_HOME` store | Trusted computing base |
| Cognitive model / LLM | Untrusted for authority — may hallucinate; never auto-confirms Memory/Judgment |
| MCP / HTTP / CLI clients | Authenticated principals with least privilege; default deny |
| External connectors (Slack, GitHub, mail, …) | Untrusted content sources; evidence only |
| Backups / exports | Sensitive at rest; treat as equivalent to the live store |

## Top threats and controls

1. **Prompt injection via ingested content**  
   Content is data, never instruction. Screening (`detect_injection`), quarantine, pack-time exclusion. Connectors quarantine malicious records before percepts.

2. **Cross-domain / persona privilege amplification**  
   Domain firewall + persona scope intersection (never amplifies). Cross-domain recall blocked by default.

3. **Connector credential theft / over-privilege**  
   Secrets in encrypted credential store (`credential_ref` only in DB). Least-privilege health warnings. Revoke is resumable and honest about residual secrets.

4. **Silent corruption of confirmed cognition**  
   Confirm requires evidence + human actor. Consolidation and session closure never confirm Memory/Judgment. Revision collisions go to DLQ, never overwrite.

5. **Runtime poison / stuck workers**  
   CAS claim, leases, DLQ for permanent errors; `model_unavailable` stays retryable (never DLQ). Vault isolation on claim.

6. **Exfiltration via tool output / context packs**  
   Blocked items report counts/reasons, not forbidden content. Injection-screened packs. Capability-gated MCP surfaces.

7. **Incomplete deletion / backup leakage**  
   Tombstones + source deletion events. Backup/export are full-fidelity — operators must protect backup media. Encrypted/incremental backup hardening remains follow-on work.

8. **Malicious or buggy MCP client**  
   Capability checks; preview/confirm fingerprints on agent-facing mutating connector ops; fail closed on missing principal/scope.


## Residual risk

Operators still must: protect `$TWIN_HOME` and backup directories, rotate connector tokens, and treat every external document as adversarial input.

Connect via [INTERFACES.md](INTERFACES.md). Install in [SETUP.md](SETUP.md). Operate in [OPERATIONS.md](OPERATIONS.md). Product in [PRODUCT.md](PRODUCT.md). Roadmap in [ROADMAP.md](ROADMAP.md). Changelog in [CHANGELOG.md](CHANGELOG.md).
