[← README](../README.md) · [FOUNDATIONS](FOUNDATIONS.md) · [PRODUCT](PRODUCT.md) · [ROADMAP](ROADMAP.md) · [CHANGELOG](CHANGELOG.md) · [ARCHITECTURE](ARCHITECTURE.md) · [INTERFACES](INTERFACES.md) · [SETUP](SETUP.md) · [OPERATIONS](OPERATIONS.md)

# Foundations

**Source of truth for:** why Twin exists — philosophy and academic inspirations (Extended Mind, 4E, memory systems, GWT, ACT-R, …).

This document answers *why the shape of Twin is the way it is*. It deliberately mixes philosophy, cognitive science and neuroscience as **design inspiration**, not as implementation claims. How Twin is built in [ARCHITECTURE.md](ARCHITECTURE.md). What it delivers in [PRODUCT.md](PRODUCT.md). Versions in [CHANGELOG.md](CHANGELOG.md) / [ROADMAP.md](ROADMAP.md). Short narrative in [README](../README.md).

## Academic and conceptual foundations

The project draws on several areas: philosophy of mind, cognitive science, neuroscience, psychology, symbolic AI, knowledge graphs, human-computer interaction and cognitive architectures.

### Extended Mind — Andy Clark and David Chalmers

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

### 4E Cognition

The **4E cognition** school understands cognition as:

- embodied — incorporated in the body;
- embedded — situated in an environment;
- extended — extended through tools;
- enactive — produced in active interaction with the world.

This line matters because the project does not treat thinking as something isolated inside the brain. The user thinks with tools, IDEs, documents, meetings, Slack, email, calendar, voice, notes and LLMs. `twin` tries to turn that scattered set into a coherent computational layer.

### Memory systems and brain mapping

Cognitive psychology and neuroscience distinguish episodic, semantic, procedural and working memory, plus executive control. Twin mirrors those separations in software (events vs graph vs procedures vs context packs vs firewall/judgment).

The **engineering mapping** (brain region to Twin component, and how it wires through the pipeline) lives in [Brain analogies](ARCHITECTURE.md#brain-analogies). The subsections below stay with the academic / conceptual motivation.

### Hippocampus, consolidation and temporality

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
Participants: Alex, Marina, Rafael
Decision: use Postgres outbox + dedicated worker
Rejected alternative: Kafka
Future condition: revisit Kafka if volume > 50k events/day
```

This is more useful than an entire transcript dumped into context.

### Prefrontal cortex, judgment and inhibition

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

### Amygdala, salience and risk

The amygdala and limbic circuits are associated with emotional salience, fear, risk, reward and affective relevance. In a future version, `twin` should represent something analogous to **salience**:

- is this urgent?
- is this emotionally sensitive?
- can this cause harm if leaked?
- is this important for future decisions?
- should this become a memory or be discarded?

In the initial concepts, this function partially shows up as `sensitivity`, `confidence`, `needs_review` and `review_reason`.

### Basal ganglia and action selection

The basal ganglia are frequently associated with action selection, habits and decision loops. For the project, this inspires future versions with safe automations:

```text
memory + context + judgment
        ↓
selection of a possible action
        ↓
draft / reminder / suggestion / automation with approval
```

The initial concepts deliberately does not execute autonomous actions. Before acting, the system needs to learn to remember, filter and judge.

### Global Workspace Theory — Bernard Baars, Stanislas Dehaene

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

### ACT-R — John R. Anderson

ACT-R is a cognitive architecture that separates declarative and procedural components, with activation, retrieval and production mechanisms. The project draws on that separation:

- declarative memory: facts, events, decisions;
- procedural memory: how the user usually does something;
- production/action: rules and decision criteria;
- activation: memory relevance for the current context.

`twin` does not implement ACT-R, but adopts the idea that memory and procedure are distinct categories.

### Predictive Processing and Active Inference — Karl Friston

Predictive processing and active inference models treat the brain as a system that maintains internal models, predicts the world and updates beliefs upon receiving prediction error.

For `twin`, this implies the system should not store only loose sentences like "the user prefers X". It should track the evolution of mental models:

```text
2023: the user considered microservices preferable for almost everything.
2026: the user came to prefer a modular monolith when maintainability and simplicity matter more.
Reason: hands-on experience with operational complexity.
```

This calls for temporality, contradiction, supersedence and belief history.

### Self-complexity and social roles

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

`twin` must not model only `User -> everything`. It must model:

```text
User
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

### Symbolic AI: semantic networks, frames and scripts

Before LLMs, symbolic AI already represented knowledge with semantic networks, frames and scripts.

`twin` reuses those ideas:

- triples/edges: `User -> prefers -> pt-BR answers`;
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

## Aesthetic inspiration

The long-term experience can draw on sci-fi and human–machine interfaces (exocortex, continuous coupling with tools). That inspiration belongs here — not in the product pitch. The implementation must stay sober, local-first, auditable and incremental.

---

Next: product shape in [PRODUCT.md](PRODUCT.md). Architecture principles and brain analogies in [ARCHITECTURE.md](ARCHITECTURE.md).
