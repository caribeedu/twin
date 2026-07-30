[← README](../README.md) · [FOUNDATIONS](FOUNDATIONS.md) · [PRODUCT](PRODUCT.md) · [ROADMAP](ROADMAP.md) · [CHANGELOG](CHANGELOG.md) · [ARCHITECTURE](ARCHITECTURE.md) · [INTERFACES](INTERFACES.md) · [SETUP](SETUP.md) · [OPERATIONS](OPERATIONS.md)

# Interfaces

**Source of truth for:** how tools talk to Twin — Native, MCP, CLI, local API and connectors.

> **Native where possible. MCP everywhere. One cognitive core.**

Twin is infrastructure, not a chat app. LLM-powered **clients** (Cursor, Claude Code, Claude Desktop, …) pull memory and safe context packs from one local core. Prefer **native** when the host can embed Twin in its session lifecycle; use **MCP** as the universal tool surface everywhere else (including mid-conversation pulls). **CLI** and the local **API** are the same core with different transport. **Connectors** are separate: they ingest external sources (GitHub, Slack, …), not client sessions.

Identity and principles in [README](../README.md) and [ARCHITECTURE.md](ARCHITECTURE.md). Install and models in [SETUP.md](SETUP.md). Day-2 ops in [OPERATIONS.md](OPERATIONS.md).

| Surface | Role | Prefer when |
|---|---|---|
| **Native** | Host lifecycle binds to Twin sessions; packs on session start; observations; summary percept on session end | The host offers a native surface (Claude Code hooks today; app-server-style later) |
| **MCP** | Universal tools: packs, search, sessions, review, judgment, connector ops | Every MCP client; also alongside native for mid-task tools |
| **CLI** | Ingest, review, connector ops, scripting | Humans and automation outside an IDE |
| **Local API** | HTTP + review workbench | Browsers and local integrations |

---

## Shared concepts

Most retrieve / pack calls share these ideas:

| Concept | Meaning |
|---|---|
| `target_domain` / `--domain` | Domain the *consumer* is working in (`technical`, `work`, …). Firewall uses this to block cross-domain leaks **before** content reaches the LLM. |
| `query` | Natural-language task or question that drives hybrid search + packing. |
| Memory `status` | `candidate` (unreviewed) vs `confirmed` (trusted). Packs **exclude candidates by default**. |
| `include_candidates` | Explicit opt-in to pack unreviewed items (usually for human review flows, not agents). |
| `max_tokens` | Soft budget for pack size. |
| `confirm=true` / `--confirm` | Required on mutating MCP tools and some CLI paths — dry-run / preview otherwise. |
| Judgment | Separate from memory: principles and trade-offs that shape how tools should decide. |

---

## Clients

