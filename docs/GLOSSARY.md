# Glossary

This document explains Twin’s shared vocabulary — short definitions so
other docs can link here instead of redefining terms.

Deeper concepts: [COGNITION.md](COGNITION.md). Identity and unit of
value: [IDENTITY.md](IDENTITY.md). Twin v2 redesign:
[v2.md](v2.md). Destination narrative: [README](../README.md).

---

## Sense / Cognize / Inject

Twin’s three hard modules ([ARCHITECTURE.md](ARCHITECTURE.md),
[v2.md](v2.md) §1):

| Module | Role |
|---|---|
| **Sense** | Deterministic capture and normalization into Artifacts / Percepts |
| **Cognize** | LLM-driven formation and revision of Narratives (pipeline detail in [COGNIZE.md](COGNIZE.md)) |
| **Inject** | Domain Firewall + governed packs (+ Observer slot) toward authorized hosts |

---

## Artifact

A raw piece of information collected from a connector or local source.

## Percept

A normalized, attributable observation produced by Sense from one or more
artifacts. Immutable once stored.

**Observed** percepts come from Sense connectors. **Derived** percepts are
Cognize-synthesized (episode/pattern arcs) and are *not* Cognize Reflections
(open epistemic gaps).

## Situation

Clustering of percepts that appear to belong to the same happening
(container — not the durable product). Lifecycle: `working` → `concluded`.
The older phrase **Situation Model** refers to this idea; runtime may still
carry related structure as `WorkEpisode` until Cognize Situate fully lands.

## Reflection

An open epistemic gap: a question, tension, or unresolved framing the
system is holding. Lifecycle: `open` → `answered` / `superseded` /
`faded`. Always visible in Review.

*(Legacy sense: “reflection” as a process verb still appears in older
docs; the product noun is this entity.)*

## Interpretation

A candidate **explanation** of a Situation / Reflection set — competing,
revisable, not an answer to a user query. Lifecycle: `competing` →
`rejected` / `merged` / `superseded` / `committed-as-Narrative`.

## Relation

A typed link among Reflections, Interpretations, Narratives, or Evidence —
asserted by Cognize (LLM), not by embeddings alone. Types include
`same-as`, `related`, `supports`, `contradicts`, `depends-on`,
`supersedes`, `part-of`, `continues`, and **`same_originating_decision`**.

## Narrative

Human-accepted, evidence-backed, temporally bounded, revisable **account**
of a situation (actors, causality, goals, state change) — not fiction and
not a styled summary. Optional soft `grain`: `episode` \| `arc` \|
`domain`. May be marked **stale**. Durable product unit.

## EpistemicState

Freshness and evidence-set metadata attached to a Narrative (and optionally
an Interpretation): `synthesized_at`, `freshness_boundary`, `unseen_since`,
`status` (`fresh` \| `stale` \| `superseded` \| `tombstoned`),
`stale_reason`, `evidence_ids`. **Confidence is not a stored scalar** — it
is derived at read / Inject / Review time. See [EPISTEMICS.md](EPISTEMICS.md).

## Stance

How similar situations should be evaluated later — evaluative posture,
kept distinct from factual Narratives. Public name for what older docs
called **Judgment**. Lifecycle: `pending` → `approved` → `active` /
`deprecated`.

## Evidence

Anchored percept span (source id, timestamp, ACL tags) that warrants an
Interpretation or Narrative. Losing / dissenting evidence stays attached
when contradictions resolve.

## Trace

Append-only retrieval / use events that inform accessibility policy
(Fade / Remarkable).

## Understanding

**Not** a schema root or required table. Understanding is the *emergent*
state produced by:

```text
Narratives + Relations + EpistemicStates + Stances
  + Open Reflections (+ Evidence)
```

Full discussion: [COGNITION.md](COGNITION.md#understanding).

## Governed Context

A context package assembled after privacy, domain and policy evaluation —
privacy before reasoning ([IDENTITY.md](IDENTITY.md#design-principles)).
Inject packs must attach EpistemicState and must not present stale
Narratives as fresh.

## Cognitive Continuity

The ability for different AI systems to progressively understand the
same person over time rather than repeatedly starting from zero. See
[README — The Problem](../README.md#the-problem).

---

## Migration note (deprecated product terms)

| Deprecated (avoid in product / CLI / MCP copy) | Prefer |
|---|---|
| **Memory** (as product noun / `twin memory`) | **Narrative** (+ Relations) |
| **Judgment** (public name) | **Stance** (`twin stance`) |
| **Situation Model** (as sole label) | **Situation** (+ Narrative as the durable account) |
| Understanding as a stored row / table | Understanding as **emergent** (above) |
| Package names `twin.memory` / `twin.judgment` / `twin.cognition` as product architecture | Target packages in [ARCHITECTURE — Code packages](ARCHITECTURE.md#code-packages-target-layout) |
| Purpose `memory_retrieval` | `context_retrieval` |
| Store facade `MemoryStore` | `TwinStore` |
| Lifecycle `merge_memories` / `archive_memory` / `split_memory` | `merge_claims` / `archive_claim` / `split_claim` |
| REST `/api/memories` | `/api/claims` |
| Interpreter JSON `memory_type` | `claim_type` |
| Connector config `allow_memory_types` | `allow_claim_types` |
| Metrics `memory_usage_rate` / `false_memory_rate` | `claim_usage_rate` / `false_claim_rate` |
| `gather_related_memories` / `related_memories` | `gather_related_claims` / `related_claims` |
| Job kind `reembed_memory` | `reembed_claim` |
| Stance proposal metadata `memory_count` | `claim_count` |
| Privacy purpose / pack default | `context_retrieval` only |

Academic citations may still say “memory” (paper titles). Everyday speech
(“Twin remembers”) is fine in conversation; commands, schema, and product
docs should not.

Code note: internal `StoreClaim` rows (table `store_claims`, id prefix
`clm_`) hold dual-read claim data until Cognize maps them to Narratives —
see [v2-tracker.md](v2-tracker.md) (v2.5 dual-read schema rename).
