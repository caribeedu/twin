# CLI

This document explains the `twin` terminal surface — ingest, review,
connectors, runtime and scripting.

Global flag: `--home` sets Twin home (default `~/.twin` or `$TWIN_HOME`).

Add `--json` to any command for machine-readable output (mirrors `twin pack --json`). Machine protocol surfaces stay on their own transport: `twin native event` ([Native](NATIVE.md)), `twin mcp` ([MCP](MCP.md)), and `twin serve` ([REST](REST.md)).

## Setup & doctors

| Command | What it does |
|---|---|
| `twin init` | Create home, copy defaults, guided LLM/embed setup. |
| `twin init --skip-setup` | Home defaults only (CI / non-interactive). |
| `twin doctor` | Check store, policies, LLM reachability, MCP client configs. |
| `twin setup ollama` | Pull configured Ollama models. |
| `twin setup postgres` | Verify / prepare Postgres + pgvector. |
| `twin setup mcp <client>` | Write/merge MCP server entry (`cursor`, `claude-code`, `claude-desktop`). |

## Ingest, extract, review

| Command | What it does |
|---|---|
| `twin ingest <paths…>` | Run sensors over files/dirs (docs, transcripts, exports). |
| `twin extract` | Interpret pending percepts into memory candidates. |
| `twin extract -A` / `--auto-approve` | **Advanced / demos only:** extract and immediately confirm new *memory* candidates (skip queue). Not the recommended path — Judgment stays human-gated; prefer `twin review`. |
| `twin interpret status\|deferred\|signals` | Cognitive interpretation diagnostics (deferred queue, heuristic signals). |
| `twin review` | Interactive priority review queue. |
| `twin review --analyze` | Run quality analyzer on candidates first. |
| `twin review --priority high` | Filter queue by priority. |
| `twin review --conflicts` | Focus conflicted items. |
| `twin review-batch create\|resume` | Batch review sessions. |
| `twin serve` | Review workbench UI + local HTTP API (default `http://127.0.0.1:8765`). |

## Query

| Command | What it does |
|---|---|
| `twin search <query>` | Hybrid search (optional `--domain`). |
| `twin pack <query> --domain <domain>` | Build a safe context pack (candidates off unless flagged). |
| `twin observe <text>` | Memory observer suggestion for current text. |

## Memory lifecycle

| Command | What it does |
|---|---|
| `twin memory merge\|split\|provenance\|archive\|diff\|undo` | Consolidation ops on memory ids. |
| `twin supersede <new> <old>` | Mark newer memory as superseding older. |
| `twin contradict <a> <b>` | Record contradiction between memories. |
| `twin undo <op_id>` | Undo a recorded memory operation. |
| `twin reindex` | Regenerate embeddings with current embedder. |
| `twin retention [--dry-run]` | Apply retention policies. |
| `twin delete-source …` | Propagate deletion from an upstream source system. |
| `twin stats` | Memory / connector quality metrics. |

## Judgment

| Command | What it does |
|---|---|
| `twin promote <mem_id>` | Open a judgment proposal from a memory (does **not** auto-write). |
| `twin judgment import\|export\|list\|show\|history\|versions` | Bootstrap and inspect judgment store. |
| `twin judgment proposals\|propose\|preview\|approve\|reject\|defer` | Proposal lifecycle (approve needs preview token). |
| `twin judgment propose-episode <episode_id>` | Seed a proposal from an episode's **confirmed** trajectory memories (`provenance.source=episode_pattern`; human approval only). |
| `twin judgment simulate <query> --domain …` | Simulate applicable judgment. |
| `twin judgment conflicts [--refresh]` | List / refresh conflicts. |
| `twin judgment explain <trace_id>` | Explain a judgment application trace. |

## Correlation & Episode cognition