Clients are LLM-powered tools that **consume** Twin (packs, search, sessions). They are not [Connectors](#connectors).

| Preference | Surface |
|---|---|
| **1. Native** | When the host can embed Twin in its session lifecycle (Claude Code hooks today; app-server-style later) |
| **2. MCP** | Universal tools for every MCP client; also complements native |

### Native hosts

Native integration binds the **host application** to Twin’s cognitive sessions without a parallel memory store. Today the shipped proof is **Claude Code hooks**. Deeper host embedding (for example app-server style surfaces) should follow the same rules: one core, fail-open, no silent Memory/Judgment confirmation.

This is **not** a connector. Connectors ingest external systems (repos, Slack, …). Native binds the IDE/agent session you are already in. Both can create Percepts, but through different paths.

#### What native can do

| Power | What happens |
|---|---|
| Bind a host session | `session_start` / `pack_request` creates or resumes a `CognitiveSession` and a `HostSessionBinding` |
| Emit a context pack | On **SessionStart** (and explicit `pack_request`), and on the first **UserPromptSubmit** that **search-votes** a previously `unclassified` domain, Twin builds a firewall-filtered pack and prints it on stdout for the host to inject. Hook paths never wait on the local LLM for domain |
| Observe work | User prompts, tool request/completion, and related events are recorded as **session artifacts** (notes on the cognitive session) |
| Form new percepts | On **SessionEnd**, Twin closes the binding immediately and enqueues a background `session_complete` job (`twin-runtime`) that folds **user prompts, assistant replies and deliberate observations** into a **`session_summary` Percept** and extracts candidates. Claude's **Stop** is only end-of-turn and must not close the Twin binding. Native never auto-confirms Memory or Judgment |
| Fail open | With `--fail-open`, Twin failures return `ok=false` + `error_id` and exit 0 so the host is not blocked; diagnostics go to stderr/logs |

Session lifecycle, packs and consolidation in [ARCHITECTURE.md](ARCHITECTURE.md) (sessions / observer) and cognition host binding in-tree (`twin/cognition/host_session.py`). Threat notes in [ARCHITECTURE.md](ARCHITECTURE.md#threat-model).

#### How Claude Code hooks work

1. `twin native install` writes a snippet under Twin home **and** merges Twin's `hooks` into `~/.claude/settings.json` (user-global). Prior Twin handlers are replaced; other hooks/settings are kept. Use `--no-merge` for snippet-only, or `--settings <path>` to target another file. A `.twin-bak` backup is written when an existing settings file is patched. `--profile` picks the **observation profile** (see below). `twin native uninstall` removes only Twin-owned handlers (third-party hooks stay); `--restore-backup` restores the most recent `.twin-bak`.
2. Restart Claude Code (or start a new session). Confirm with `/hooks`.
3. Each hook runs `twin native event --host claude-code --stdin --fail-open`. The event name comes from Claude's stdin JSON (`hook_event_name`).
4. Twin normalizes the event, updates the binding/session, and may emit Claude's `hookSpecificOutput.additionalContext` with a context pack on **SessionStart** (when domain is already known) or on the first **UserPromptSubmit** that **search-votes** a previously `unclassified` domain (hosts may open without semantic input). If search cannot name a domain, Twin enqueues a background `session_domain_resolve` job for multi-message LLM classification — the hook returns immediately. When that job freezes the domain it sets `pending_context_pack`; the **next** injection-capable host event (`user_message`) emits the pack. Background resolve never pushes mid-turn (Claude has no async context push). Other observation hooks stay silent on stdout.

| Claude Code hook | Twin event kind | Typical effect |
|---|---|---|
| `SessionStart` | `session_start` | Bind/start session; **may emit context pack** if domain is known (search vote / explicit) |
| `UserPromptSubmit` | `user_message` | Observe; search-vote upgrade + pack once, else enqueue background domain resolve; emit `pending_context_pack` from a prior background freeze |
| `PostToolUse` | `tool_completed` | Observe (default install) |
| `Stop` | `turn_completed` | End of **agent turn** — structural observe only; binding stays open |
| `SessionEnd` | `session_end` | Close binding; enqueue background **`session_complete`** (summary + extract) |

**Observation profiles** (`twin native install --profile`)

| Profile | Hooks wired | When |
|---|---|---|
| `minimal` | lifecycle only (SessionStart, UserPromptSubmit, Stop, SessionEnd) | lowest noise; no tool observation |
| `standard` (default) | + `PostToolUse` | tool results that changed state |
| `verbose` | + `PreToolUse` | every tool request (noisiest) |

The chosen profile is recorded in the snippet as `twin_native.observation_profile`. Reinstall with a different `--profile` to change coverage.

**Pack assembly deadline.** Pack assembly on the hot path has a wall-clock deadline (SessionStart ≈ 300ms, UserPromptSubmit upgrade+pack ≈ 500ms). Stages of retrieval, privacy screening, and formatting check the deadline and abort early when it is reached. Binding and domain state still persist; the pack is not returned to the host (`pack_skipped_budget`), and Twin marks it pending so the next injection-capable turn (or MCP) can emit it. The deadline is a response-eligibility limit with stage-level abort — not a guarantee that the hook process exits the instant the clock hits zero.

**Runtime degradation**

| State | Behavior |
|---|---|
| Runtime active | Full experience (domain resolve, SessionEnd extract) |
| Runtime stopped briefly | Hooks stay fast; jobs remain pending until workers claim them |
| Store without queue | Limited sync fallback where implemented; otherwise jobs unavailable |
| Runtime down for long | `twin doctor` warns (`runtime:queue` pending, `runtime:dead_letter` failed); observed events are still stored |

Keep `twin-runtime` / `twin runtime start` running for deferred work.

#### Native CLI / MCP status

| Command / tool | What it does |
|---|---|
| `twin native install` | Write Claude Code hooks snippet + merge into `~/.claude/settings.json` (`--profile` / `--no-merge` / `--settings` / `--dir`) |
| `twin native uninstall` | Remove Twin hooks from settings (`--restore-backup` to restore the latest `.twin-bak`) |
| `twin native bindings` | List `HostSessionBinding`s |
| `twin native event` | Ingest a host event (JSON or `--stdin`) |
| MCP `native_bindings` | List native host bindings |
| MCP `native_session_status` | Status of a host-native session link |

**With Claude Code, prefer native for session start/observe/end.** Keep MCP enabled for tools that surface does not cover (search, review, judgment, one-shot packs mid-task, connector ops). Cursor and Claude Desktop remain MCP-first until they expose an equivalent native surface.


### MCP

MCP is the **universal** client interface: any MCP host can pull packs, search, run sessions and call tools — including session notes / observe / complete. Use it when the host has no native surface, and **alongside** native on Claude Code for mid-conversation tools. The client starts `twin mcp` locally; nothing is required to leave the machine.

```bash
twin setup mcp cursor          # or: claude-code | claude-desktop
twin mcp                       # stdio server (what the client runs)
```

`twin setup mcp <client>` registers that host with Twin and writes `TWIN_MCP_CLIENT` / `TWIN_MCP_CLIENT_TOKEN` into the host MCP `env` block. The model **cannot** pass credentials as tool arguments — identity is process-env only.

Manual entry (absolute `command` path if the GUI cannot see your `PATH`):

```json
{
  "mcpServers": {
    "twin": {
      "command": "twin",
      "args": ["mcp"],
      "env": {
        "TWIN_MCP_CLIENT": "cursor",
        "TWIN_MCP_CLIENT_TOKEN": "…from twin setup mcp…"
      }
    }
  }
}
```

`twin setup mcp` also copies LLM/embed env from `~/.twin/env` into the client `env` block when present.

#### How agents should use it

1. Prefer `memory_safe_context_pack` or `session_start` at the beginning of a technical task.
2. Always pass a truthful `target_domain`.
3. Treat `blocked` as authoritative — do not ask the model to “ignore” the firewall.
4. Do not treat `candidate` memories as established fact.
5. Cite memory ids / evidence when using specific claims.
6. Mutating tools require `confirm=true` (and stronger flags for constitutional judgment changes).

#### Retrieve

| Tool | Arguments | What it does |
|---|---|---|
| `memory_search` | `query`, `domain="technical"`, `type?`, `limit=10` | Hybrid search (vector + FTS + graph boosts) filtered by domain. |
| `memory_get` | `memory_id` | Single memory with evidence links. |
| `memory_related` | `entity` | Graph neighborhood around an entity name/id. |
| `memory_project_context` | `project_name` | Memories scoped to a project. |
| `memory_recent_decisions` | `project_name?`, `limit=10` | Recent `decision` memories. |
| `memory_user_preferences` | `context=""` | Stable preference memories for the given context string. |
| `memory_judgment_profile` | — | Active judgment items (DB) plus YAML bootstrap view. |

#### Context packs & observer

| Tool | Arguments | What it does |
|---|---|---|
| `memory_safe_context_pack` | `query`, `target_domain="technical"`, `max_tokens=1200`, `include_judgment=true`, `include_candidates=false`, `task_profile="general"`, `project?` | **Primary agent entry**: compact pack after firewall. Identity from process env only. |
| `get_context_pack` | same shape | Lower-level pack builder (prefer `memory_safe_context_pack` in clients). |
| `memory_observe` | `current_text`, `target_domain?` | Parallel “what might be relevant?” suggestion for the current text/task. |

#### Sessions

| Tool | Arguments | What it does |
|---|---|---|
| `session_start` | `query`, `cwd?`, `domain?`, `project?`, `task_profile?`, `max_tokens=1200` | Opens a cognitive session and returns an initial safe pack. Host identity from env. |
| `session_observe` | `session_id`, `kind`, `ref?`, `note?`, `percept_id?` | Records an observation on the session (artifact, note, …). |
| `append_session_delta` | `session_id`, `text`, `sequence?`, `external_session_id=""`, `client="mcp"` | Appends a delta of conversation/work text for later interpretation. |
| `get_active_session` | `session_id` | Session snapshot. |
| `get_attention` | `session_id`, `evaluate=false` | Attention / focus hints for the session. |
| `session_complete` | `session_id`, `summary=""`, `abandoned=false`, `summary_origin="assistant"`, `user_confirmed=false` | Closes the session; may enqueue extraction candidates. |
| `session_feedback` | `session_id`, `verdict`, `memory_id?`, `note=""`, `scope?` | Feedback on session usefulness / a memory in context. |
| `provide_feedback` | `emission_id=""`, `session_id=""`, `verdict="useful"`, `memory_id?`, `note=""` | Feedback on a specific emission (pack/suggestion). |

#### Review & curation (mutating — need `confirm`)

| Tool | Arguments | What it does |
|---|---|---|
| `review_queue` | `limit=20`, `conflicts_only=false` | Priority-ordered candidates waiting for human review. |
| `review_batch_get` | `batch_id` | Load a review batch. |
| `review_suggest_action` | `memory_id` | Suggest confirm/reject/merge/… **without** mutating. |
| `memory_confirm` | `memory_id`, `confirm=false` | Promote candidate to confirmed. |
| `memory_reject` | `memory_id`, `confirm=false` | Reject a candidate. |
| `memory_archive` | `memory_id`, `confirm=false` | Archive a memory. |
| `memory_merge` | `memory_ids`, `confirm=false`, titles/summaries/scope flags… | Merge memories into one (cross-scope needs extra confirm). |
| `memory_split` | `memory_id`, `parts`, `confirm=false` | Split one memory into parts. |

#### Quality & provenance

| Tool | Arguments | What it does |
|---|---|---|
| `memory_quality` | `memory_id` | Quality findings + review priority. |
| `memory_neighbors` | `memory_id` | Nearby memories for side-by-side review. |
| `memory_provenance` | `memory_id` | Chain memory, evidence, percept, artifact. |

#### Judgment governance

| Tool | Arguments | What it does |
|---|---|---|
| `judgment_applicable` | `domain="technical"`, `task_profile="general"`, `project?`, `query=""` | Judgment items applicable to this context. |
| `judgment_simulate` | `query`, `domain="technical"`, `task_profile="architecture"`, `project?` | Simulate which judgment would fire without writing. |
| `judgment_proposals` | `status="pending"` | List judgment change proposals. |
| `judgment_proposal_preview` | `proposal_id` | Preview + token required for approve. |
| `judgment_proposal_approve` | `proposal_id`, `preview_token`, `confirm=false`, `confirm_constitutional=false` | Human-gated approve. |
| `judgment_proposal_reject` | `proposal_id`, `confirm=false`, `reason=""` | Reject a proposal. |
| `judgment_conflicts` | `status="open"` | Open judgment conflicts. |
| `judgment_version` | — | Current judgment store version metadata. |

#### Privacy

| Tool | Arguments | What it does |
|---|---|---|
| `privacy_evaluate` | `memory_ids?`, `persona="individual"`, `purpose="memory_retrieval"`, `audience="self"` | Evaluate whether content may be disclosed (MCP process identity). |
| `privacy_explain` | `decision_id` | Explain a prior privacy decision. |
| `privacy_validate_output` | `text` | Check model output for policy violations. |

#### Connectors & meta

| Tool | Arguments | What it does |
|---|---|---|
| `connector_list` | — | Configured connectors. |
| `connector_status` | `connector_id`, … | One connector’s sync/health state. |
| `connector_health_all` | … | Health snapshot across connectors. |
| `connector_dead_letters` | `connector_id`, … | Failed items / DLQ. |
| `connector_backfill_preview` | `connector_id`, … | Preview historical backfill (**never** starts ingest). |
| `connector_sync` | `connector_id`, `confirm=false`, `confirm_token?`, … | Trigger sync when confirmed. |
| `capabilities` | — | What this Twin build exposes. |
| `health` | — | Liveness / basic readiness. |
| `native_bindings` | `host_type?`, `limit=50` | Native host bindings (when present). |
| `native_session_status` | `external_session_id`, `host_type="claude-code"` | Status of a host-native session link. |
| `workspace_tick` | `current_text`, `target_domain?`, `session_id=""`, `interpret=false`, … | One parallel-memory workspace tick. |
| `consolidate_cycle` | `kind="daily"`, `apply=false`, `limit=200` | Daily/weekly consolidation (dry-run unless `apply`). |

---

### Per-client setup

`twin setup mcp <claude-code|claude-desktop|cursor>` writes/merges the entry for you; `twin doctor` verifies store, models, policies and MCP configs. GUIs do **not** inherit your shell env — put `TWIN_*` in the client `env` block.

#### Claude Code

```bash
claude mcp add twin -- twin mcp
# project scope (shareable via .mcp.json):
claude mcp add --scope project twin -- twin mcp
```

Or directly in the project's `.mcp.json`:

```json
{
  "mcpServers": {
    "twin": {
      "command": "twin",
      "args": ["mcp"],
      "env": { "TWIN_DB_URL": "postgresql://twin:twin@localhost:5432/twin" }
    }
  }
}
```

#### Claude Desktop

Edit the configuration file:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "twin": {
      "command": "/absolute/path/to/twin",
      "args": ["mcp"],
      "env": { "TWIN_DB_URL": "postgresql://twin:twin@localhost:5432/twin" }
    }
  }
}
```

Use the executable's absolute path (`which twin`) — desktop apps do not
always have your `PATH`. Restart the app after editing.

#### Cursor

`~/.cursor/mcp.json` (global) or `.cursor/mcp.json` at the project root:

```json
{
  "mcpServers": {
    "twin": {
      "command": "twin",
      "args": ["mcp"],
      "env": { "TWIN_DB_URL": "postgresql://twin:twin@localhost:5432/twin" }
    }
  }
}
```

Enable the server in Settings, then MCP.

#### Other stdio clients

Any MCP stdio-compatible client works with:

```json
{ "command": "twin", "args": ["mcp"] }
```

#### How a client should use the tools

##### The session lifecycle (preferred for units of work)

1. **Open work with `session_start`**, passing the task description in
   `query` and the working directory in `cwd` (it helps twin identify the
   project). twin infers project, domain and task profile, returns a
   task-aware context pack and a `session_id`.
   - If the response has `needs_domain_confirmation: true`, twin could not
     classify the domain and supplied **no** context (default-deny). Ask the
     user which domain applies and start again with `domain` set.
   - An explicit `project` that does not exist is an **error** — twin never
     silently substitutes an inferred project for one you named.
2. **Record artifacts with `session_observe`** as the work happens — files
   touched, commits, PRs, decisions made along the way. Appends are atomic:
   concurrent clients never overwrite each other. If the artifact was
   already ingested by a sensor, pass its `percept_id` so it is referenced,
   not duplicated as text.
3. **Close with `session_complete`**, summarizing what was decided, built or
   changed. The summary becomes a percept and goes through extraction, so
   the session's decisions turn into candidate memories the user reviews
   later — the loop that keeps twin's memory alive.
   - Declare `summary_origin` (`assistant` | `user` | `client` | `derived`):
     it sets how much the summary is trusted. Only pass
     `user_confirmed: true` when the human explicitly approved the text.
   - The response carries `consolidation_status`; `failed` means the work
     is closed but extraction failed — call `session_complete` again to
     retry, nothing gets duplicated.
4. **Report usefulness with `session_feedback`** (`useful`,
   `partially_useful`, `irrelevant`, `incorrect`, `missing_context`,
   `privacy_overblock`, `privacy_underblock`), with `scope` = `session`,
   `pack` or `memory`. A `memory_id` must be one this session supplied or
   created. This feeds twin's product metrics — especially "did the user
   have to re-explain something twin should already have known?".

##### One-shot context and exploration

1. **`memory_safe_context_pack`** returns the same pack without opening a
   session: pass the task in `query`, the correct `target_domain`
   (`technical`, `work`, `personal_preferences`, `assistant_preferences`),
   and optionally `task_profile` (`coding`, `architecture`, `debugging`,
   `writing`, `planning`, `review`, `meeting_prep`) and `project` to shape
   it. The pack comes in sections already filtered by the Domain Firewall.
2. By default packs only contain memories **confirmed** by a human. Only
   request `include_candidates=true` when exploring, and never treat a
   `[candidate]` as established fact.
3. **Respect `blocked`**: those are memories withheld by the privacy
   firewall. Do not try to work around it by asking for the content some
   other way.
4. Use `memory_search`/`memory_get` to dig deeper, `memory_related` and
   `memory_project_context` to navigate the graph, `memory_recent_decisions`
   before proposing architecture changes.
5. Cite the `memory_id` when using specific content — every memory has
   traceable verbatim evidence.
6. `memory_observe` is for suggesting context during an ongoing
   conversation; it never answers the user, it only remembers.

##### Troubleshooting

| symptom | likely cause |
|---|---|
| server does not show up in the client | non-absolute path / `twin` outside the app's PATH |
| `Unsupported TWIN_DB_URL` | missing `env` in the client config |
| empty packs | nothing confirmed yet — run `twin review` or pass `include_candidates=true` |
| weak semantic search | Ollama is down (fell back to the hash embedder) — bring Ollama up and run `twin reindex` |
| Postgres connection error | `docker compose up -d` is not running |

---

## CLI

Terminal / scripting surface. Global flag: `--home` sets Twin home (default `~/.twin` or `$TWIN_HOME`).

Add `--json` to any of them to get machine-readable output for scripting and pipes (mirrors `twin pack --json`). The machine protocol surfaces stay unchanged and always speak their own protocol: `twin native event` (JSON on stdout for host hooks, with `--fail-open`), `twin mcp` (MCP over stdio), and `twin serve` (HTTP API).

### Setup & doctors

| Command | What it does |
|---|---|
| `twin init` | Create home, copy defaults, guided LLM/embed setup. |
| `twin init --skip-setup` | Home defaults only (CI / non-interactive). |
| `twin doctor` | Check store, policies, LLM reachability, MCP client configs. |
| `twin setup ollama` | Pull configured Ollama models. |
| `twin setup postgres` | Verify / prepare Postgres + pgvector. |
| `twin setup mcp <client>` | Write/merge MCP server entry (`cursor`, `claude-code`, `claude-desktop`). |

### Ingest, extract, review

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

### Query

| Command | What it does |
|---|---|
| `twin search <query>` | Hybrid search (optional `--domain`). |
| `twin pack <query> --domain <domain>` | Build a safe context pack (candidates off unless flagged). |
| `twin observe <text>` | Memory observer suggestion for current text. |

### Memory lifecycle

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

### Judgment

| Command | What it does |
|---|---|
| `twin promote <mem_id>` | Open a judgment proposal from a memory (does **not** auto-write). |
| `twin judgment import\|export\|list\|show\|history\|versions` | Bootstrap and inspect judgment store. |
| `twin judgment proposals\|propose\|preview\|approve\|reject\|defer` | Proposal lifecycle (approve needs preview token). |
| `twin judgment simulate <query> --domain …` | Simulate applicable judgment. |
| `twin judgment conflicts [--refresh]` | List / refresh conflicts. |
| `twin judgment explain <trace_id>` | Explain a judgment application trace. |

### Workspace, evals, connectors

| Command | What it does |
|---|---|
| `twin workspace tick …` | Parallel-memory observation/interpret tick. |
| `twin consolidate daily\|weekly [--apply]` | Consolidation cycle (dry-run by default). |
| `twin eval extraction\|retrieval\|golden\|…` | Benchmarks and golden work-loop. |
| `twin source …` | Show source-trust calibration. |
| `twin connector …` | Connector setup, sync, health, contract matrices (see `twin connector -h`). |
| `twin export` | Export portable dump of the cognitive store. |

### Runtime

Durable background workers (`twin runtime` / `twin-runtime`) for jobs that must not block Claude Code hooks or the interactive CLI. Handlers call the same cognitive core as MCP/CLI/API — this is not an autonomous agent. Day-2 ops notes in [OPERATIONS.md](OPERATIONS.md).

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

## Connectors

Connectors are **source adapters**, not LLM clients. They pull GitHub, Slack, mail, calendars, meetings and folders into Twin. Client sessions (native / MCP) are documented under [Clients](#clients).

Connectors are how Twin **obtains** ongoing evidence from professional systems. Each adapter fetches and normalizes into the same Artifact-to-Percept path as `twin ingest`. They do **not** confirm Memory or Judgment — you still run `twin extract` and `twin review`.

Ownership (`--source-owner`) and vault labels keep employer and personal data separable. Day-2 ops (due list, DLQ, backup) in [OPERATIONS.md](OPERATIONS.md).

### What each connector extracts

Every connector uses an **allowlist** (repos, channels, labels, folders, calendars, or disk roots) — never “ingest the whole workspace by default.” Attachments are metadata-oriented unless noted. After any sync: `twin extract` then `twin review`.

| Connector | Identifier | Pulls into Twin | Does not pull | Notes |
|---|---|---|---|---|
| **GitHub** | `github` | Issues + issue comments; PRs + reviews + review comments; default-branch commits; releases; CI check **summaries** | Diffs / patches; attachment or blob bytes; non-default-branch commits (except as PR heads); provider deletions | Explicit repo list. Polling is authoritative; optional webhook only marks sync due. Bot-like posts flagged as derived. |
| **Slack** | `slack` | Channel history: messages and thread replies (text, edits, deletion tombstones). File **names / mime / size / permalink** as refs | File **bytes**. Whole-workspace scrape | Channel allow-list. DMs and private channels off unless you opt in. High leakage risk — set ownership/vault honestly. |
| **Gmail** | `gmail` | Messages under chosen labels: subject, From/To/Cc, authored body (quotes/signatures split), snippet, label membership | Attachment **bodies** (metadata refs only by default). Spam/promotions unless you include those labels | OAuth read-only. HTML kept as an untrusted stub, not safe UI HTML. |
| **Outlook** | `outlook` | Same mail cognitive model as Gmail, via Microsoft Graph folders you choose | Attachment bodies (same metadata rule). Write scopes | Folder discovery before sync. Delta sync; removals become tombstones. |
| **Google Calendar** | `calendar` | Events on chosen calendars: title, when, status, location, organizer, attendees, description (capped) | Attachments. In **free/busy** mode: no title, attendees, or description — busy windows only | Correlate later with meeting transcripts when ids / links match. Match vault to personal vs work. |
| **Fireflies** | `fireflies` | Meeting **manifest**, speaker-labeled **transcript chunks**, optional provider **summary** | Audio / video bytes; signed media URLs (flags only that media existed) | Chunks never split mid-utterance. Summary marked derived. Still extract + human review; PII policies apply. |
| **Local folder** | `folder` | Watched roots: text docs (default `md` / `txt` / `rst`, …) as manifest + revision **chunks**; deletes as tombstones | Binary file bodies; absolute paths in the cognitive payload | Content-hash skips unchanged files. Oversized / unsupported files stay metadata-only. No auth — path access is the trust boundary. |

Shared CLI and per-type setup follow. Discovery helpers (`twin connector github repositories`, `slack channels`, …) list what you can put on the allowlist **before** you widen sync.

### Shared CLI

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

MCP mirrors (capability-gated; mutating tools need confirm): `connector_list`, `connector_status`, `connector_health_all`, `connector_sync`, `connector_backfill_preview`, `connector_dead_letters` — see [Connectors & meta](#connectors--meta) above. HTTP: `/api/connectors…` and optional webhooks below.

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
| Extract candidates | `twin extract` |
| Human review | `twin review` |
| Scheduler | `twin connector due` then `twin connector sync-due` |

---

## Local API

`twin serve` mounts a minimal review workbench, a JSON API and interactive docs (OpenAPI/Swagger via FastAPI when the `api` extra is installed).

Base: `http://127.0.0.1:8765` (unless configured otherwise).

