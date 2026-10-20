# Why I stopped working on Twin

Twin ran for four months: 248 commits, about 105,000 lines of code, 12 releases on PyPI. I used it only on my own data. The goal is still right: stop explaining the same things to every AI. The design I chose to reach it was wrong, and patching the code would not fix that.

## Architecture problems

- **Every durable item needed my approval.** The LLM did the thinking. Then a human step decided what the system could keep. The system was only as good as my patience.
- **Local models.** I wanted the whole system to run locally. Local models were too slow, and their quality was too low for staged reasoning. Frontier models gave much better results.
- **Two cognition paths.** An old engine and a new engine ran on the same data. The LLM was paid twice, and the MCP tools still served the old model.
- **Batches did not mix sources.** I chose batches by ingestion time. The cross-source synthesis that Twin promised almost never happened.
- **Stages had no memory.** 6 of the 8 LLM stages never read the state left by earlier runs. Nothing was deduplicated or linked between runs. One broad "stale" rule marked too many items as out of date.
- **Open output schemas.** All stages shared one loose JSON shape, and models invented their own formats. In one run, a string was read as a list, and one batch produced 3,569 one-character "reflections". In another, all five stance drafts I checked were copies of the narrative text.
- **Fallbacks that hid failures.** A heuristic replaced the LLM in one stage.
- **No cost or quality controls.** The system had no prompt caching, no choice of model per task, and no evaluation against a simple baseline.

## Product and UX problems

- **I was the bottleneck.** Reviewing narratives one by one was tiring. The system should have done that work.
- **The wrong unit of knowledge.** The main object was a narrative: an interpretation that waited for my confirmation before it counted. I prefer a wrong answer that I can correct over many hypotheses that wait for me. A narrative also hid the evidence behind it, so it was hard to check.
- **Lists did not help.** I tried to explore the knowledge as lists. They did not make sense, and I could not see how facts connected over time.
- **Too many concepts.** Twin used percepts, situations, reflections, interpretations, narratives, stances and epistemic state. The words made the system hard to explain, hard to use and hard to check.
- **A promise that was too large.** "A personal cognitive OS" turned every question into a design question. I could not say what "better" meant, so I could not tell whether Twin worked.
- **One model for every interface.** The CLI, the REST API, the web UI and the MCP server all exposed the same model. The MCP server had about 53 tools. A long tool list costs tokens in every session, and it makes the AI choose worse.
- **A UI that did not fit the job.** The web UI had hard limits, such as 200 rows without pagination. The cost estimate of a run was wrong because the pending queue was not cleared correctly. The CLI was large, but I only needed it to keep the process running.

## How can this be fixed

1. **No approval gate.** The system writes its result. I correct it afterward. My corrections win, and a deletion also removes the text derived from the deleted item.
2. **Frontier models and no fallback.** If the LLM is not available, the run stops. No heuristic takes its place.
3. **One cognition path.** Every stage uses a closed JSON schema.
4. **Stages that read earlier state.** Batches mix sources. Staleness has one rule for each type of knowledge (profile, event, decision, entity state, cause), and an LLM applies it.
5. **Small building blocks with evidence.** The unit is an atomic claim with its source. Summaries and pages cite the claims behind them, and they go stale only when a cited claim changes. The reader can go down from a summary to the evidence.
6. **A graph view with a time slider** in place of lists, and the settings for models, budget and sources in the web UI.
7. **A small tool surface.** About five MCP tools, with a short, pushed context.
8. **A smaller vocabulary and one clear goal:** stop re-explaining myself to every AI. A result is better only if I repeat myself less.
9. **Quality checks from the first day:** prompt caching, one model for each role, and a comparison with a plain-search baseline.