Correlation proposes revisable structure over connector evidence — never Memory or Judgment. Semantic episode cognition runs as an LLM chain whose stages are named for their brain analogy (see [ARCHITECTURE → Brain analogies and CLI stages](ARCHITECTURE.md#brain-analogies-and-cli-stages)). A missing model **defers** an interpreting stage — it never falls back to lexical rules, and `extractor=heuristic` blocks those stages with a clear message.

| Stage | Brain analogy | CLI surface |
|---|---|---|
| `sensory` | encoding substrate | `twin correlate --until sensory` (structural scaffold only) |
| `amygdala` | salience / role | `twin correlate` (classify member roles) |
| `basal` | action selection | `twin correlate` (episode lifecycle read) |
| `hippocampus_bind` | binding | `twin correlate` (membership consolidation) |
| `cortex` | semantic memory | `twin correlate` (phases + narrative edges) |
| `hippocampus_consolidate` | consolidation | `twin episode reflect` / `twin meditate` |
| `prefrontal` | executive control | `twin judgment propose-episode` / `twin meditate` |

| Command | What it does |
|---|---|
| `twin meditate [--full\|--incremental] [--no-reflect] [--no-propose] [--review] [--limit N] [--dry-run]` | **Orchestrator**: runs `sensory…cortex` → `hippocampus_consolidate` (reflect) → optional interactive `review` → `prefrontal` (judgment drafts). Never auto-confirms Memory nor auto-approves Judgment. The post-sync happy path. |
| `twin correlate [--full\|--incremental] [--until <stage>]` | Runs `sensory → amygdala → basal → hippocampus_bind → cortex` (phases + edges). `--full` (default) rescans all records; `--incremental` re-correlates only dirty records; `--until sensory` stops at the structural scaffold (debug). |
| `twin episode list [--vault] [--limit]` | List episodes with phase/edge counts and `consolidate=ready` (cortex built ≥2 phases). Empty until `twin correlate` has run. |
| `twin episode show\|explain <id>` | Summary + phases + edges (`method=llm`, `brain_stage=…`); `explain` is the full anchors/links dump (`--json` for scripts). |
| `twin episode phases <id>` | List the `goal → decision → execution → outcome` arc phases (built by the `amygdala`/`cortex` stages). |
| `twin episode edges <id>` | List proposed causal/narrative edges (`motivated\|superseded\|resolved\|continues\|contradicts`) from the `cortex` stage. |
| `twin episode confirm-edge\|reject-edge <edge_id>` | Human decision on an edge (survives cortex rebuilds). |
| `twin episode reflect <id> [--dry-run]` | The `hippocampus_consolidate` stage: synthesize trajectory **MemoryCandidates** ("intended X → chose Y") from the arc; candidates only, `review_reason=episode_reflect`. Defers if the model is unavailable. Does **not** replace `twin extract`. |

## Native

Host-lifecycle commands for Claude Code hooks. Behavior and profiles in [NATIVE.md](NATIVE.md).

| Command | What it does |
|---|---|
| `twin native install` | Write Claude Code hooks snippet + merge into `~/.claude/settings.json` (`--profile` / `--no-merge` / `--settings` / `--dir`) |
| `twin native uninstall` | Remove Twin hooks from settings (`--restore-backup` to restore the latest `.twin-bak`) |
| `twin native bindings` | List `HostSessionBinding`s |
| `twin native event` | Ingest a host event (JSON or `--stdin`; hooks use `--fail-open`) |

MCP status tools for the same bindings: `native_bindings`, `native_session_status` — see [MCP.md](MCP.md#connectors-and-meta) (native tools listed under Connectors and meta).

## Connectors

Source-adapter CLI. What each connector pulls (and does not) lives in [INTERFACES.md → Connectors](INTERFACES.md#connectors). Discovery helpers (`twin connector github repositories`, `slack channels`, …) list allowlist targets **before** you widen sync.

### Shared commands

| Command | What it does |
|---|---|
| `twin connector adapters` | List registered adapter types. |
| `twin connector setup <type> --source-owner …` | Guided plan (ownership, auth, scope, preview). **Never ingests.** |
| `twin connector add <type> --source-owner … [--secret …] [--config '{…}']` | Register account + instance. |
| `twin connector configure <id> [--secret …] [--config '{…}']` | Rotate credential or update configuration. |
| `twin connector list` | List instances (id, type, status, owner, vault). |
| `twin connector auth` / `test <id>` | Validate stored credentials. |
| `twin connector sync <id>` | Run one sync pass. |
| `twin connector due` / `sync-due` | Scheduler: what is due / run due connectors. |
| `twin connector pause` / `resume` / `revoke <id>` | Lifecycle controls. |
| `twin connector backfill --preview <id>` | Historical import preview (**never** starts ingest). |
| `twin connector backfill --create <id>` | Open a historical backfill job (no ingest yet). |
| `twin connector backfill --run [--job-id …]` | Enqueue + watch runtime drain partitions (requires `twin runtime start`). |
| `twin connector production-ready` | Report which real adapters close the production-ready contract. |
| `twin connector contract` | Print adapter contract matrix (evidence pointers into pytest). |

MCP mirrors (capability-gated; mutating tools need confirm): `connector_list`, `connector_status`, `connector_health_all`, `connector_sync`, `connector_backfill_preview`, `connector_dead_letters` — see [MCP → Connectors and meta](MCP.md#connectors-and-meta). HTTP webhooks: [REST](REST.md).

### GitHub

| Step | Command / surface |
|---|---|
| Plan | `twin connector setup github --source-owner personal` |
| Register | `twin connector add github --source-owner personal --secret "$GITHUB_TOKEN" --config '{"repositories":["owner/repo"]}'` |
| Validate | `twin connector auth <id>` |
| Discover | `twin connector github repositories <id>` |
| Sync | `twin connector sync <id>` |
| Webhook (optional) | `POST /api/webhooks/github/{connector_id}` with `X-Hub-Signature-256` — marks sync due; does not replace polling |

### Slack

| Step | Command / surface |
|---|---|
| Plan | `twin connector setup slack --source-owner employer` (or `personal`) |
| Register | `twin connector add slack --source-owner … --secret "$SLACK_BOT_TOKEN" --config '{…channels…}'` |
| Validate | `twin connector auth <id>` |
| Discover | `twin connector slack channels <id>` |
| Sync | `twin connector sync <id>` |
| Webhook (optional) | `POST /api/webhooks/slack/{connector_id}` (`X-Slack-Signature`, `url_verification`) |

### Gmail

| Step | Command / surface |
|---|---|
| Plan | `twin connector setup gmail --source-owner personal` |
| Register | `twin connector add gmail --source-owner personal` then `configure` with OAuth secret material |
| Discover | `twin connector gmail …` (account helpers) |
| Sync | `twin connector sync <id>` |

### Outlook

| Step | Command / surface |
|---|---|
| Plan | `twin connector setup outlook --source-owner employer` |
| Register | `twin connector add outlook --source-owner …` then OAuth `configure` |
| Discover | `twin connector outlook folders <id>` |
| Sync | `twin connector sync <id>` |

### Google Calendar

| Step | Command / surface |
|---|---|
| Plan | `twin connector setup calendar --source-owner personal` |
| Register | `twin connector add calendar --source-owner …` then OAuth `configure` |
| Discover | `twin connector calendar calendars <id>` |
| Sync | `twin connector sync <id>` |

### Fireflies

| Step | Command / surface |
|---|---|
| Plan | `twin connector setup fireflies --source-owner personal` |
| Register | `twin connector add fireflies --source-owner personal --secret "$FIREFLIES_API_KEY"` |
| Discover | `twin connector fireflies meetings <id>` |
| Sync | `twin connector sync <id>` |

### Local folder

| Step | Command / surface |
|---|---|
| Plan | `twin connector setup folder --source-owner personal` |
| Register | `twin connector add folder --source-owner personal --config '{"roots":["/path/to/notes"]}'` |
| Discover | `twin connector folder roots <id>` |
| Sync | `twin connector sync <id>` |

Empty roots leave the instance `awaiting_configuration` until roots are set.

### After sync

| Step | Command |
|---|---|
| Extract atomic candidates | `twin extract` |
| Episode cognition (happy path) | `twin meditate` (or `twin correlate` then `twin episode reflect`) |
| Human review | `twin review` |
| Scheduler | `twin connector due` then `twin connector sync-due` |

## Workspace & evals

| Command | What it does |
|---|---|
| `twin workspace tick …` | Parallel-memory observation/interpret tick. |
| `twin consolidate daily\|weekly [--apply]` | Consolidation cycle (dry-run by default). Both include `episode_cortex` (sensory→cortex, incremental) then `episode_reflect` (candidates only). Weekly also drafts judgment proposals. Never auto-confirms. |
| `twin eval extraction\|retrieval\|golden\|…` | Benchmarks and golden work-loop. |
| `twin source …` | Show source-trust calibration. |
| `twin export` | Export portable dump of the cognitive store. |

## Runtime

Durable background workers (`twin runtime` / `twin-runtime`) for jobs that must not block Claude Code hooks or the interactive CLI. Handlers call the same cognitive core as MCP/CLI/API — this is not an autonomous agent. When to run the worker and how it fits operating loops in [OPERATIONS.md](OPERATIONS.md).

With Claude Code native hooks, keep a runtime process running so deferred domain resolve and SessionEnd consolidation are processed:

```bash
twin runtime start          # foreground live panel; Ctrl+C to stop
twin runtime start --no-live
# or:
twin-runtime                # same entrypoint (python -m twin.runtime)
```

On an interactive TTY (with `rich` installed), `start` refreshes a panel of queue depth, per-worker in-flight jobs, and recent completed/failed work. Use `--no-live` (or `TWIN_RUNTIME_NO_LIVE=1`) for plain logs; `--json` also skips the panel.

| Command | What it does |
|---|---|
| `twin runtime start` | Run scheduler + worker pool with a live processing panel on a TTY (`--workers`, `--vault`, `--lease`, `--schedule-interval`, `--offline`, `--no-live`) |
| `twin runtime status` | Queue depth, dead-letter count, recent jobs (`--json` for scripts) |
| `twin runtime schedule` | Enqueue due temporal jobs once (daily/weekly/integrity) |
| `twin runtime enqueue <kind>` | Enqueue one job (`--payload-json`, `--idempotency-key`, `--vault`, `--priority`) |
| `twin runtime job <job_id>` | Show one job |
| `twin runtime retry <job_id>` | Requeue a failed or dead-lettered job |
| `twin runtime cancel <job_id>` | Cancel a pending/failed job |

**Job kinds** (`twin runtime enqueue <kind>`):

| Kind | Role |
|---|---|
| `interpret_percept` | Extract one percept (`payload.percept_id`) |
| `workspace_tick` | Parallel-memory tick |
| `attention_evaluate` | Session attention evaluation |
| `consolidate_daily` / `consolidate_weekly` | Consolidation cycle |
| `reembed_memory` | Re-embed one memory |
| `integrity_check` | Store integrity checks |
| `connector_reconcile` | Run due connector syncs |
| `backfill_partition` | Advance one month of a connector historical backfill (`payload.backfill_job_id`) — scheduled while a backfill is in progress; not continuous sync |
| `session_domain_resolve` | Background LLM domain freeze from multi-message dialogue (`payload.binding_id`, optional `cwd`) — enqueued by native UserPromptSubmit when search cannot name a domain |
| `session_complete` | Background session consolidation + extract (`payload.session_id`, optional `summary` / `abandoned` / `summary_origin`) — enqueued by native SessionEnd |

`session_domain_resolve` and `session_complete` are model-gated: when the chat model is unavailable they stay pending/retry and do not burn into the dead letter queue. Manual enqueue examples:

```bash
twin runtime enqueue session_domain_resolve \
  --payload-json '{"binding_id":"hsb_…","session_id":"ses_…"}' \
  --idempotency-key "session_domain_resolve:hsb_…"

twin runtime enqueue session_complete \
  --payload-json '{"session_id":"ses_…","summary":"","abandoned":false,"summary_origin":"assistant"}' \
  --idempotency-key "session_complete:ses_…"

twin runtime status --json
twin runtime job <job_id> --json
```

Without a running runtime, native SessionEnd falls back to in-process `complete_session`; domain stays `unclassified` until a later search vote or an explicit client/MCP domain.

---

---

Quickstart narrative in [README.md](../README.md). Install/config in [SETUP.md](SETUP.md). Ops in [OPERATIONS.md](OPERATIONS.md).