### Ingest & extract

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/ingest` | Ingest artifacts / paths into percepts. |
| `POST` | `/api/extract` | Run extraction on pending percepts. |
| `GET` | `/api/percepts` | List/inspect percepts. |
| `GET` | `/api/artifacts/{id}` | Fetch an artifact record. |

### Memories & review

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/memories` | List / filter memories. |
| `POST` | `/api/memories/{id}/review` | Submit a review decision. |
| `POST` | `/api/memories/{id}/promote` | Propose promotion into judgment. |
| `POST` | `/api/memories/{id}/supersede/{old_id}` | Supersede relation. |
| `POST` | `/api/memories/{id}/contradict/{other_id}` | Contradiction relation. |
| `GET` | `/api/memories/{id}/neighbors` | Neighborhood for review. |
| `GET` | `/api/memories/{id}/quality` | Quality report. |
| `GET` | `/api/memories/{id}/provenance` | Provenance chain. |
| `POST` | `/api/memories/{id}/split` | Split memory. |
| `POST` | `/api/memories/{id}/archive` | Archive memory. |
| `POST` | `/api/memories/merge` | Merge memories. |
| `GET` | `/api/review/queue` | Review queue. |
| `GET`/`POST` | `/api/review/batches` | Review batches. |

### Search, packs, observer

