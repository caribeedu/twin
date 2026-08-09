# Cognize

This document owns the **Cognize pipeline** — staged formation and revision
of Narratives. It is **not** the public architecture diagram.

Public walls: [ARCHITECTURE.md](ARCHITECTURE.md) (Sense → Cognize → Inject).  
Design contracts: [v2.md](v2.md) §2.  
Epistemics: [EPISTEMICS.md](EPISTEMICS.md).  
Vocabulary: [GLOSSARY.md](GLOSSARY.md).  
Implementation inventory: [v2-tracker.md](v2-tracker.md).

**Status:** stub while Twin v2.0 lands. Prefer [v2.md](v2.md) §2 for full
I/O contracts until stages are implemented in code.

---

## Stage map

Every thinking stage requires a live chat LLM. Missing model → **halt**
(no Reflections, Interpretations, Relations, Narrative Revision, Stance
drafts, or Fade/Remarkable judgment).

| # | Stage | Question | Primary writes | Engine |
|---|---|---|---|---|
| 0 | Salience gate | Worth cognitive work now? | salience / drop / defer | LLM |
| 1 | Situate | Which Situation cluster? | Situation membership | LLM |
| 2 | Raise Reflections | What is still unknown? | Reflection | LLM |
| 3 | Form Interpretations | Candidate explanations? | Interpretation | LLM |
| 4 | Cross Reflections | Same / related / conflicting asks? | Reflection↔Reflection Relation | LLM |
| 5 | Cross Interpretations | Support / contradict / same claim? | Interpretation↔Interpretation Relation | LLM |
| 6 | Narrative Revision | How should new interpretations change the account? | revision decisions + retain dissent | LLM |
| 7 | Evidence audit | What warrants each Interpretation? Independence? | Evidence links, `same_originating_decision` | LLM |
| 8 | Human review | What may become durable? | review decisions | Human |
| 9 | Commit Narrative | Apply human accept | Narrative + EpistemicState | Persist only |
| 10 | Stance drafts | How evaluate similar cases later? | pending Stance | LLM |
| 11 | Consolidation judgment | Generalize vs stay episodic? | consolidation tags / drafts | LLM |
| 12 | Fade / Remarkable | What stays accessible? | accessibility recommendations | LLM |

Entities and lifecycles: [GLOSSARY.md](GLOSSARY.md) · [v2.md](v2.md) §2.2.

Narrative Revision decision shape: [v2.md](v2.md) §10.

---

## Legacy episode pipeline

Pre-v2 CLI still exposes brain-named episode stages (`sensory` →
`prefrontal`) via `twin correlate` / `twin meditate`. Those are transitional
aliases toward Cognize; semantic stages must **halt** without an LLM rather
than invent meaning. See [ARCHITECTURE.md](ARCHITECTURE.md) § Brain
analogies and CLI stages.
