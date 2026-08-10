# Cognition

This document explains Twin’s core cognitive concepts — **understanding**,
**situations**, and how they relate to artifacts, percepts, Narratives and
Stance.

It does not specify the full Cognize stage pipeline
([COGNIZE.md](COGNIZE.md) · [v2.md](v2.md) §2) or academic lineage
([FOUNDATIONS.md](FOUNDATIONS.md)). Identity and unit of value:
[IDENTITY.md](IDENTITY.md). Short definitions: [GLOSSARY.md](GLOSSARY.md).
Architecture walls: [ARCHITECTURE.md](ARCHITECTURE.md). Destination:
[README](../README.md).

**Package note:** conceptual “cognition” here is product language. The code
package `twin/cognition/` is transitional — its services (interpret, packs,
episodes, LLM adapters) fold into **`twin/cognize/`**, **`twin/inject/`**,
and **`twin/llm/`** per
[ARCHITECTURE — Code packages](ARCHITECTURE.md#code-packages-target-layout).
Prefer [COGNIZE.md](COGNIZE.md) for pipeline implementation.

---

## Understanding

Understanding is not a collection of documents, embeddings or “memory
blobs.”

Twin treats **Understanding** as an **emergent** state — not a schema root:

```text
Narratives + Relations + EpistemicStates + Stances
  + Open Reflections (+ Evidence)
```

A useful account of a situation answers:

- What actually happened?
- Why did it happen?
- Who was involved?
- What changed?
- What is now true that wasn't true before?

If Twin stores or retrieves information without increasing understanding,
it has failed ([IDENTITY.md](IDENTITY.md#the-unit-of-value)). The durable
product artifact that carries an accepted account is a **Narrative**, not
a Memory row.

### Relationship to Other Concepts

| Concept | Role |
|---|---|
| Artifact | Raw observation (Sense) |
| Percept | Structured observation (Sense) |
| **Situation** | Working cluster of percepts for one happening |
| **Reflection** | Open question / tension Cognize is holding |
| **Interpretation** | Competing candidate explanation |
| **Narrative** | Human-committed, evidence-backed, revisable account |
| **Stance** | How similar cases should be evaluated later |
| **Understanding** | Emergent state over the above — not a table |
| Memory | Transitional dual-read `MemoryItem` during store migration — not a product noun |

### Example

Artifacts:

- Slack: “Feature A blocks launch.”
- GitHub: PR #15 implements Feature A.
- Slack: “I've merged it.”

Narrative (after Cognize + human commit):

> John requested Feature A because launch was blocked. Edu implemented
> it in PR #15. The merge removed the launch blocker.

Hosts receive that account via Inject — without re-reading raw artifacts.
Same story: [README — Demonstration](../README.md#demonstration).

---

## Situations

Humans rarely remember isolated messages. They remember situations.

Twin uses **Situations** as the working container while Cognize raises
Reflections and Interpretations — before a human commits a Narrative.
Older docs say **Situation Model**; the runtime may still expose related
structure as `WorkEpisode` (phases + edges) until Situate fully replaces
it — see [ARCHITECTURE.md](ARCHITECTURE.md) (episode pipeline) and
[COGNIZE.md](COGNIZE.md).

Hypothesis under test:
[RESEARCH.md](RESEARCH.md#hypothesis-2-situation-models-are-the-correct-cognitive-primitive).

### Components

A Situation may include:

- actors;
- intentions;
- goals;
- constraints;
- causal relationships;
- evidence;
- temporal evolution;
- outcomes;
- unresolved questions (often surfaced as **Reflections**).

### Lifecycle

```text
Artifacts → Percepts → Situate → Reflections → Interpretations
  → Narrative Revision → Evidence audit → Human review
  → Commit Narrative → Stance drafts
```

Situations are working structure. **Narratives** are the durable,
governed accounts Inject may project. Understanding remains emergent.

### Design Principle

A Situation should summarize **reality**, not summarize documents.

That aligns with understanding before durable commit and evidence before
belief ([IDENTITY.md](IDENTITY.md#design-principles) · [v2.md](v2.md)).
