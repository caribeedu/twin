# Operations

This document explains day-2 operation — cognitive runtime, health,
connectors, backup, release gates and incidents.

Install and providers: [SETUP.md](SETUP.md). Interfaces and connector
concepts: [INTERFACES.md](INTERFACES.md) · [CLI.md](CLI.md#connectors).
Destination: [README](../README.md).

## Start cognitive runtime

Required for Claude Code native hooks: deferred domain resolve and SessionEnd consolidation run as background jobs.

```bash
twin runtime start          # live processing panel on TTY; or: twin-runtime
twin runtime start --no-live
twin runtime status         # queue depth + recent jobs
twin runtime status --json
```

Workers claim durable jobs, including:

| Kind | Typical producer |
|---|---|
| `session_domain_resolve` | Native UserPromptSubmit when search cannot name a domain |
| `session_complete` | Native SessionEnd (binding already closed) |
| `interpret_percept` | Manual / extract pipelines |
| `workspace_tick` / `attention_evaluate` | Workspace / session deltas |
| `consolidate_daily` / `consolidate_weekly` | Scheduler (`twin runtime schedule` or start loop) |
| `integrity_check` | Scheduler |
| `connector_reconcile` | Recovery / manual enqueue |
| `backfill_partition` | Scheduler / `twin connector backfill --run` (historical; not continuous sync) |
| `reembed_memory` | Manual enqueue |

Full CLI table and payload examples in [CLI.md](CLI.md#runtime).

```bash
# inspect / recover one job
twin runtime job <job_id>
twin runtime retry <job_id>
twin runtime cancel <job_id>
```

## Health

```bash
twin doctor
twin runtime status
curl -s localhost:PORT/api/runtime/health
curl -s localhost:PORT/api/health/cognition
twin connector due
```

`twin doctor` reports runtime queue health from the store (no pidfile, so it never claims a worker is "up"):

- `runtime:queue` — warns with `N jobs pending — run \`twin runtime start\`` when work is backlogged (native SessionEnd consolidation + domain resolve run here).
- `runtime:failed` — jobs retrying with backoff.
- `runtime:dead_letter` — fails; inspect and requeue with `twin runtime retry <job_id>`.

## Connector recovery

```bash
twin connector sync-due
# or enqueue via runtime:
twin runtime enqueue connector_reconcile
twin connector production-ready   # attest ≥2 real adapters
```

Paused / unauthorized instances stay out of syncable sets until credentials are fixed and resumed.

## Dead letters

```bash
twin runtime status                 # includes dead-letter count
twin runtime retry <job_id>         # requeue failed / dead-lettered runtime job
# connector DLQ:
twin connector dead-letters <connector_id>
twin connector replay <id>
```

Permanent handler failures land in DLQ. `model_unavailable` on model-gated kinds (`interpret_percept`, `workspace_tick`, `session_domain_resolve`, `session_complete`, …) must stay pending/retry — never DLQ.

## Backup / restore

```bash
twin backup create ./backup-dir
twin backup validate ./backup-dir
twin backup restore ./backup-dir ./restored.db
```

Validate before restore. Restored DB is isolated until you point `$TWIN_HOME` / config at it.

## Memory formation (human control)

```bash
twin memory candidates
# confirm / reject only with evidence present
twin review
```

**Default:** humans confirm Memory; Judgment always stays human-gated. Do not automate confirmation of Judgment. Opt-in `twin extract -A` (auto-confirm new *memory* candidates) is for trusted demos or tightly scoped pipelines only — not the recommended day-one path. See [INTERFACES.md](INTERFACES.md).

## Correlation & Episode cognition

Episode cognition is the brain-staged chain documented in [ARCHITECTURE → Brain analogies and CLI stages](ARCHITECTURE.md#brain-analogies-and-cli-stages). It requires an **interpreting** extractor (`TWIN_EXTRACTOR=auto` / `ollama` / a cloud chat client). When the model is unreachable, interpreting stages **defer** — they never invent an arc from lexical rules; `extractor=heuristic` blocks those stages outright.

The happy path after connector sync / backfill (and usually after `twin extract` + review of atomic candidates) is a single orchestrator command:

```bash
twin meditate                          # sensory…cortex → reflect → (review?) → judgment drafts
twin meditate --review                 # step through the candidate review inline (TTY)
twin review                            # confirm/reject reflected trajectory candidates
twin judgment preview <proposal_id>    # inspect a prefrontal draft before approve
```

Or run it stage by stage:

```bash
twin correlate                         # sensory → amygdala → basal → hippocampus_bind → cortex
twin episode list                      # pick an id (consolidate=ready = cortex built ≥2 phases)
twin episode show <id>                 # summary + phases + edges (method=llm, brain_stage=…)
twin episode confirm-edge <edge_id>    # optional; survives cortex rebuilds
twin episode reflect <id>              # hippocampus_consolidate → trajectory MemoryCandidates
twin episode reflect <id> --dry-run    # preview claims without persisting
twin review                            # confirm/reject reflected candidates
twin judgment propose-episode <id>     # only after trajectory memories are confirmed
```

Day-to-day after the first full pass:

```bash
twin meditate --incremental            # or: twin correlate --incremental
twin correlate --until sensory         # debug: structural scaffold only (no model needed)
```

- **`--full` vs `--incremental`:** run `--full` as the periodic correctness oracle and after schema/logic changes; use `--incremental` for routine, cheap passes (it re-correlates only the vault partitions of records the connector commit/tombstone path marked dirty, then clears the dirty index). Both **daily** and **weekly** consolidation run `episode_cortex` (sensory→cortex, incremental) then `episode_reflect` (candidates only; gate skips structural PR→commit). Weekly additionally drafts judgment proposals. `twin meditate` stays the human path (optional review + judgment drafts).
- **Deferred stages:** if `twin correlate`/`twin meditate`/`twin consolidate daily` reports cortex deferred, the chat model was unreachable — start Ollama (or configure the client), then re-run. Existing phases/edges from a prior successful pass are kept, not wiped.
- **Approved atomic memories ≠ episode reflect.** Backfill + review confirms *extract* candidates. Episodes need `twin correlate` first; `reflect` (`hippocampus_consolidate`) then adds *trajectory* candidates ("intended X → chose Y") for another `twin review` pass. Neither path auto-confirms Memory or Judgment.
- **`reflect` readiness:** an episode is consolidate-ready once the `cortex` stage built ≥2 phases; the reflect model then decides whether the arc yields a trajectory claim (or none). `twin meditate` never auto-confirms Memory nor auto-approves Judgment.
- **`reflect` does not replace `extract`.** Promote a confirmed trajectory into a pending Judgment proposal with `twin judgment propose-episode <id>` (`prefrontal` stage; human approval only).

## Release gate

```bash
twin eval golden
twin connector production-ready
pytest -q
```

`twin eval golden` exercises the cognitive work-loop. `production-ready` reports whether real adapters (not Fake) close the shared contract. Behavior lives in ordinary pytest suites under `tests/` — not in version or phase checklists.

## Incident: injection suspected

1. Quarantine / reject affected candidates.
2. Confirm packs exclude injection (`blocked` reasons, not content).
3. Rotate any secrets that appeared in source text.
4. Re-run `GET /api/health/cognition` / integrity job.

---

Install in [SETUP.md](SETUP.md). Interfaces in [INTERFACES.md](INTERFACES.md). Overview in [README](../README.md).
