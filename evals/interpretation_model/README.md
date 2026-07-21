# Real-model interpretation evals (v0.7, optional)

The deterministic suite in `evals/interpretation/` proves the *pipeline* —
governance, grounding, cognitive-act handling — using a scripted interpreter.
It deliberately does **not** exercise the actual prompt and local model, so it
cannot tell you whether the configured interpreter is any good.

This second layer does. It runs the real cognitive interpreter
(`TWIN_EXTRACTOR=ollama`) against a small labelled set and measures the
qualities v0.7 depends on:

- cognitive-act classification (statement / question / hypothesis / proposal /
  decision / opinion / third-party claim);
- memory-type precision;
- speaker / participant attribution accuracy;
- evidence-span literality (does the model quote verbatim?);
- unresolved-reference recall (does it flag ambiguity instead of guessing?);
- run-to-run stability;
- invented-item rate (items whose span is not in the source).

It is **optional and never gates CI** — it needs a running Ollama and a model,
and its pass/fail thresholds are judgement calls. Run it manually or nightly:

```
TWIN_EVAL_MODEL=1 TWIN_OLLAMA_MODEL=qwen3.6:latest python -m evals.interpretation_model.run
```

Without `TWIN_EVAL_MODEL=1` (or with no reachable model) the runner prints a
skip notice and exits 0, so it is safe to wire into a nightly job that may not
always have a GPU.

Cases live in `cases/*.json` and reuse the same fixture shape as
`evals/interpretation/`, plus per-item `expected_cognitive_act`,
`expected_type` and `expected_attributed_to` labels for scoring.
