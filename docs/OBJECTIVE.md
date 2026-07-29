# Objective

Twin exists to explore a larger possibility than persistent chat memory: a person should be able to own a durable, portable and evolving cognitive counterpart that remains continuous across models, tools and time.

This document defines that destination. It is not a release plan or a description of the current implementation. The roadmap in [PRODUCT.md](PRODUCT.md) describes what is built next; this document explains what those increments should ultimately converge toward.

## The problem

Modern LLM-powered tools are capable but discontinuous. Each model, application and session receives only a partial view of the person using it. Important context is repeatedly lost or reconstructed:

- facts and past experiences;
- decisions and rejected alternatives;
- goals, commitments and unresolved work;
- preferences and domain-specific constraints;
- relationships between events, people and projects;
- the reasoning behind previous choices;
- beliefs and priorities that change over time.

Long context windows, product memory, retrieval systems and knowledge graphs reduce repetition, but mostly improve access to stored information. They do not by themselves maintain a coherent model of what information means, when it is valid, why it matters, what superseded it, which context may use it, or how it should influence a future decision.

The deeper problem is therefore not simply storage or retrieval. It is **cognitive continuity**: preserving an inspectable and useful representation of a person across changing interfaces and intelligence providers without surrendering privacy, ownership or authority.

## The current scenario

The ecosystem is rapidly converging on several useful capabilities:

- persistent memories for assistants and agents;
- vector and graph-based retrieval;
- structured context databases;
- personal knowledge systems;
- autonomous agents, skills and workflows;
- standardized access through protocols such as MCP;
- local-first and self-hosted alternatives.

These developments validate the underlying need, but they also make weak differentiation insufficient. Memory, graphs, connectors, agents and context assembly are no longer novel in isolation. Twin should not define its ambition as merely combining those features.

Most existing systems primarily optimize one boundary: retrieving knowledge, organizing context, executing tasks, operating an agent, or representing a graph. Twin should aim at the layer that connects and governs those capabilities around a persistent human model.

Its present architecture provides part of that substrate:

- normalized percepts rather than treating raw artifacts as memories;
- evidence-backed and temporally scoped memories;
- a canonical graph with embeddings used as indexes;
- deterministic domain and privacy boundaries before reasoning;
- judgment modeled separately from factual memory;
- personas and context-specific access;
- portable context packs for multiple authorized tools;
- human control over durable conclusions;
- model-independent, local-first storage and exportability.

These foundations are necessary, but they are not the final objective. Twin must eventually demonstrate capabilities that cannot be reduced to “better RAG” or “another memory server.”

## Where to aim

Twin should aim to become an **open cognitive architecture and runtime for a persistent, self-correcting digital counterpart**.

A digital counterpart is not a chatbot impersonating its owner and not an autonomous clone. It is a user-controlled computational representation that can preserve continuity, interpret relevant history, support judgment and progressively act within explicit limits.

The long-term system should be able to represent not only what happened, but also:

- how knowledge was acquired and how reliable it is;
- why a decision was made;
- which assumptions, values and constraints influenced it;
- what outcome followed;
- whether later evidence changed the conclusion;
- which preferences are stable, contextual, aspirational or obsolete;
- where the system is uncertain or internally inconsistent;
- which parts of the model may be exposed in a given domain;
- which actions may be suggested, prepared or executed.

The desired progression is:

```text
observe
  → remember
  → understand
  → model identity and context
  → support judgment
  → detect uncertainty and contradiction
  → suggest
  → act within explicit authority
  → observe outcomes
  → revise
```

Twin should preserve the user’s authority throughout this progression. Models may propose interpretations, memories and revisions, but identity-level claims, durable judgment and delegated authority require proportionate evidence, transparency and control.

## Core research directions

### Longitudinal identity

Represent a person as an evolving history rather than a static profile. Preserve changes, contradictions, life phases, roles and context-dependent behavior without flattening them into one current summary.

### Causal and decision memory

Move beyond isolated facts and associations. Capture decision episodes linking context, evidence, alternatives, active values, judgment, action, outcome and later reflection.

### Judgment modeling

Learn how the user evaluates trade-offs while keeping judgment distinct from factual memory. Record scope, exceptions, confidence, revisions and the evidence behind each principle.

### Epistemic self-correction

Treat inferred knowledge as falsifiable. Detect contradictions, supersession, stale beliefs, weak evidence and model disagreement. Preserve historical states while maintaining a defensible current view.

### Contextual identity and privacy

Determine what an authorized intelligence may know and apply for a specific persona, purpose, domain and audience before reasoning begins. Privacy must be part of cognition, not a filter applied after generation.

### Model-independent continuity

Ensure that the user’s accumulated memory, identity, judgment and permissions survive replacement of every model, application and provider. Models should remain interchangeable processors over a user-owned substrate.

### Progressive agency

Develop from recall toward bounded delegation without collapsing understanding into action. The system must distinguish acting for the user, acting as the user and merely proposing an action.

## How progress should be evaluated

Twin should be judged by observable cognitive behavior, not by the number of integrations, graph nodes or stored documents.

Useful evaluation questions include:

1. Can Twin identify which of two conflicting memories is current and explain why?
2. Can it distinguish a temporary choice from a stable preference?
3. Can it reconstruct why a past decision was made, including rejected alternatives?
4. Can it recognize that one principle applies at work but not in a personal domain?
5. Can it expose uncertainty instead of presenting an inference as fact?
6. Can it revise a judgment after observing the result of an action?
7. Can it transfer useful understanding between models without exposing unrelated private context?
8. Can the user inspect, correct, export or remove every durable part of the resulting model?
9. Can the system remain coherent after changing the underlying LLM provider?
10. Can it demonstrate better decisions or lower re-explanation than simpler memory and retrieval baselines?

The project should publish repeatable scenarios, failure cases and comparative evaluations wherever possible. Architectural language is only valuable when it produces behavior that can be tested.

## Product and research strategy

Twin should proceed on two connected tracks.

The **product track** should deliver a practical, local-first cognitive substrate that users can adopt incrementally: reliable memory, safe context packs, evidence, domain isolation, session continuity and useful integrations.

The **research track** should investigate the harder objective: longitudinal identity, causal memory, judgment formation, metacognition, outcome-based revision and progressively delegated agency.

The product must remain useful before the complete vision exists. The research vision must prevent near-term market categories from reducing Twin to a generic memory layer.

## Objective statement

> Twin aims to give a person ownership of a portable, inspectable and evolving cognitive counterpart whose memory, identity and judgment remain continuous across models and interfaces, whose conclusions remain grounded and correctable, and whose agency grows only within explicit human authority.

The immediate implementation may begin with technical memory and MCP-delivered context. The destination is broader: not an AI that merely remembers the user, but infrastructure through which a durable part of the user’s cognition can safely exist outside any single model or application.
