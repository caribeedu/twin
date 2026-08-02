# Cognition

This document explains Twin’s core cognitive concepts — **understanding**
and **situation models** — and how they relate to artifacts, percepts,
memory and judgment.

It does not specify the runtime pipeline
([ARCHITECTURE.md](ARCHITECTURE.md)) or academic lineage
([FOUNDATIONS.md](FOUNDATIONS.md)). Identity and unit of value:
[IDENTITY.md](IDENTITY.md). Short definitions: [GLOSSARY.md](GLOSSARY.md).
Destination narrative: [README](../README.md).

---

## Understanding

Understanding is not a collection of documents, embeddings or memories.

Twin defines **Understanding** as a reusable semantic representation of
a situation. It answers:

- What actually happened?
- Why did it happen?
- Who was involved?
- What changed?
- What is now true that wasn't true before?

If Twin stores or retrieves information without increasing understanding,
it has failed ([IDENTITY.md](IDENTITY.md#the-unit-of-value)).

### Relationship to Other Concepts

| Concept | Role |
|---|---|
| Artifact | Raw observation |
| Percept | Structured observation |
| **Situation Model** | Transient structure that explains a coherent situation |
| **Understanding** | Reusable interpretation formed from situations / correlated percepts |
| Memory | Durable knowledge extracted from understanding |
| Judgment | How similar situations should be evaluated later |

### Example

Artifacts:

- Slack: “Feature A blocks launch.”
- GitHub: PR #15 implements Feature A.
- Slack: “I've merged it.”

Understanding:

> John requested Feature A because launch was blocked. Edu implemented
> it in PR #15. The merge removed the launch blocker.

This understanding can later produce memories, decisions and governed
context packs — without forcing every consumer to re-read the raw
artifacts. Same narrative: [README — Concrete Example](../README.md#concrete-example).

---

## Situation Models

Humans rarely remember isolated messages. They remember situations.

Twin adopts **Situation Models** as the primary abstraction for forming
understanding — before durable memory is written. Hypothesis under test:
[RESEARCH.md](RESEARCH.md#hypothesis-2--situation-models-are-the-correct-cognitive-primitive).

### Components

A Situation Model may include:

- actors;
- intentions;
- goals;
- constraints;
- causal relationships;
- evidence;
- temporal evolution;
- outcomes;
- unresolved questions.

### Lifecycle

```text
Artifacts → Percepts → Correlation → Situation Model → Understanding
    → Memory → Reflection → Judgment
```

Situation Models are **transient** cognitive structures. They exist to
explain what happened before durable memory is created. What leaves that
process as reusable interpretation is **understanding** (above).

### Design Principle

A Situation Model should summarize **reality**, not summarize documents.

That aligns with understanding before memory and evidence before belief
([IDENTITY.md](IDENTITY.md#design-principles)).
