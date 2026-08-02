# Research

This document explains Twin’s living research program — falsifiable
hypotheses, the engineering-research cycle, scenario benchmarks and open
directions.

Identity and unit of value: [IDENTITY.md](IDENTITY.md). Cognitive
concepts: [COGNITION.md](COGNITION.md). Product delivery:
[PRODUCT.md](PRODUCT.md). Planned engineering work (not this file):
[ROADMAP.md](ROADMAP.md). Destination narrative:
[README](../README.md#what-twin-is-trying-to-prove).

**Status:** living — revise when evidence demands it.

---

## Why This Document Exists

Twin is not driven by implementing every new AI capability.

It investigates:

> **How can software build, maintain and evolve a persistent
> computational understanding of a person across time, tools and
> models?**

Many systems already retrieve information, execute tasks, build
knowledge graphs or manage context. Twin asks whether those are
sufficient — or whether an intermediate layer of **understanding** is
required ([COGNITION.md](COGNITION.md)).

---

## Philosophy

> **Every architectural decision should validate or invalidate a
> hypothesis.**

Features are not success. Understanding is. Evaluate with reproducible
benchmarks, not anecdotes.

---

## Method

1. Observe a recurring limitation in current AI systems.
2. Formulate a falsifiable hypothesis (below).
3. Design a benchmark that isolates the problem ([#benchmarks](#benchmarks)).
4. Implement the smallest possible mechanism.
5. Evaluate against baselines (LLM, RAG, graph, agent).
6. Publish results, including failures
   ([IDENTITY.md](IDENTITY.md#how-twin-should-be-spoken-about)).
7. Refine the architecture only after evidence
   ([ARCHITECTURE.md](ARCHITECTURE.md)).

Architecture is an outcome of validated hypotheses — not the starting
point.

**Rule:** never add a cognitive layer because it sounds plausible. Add
it because a benchmark demonstrates measurable improvement in
understanding.

---

## Hypotheses

### Hypothesis 1 — Understanding is more valuable than retrieval

Distributed observations can be synthesized into reusable understanding
that is more useful than retrieving isolated documents.

Signals: better answers with fewer injected tokens, less repeated
explanation, higher factual consistency, better task completion.

### Hypothesis 2 — Situation Models are the correct cognitive primitive

The primary unit of long-term cognition should not be the document or
the message. It should be a [Situation Model](COGNITION.md#situation-models).

### Hypothesis 3 — Reflection should precede durable memory

Raw observations should be correlated, interpreted and reflected upon
before becoming durable memory — less noise, better abstraction, easier
correction, higher trust
([IDENTITY.md](IDENTITY.md#design-principles)).

### Hypothesis 4 — Judgment evolves independently from factual memory

Facts answer *what happened*. Judgment answers *how similar situations
should be evaluated in the future*. Twin should model both independently
([GLOSSARY.md](GLOSSARY.md)).

### Hypothesis 5 — Continuity depends more on understanding than context size

Larger context windows alone do not create continuity. Reusable
understanding accumulated over time should outperform simply injecting
more observations ([README — The Problem](../README.md#the-problem)).

---

## Benchmarks

Every benchmark should require understanding rather than retrieval.

Twin should be judged by observable cognitive behavior — not by feature
counts, graph size or document volume
([README — Success Criteria](../README.md#success-criteria)).

### Candidate scenarios

- Slack ↔ GitHub feature request resolution
- Meeting → RFC → Implementation
- Email contradicts documentation
- Preference changes over time
- Decision reversal after new evidence
- Multiple unrelated conversations forming one situation

Related narrative: [README — Concrete Example](../README.md#concrete-example)
· [COGNITION.md](COGNITION.md#example).

### Compare against

- Vanilla LLM
- RAG
- Knowledge graph systems
- Agent frameworks
- Future Twin versions

Measure whether a coherent understanding is produced — not whether
documents are retrieved ([IDENTITY.md](IDENTITY.md#positioning--not-these-categories)).

---

## Open Directions

Speculative by design. Promotion into the hypotheses above requires the
[#method](#method) cycle and a scenario from [#benchmarks](#benchmarks).

### Understanding revision

Can previous understanding be revised automatically when stronger
evidence appears?

### Situation boundaries

How does Twin decide whether two observations belong to the same
situation? ([COGNITION.md](COGNITION.md#situation-models))

### Longitudinal identity

Can understanding accumulated over years produce a stable computational
identity — without flattening a person into one summary?

### Judgment formation

Can repeated decision episodes produce explicit judgment models kept
distinct from factual memory?

### Understanding compression

How much understanding can replace raw context while improving reasoning
quality?

### Goal

Twin should progressively move from remembering events to understanding
situations, and eventually to assisting human judgment while remaining
governed and inspectable ([IDENTITY.md](IDENTITY.md)).
