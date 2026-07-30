# Cognitive interpretation evals

Offline, deterministic checks that the pipeline catalogues an interpreter's
output correctly and safely. A **scripted interpreter** is injected via
`set_interpreter_override`, so no LLM and no network are involved — the LLM
interpreter itself is out of scope here; what we verify is the governance its
output flows through.

Cases (`cases/*.json`):

- **semantic_classification** — distinct memory types from one source; a
  rejected alternative becomes a decision carrying
  `payload.rejected_alternative`;
- **speaker_attribution** — a third-party claim is attributed to its speaker,
  marked not-owner, and born needing review;
- **evidence_grounding** — an item with no evidence span is dropped, not
  stored; the grounded item keeps its evidence;
- **proposal_vs_decision** — a proposal is held for review by its cognitive
  act while a settled decision is not, regardless of confidence.

Run:

```
python -m evals.interpretation.run
```