| Method | Path | What it does |
|---|---|---|
| `GET`/`POST` | `/api/search` | Hybrid search. |
| `POST` | `/api/context_pack` | Safe context pack (firewall applied). |
| `POST` | `/api/observer` | Memory observer over current text. |

### Judgment

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/judgment` | Judgment overview. |
| `GET` | `/api/judgment/items` | Judgment items. |
| `GET` | `/api/judgment/versions` | Version history. |
| `GET`/`POST` | `/api/judgment/proposals` | List / create proposals. |
| `POST` | `/api/judgment/proposals/generate` | Generate proposals from signals. |
| `POST` | `/api/judgment/proposals/{id}/preview` | Preview + token. |
| `POST` | `/api/judgment/proposals/{id}/approve` | Approve (token + confirm). |
| `POST` | `/api/judgment/proposals/{id}/reject` | Reject. |
| `POST` | `/api/judgment/import` | Import YAML bootstrap into store. |
| `POST` | `/api/judgment/applicable` | Applicable pack for a context. |
| `POST` | `/api/judgment/simulate` | Simulate application. |
| `GET` | `/api/judgment/conflicts` | Conflicts. |

### Evals, metrics, export

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/evals/extraction` | Run extraction eval. |
| `POST` | `/api/evals/retrieval` | Run retrieval eval. |
| `GET` | `/api/metrics` | Store / connector metrics. |
| `GET`/`POST` | `/api/export` | Export portable data. |

---

Quickstart narrative in [README.md](../README.md). Install/config in [SETUP.md](SETUP.md). Ops in [OPERATIONS.md](OPERATIONS.md).
