[← README](../README.md) · [FOUNDATIONS](FOUNDATIONS.md) · [PRODUCT](PRODUCT.md) · [ARCHITECTURE](ARCHITECTURE.md) · [CONNECTION](CONNECTION.md) · [SETUP](SETUP.md)

# Connection

Twin exposes one cognitive core through three channels. Same store, same firewall, same judgment — different transport.

| Channel | Transport | Best for |
|---|---|---|
| **MCP** | stdio JSON-RPC tools | Agents / IDEs that pull context mid-conversation |
| **CLI** | `twin …` process | Ingest, review, ops, scripting |
| **Local API** | HTTP (+ Review Workbench UI) | Browsers, local integrations, `twin serve` |

Install and models: [SETUP.md](SETUP.md).

---

## Shared concepts (all channels)

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

## MCP

Preferred interface for Cursor, Claude Code, Claude Desktop and other MCP hosts. The client starts `twin mcp` locally; nothing is required to leave the machine.

```bash
twin setup mcp cursor          # or: claude-code | claude-desktop
twin mcp                       # stdio server (what the client runs)
```

Manual entry (absolute `command` path if the GUI cannot see your `PATH`):

```json
{
  "mcpServers": {
    "twin": {
      "command": "twin",
      "args": ["mcp"]
    }
  }
}
```

`twin setup mcp` copies LLM/embed env from `~/.twin/env` into the client `env` block when present.

### How agents should use it

1. Prefer `memory_safe_context_pack` or `session_start` at the beginning of a technical task.
2. Always pass a truthful `target_domain`.
3. Treat `blocked` as authoritative — do not ask the model to “ignore” the firewall.
4. Do not treat `candidate` memories as established fact.
5. Cite memory ids / evidence when using specific claims.
6. Mutating tools require `confirm=true` (and stronger flags for constitutional judgment changes).

### Retrieve

| Tool | Arguments | What it does |
|---|---|---|
| `memory_search` | `query`, `domain="technical"`, `type?`, `limit=10` | Hybrid search (vector + FTS + graph boosts) filtered by domain. |
| `memory_get` | `memory_id` | Single memory with evidence links. |
| `memory_related` | `entity` | Graph neighborhood around an entity name/id. |
| `memory_project_context` | `project_name` | Memories scoped to a project. |
| `memory_recent_decisions` | `project_name?`, `limit=10` | Recent `decision` memories. |
| `memory_user_preferences` | `context=""` | Stable preference memories for the given context string. |
| `memory_judgment_profile` | — | Active judgment items (DB) plus YAML bootstrap view. |

### Context packs & observer

| Tool | Arguments | What it does |
|---|---|---|
| `memory_safe_context_pack` | `query`, `target_domain="technical"`, `max_tokens=1200`, `include_judgment=true`, `include_candidates=false`, `task_profile="general"`, `project?`, `client?` | **Primary agent entry**: compact pack after firewall. Returns allowed memories + blocked reasons. |
| `get_context_pack` | same shape | Lower-level pack builder (prefer `memory_safe_context_pack` in clients). |
| `memory_observe` | `current_text`, `target_domain?` | Parallel “what might be relevant?” suggestion for the current text/task. |

### Sessions

| Tool | Arguments | What it does |
|---|---|---|
| `session_start` | `query`, `client="mcp"`, `client_token?`, `cwd?`, `domain?`, `project?`, `task_profile?`, `max_tokens=1200` | Opens a cognitive session and returns an initial safe pack. |
| `session_observe` | `session_id`, `kind`, `ref?`, `note?`, `percept_id?` | Records an observation on the session (artifact, note, …). |
| `append_session_delta` | `session_id`, `text`, `sequence?`, `external_session_id=""`, `client="mcp"` | Appends a delta of conversation/work text for later interpretation. |
| `get_active_session` | `session_id` | Session snapshot. |
| `get_attention` | `session_id`, `evaluate=false` | Attention / focus hints for the session. |
| `session_complete` | `session_id`, `summary=""`, `abandoned=false`, `summary_origin="assistant"`, `user_confirmed=false` | Closes the session; may enqueue extraction candidates. |
| `session_feedback` | `session_id`, `verdict`, `memory_id?`, `note=""`, `scope?` | Feedback on session usefulness / a memory in context. |
| `provide_feedback` | `emission_id=""`, `session_id=""`, `verdict="useful"`, `memory_id?`, `note=""` | Feedback on a specific emission (pack/suggestion). |

### Review & curation (mutating — need `confirm`)

| Tool | Arguments | What it does |
|---|---|---|
| `review_queue` | `limit=20`, `conflicts_only=false` | Priority-ordered candidates waiting for human review. |
| `review_batch_get` | `batch_id` | Load a review batch. |
| `review_suggest_action` | `memory_id` | Suggest confirm/reject/merge/… **without** mutating. |
| `memory_confirm` | `memory_id`, `confirm=false` | Promote candidate → confirmed. |
| `memory_reject` | `memory_id`, `confirm=false` | Reject a candidate. |
| `memory_archive` | `memory_id`, `confirm=false` | Archive a memory. |
| `memory_merge` | `memory_ids`, `confirm=false`, titles/summaries/scope flags… | Merge memories into one (cross-scope needs extra confirm). |
| `memory_split` | `memory_id`, `parts`, `confirm=false` | Split one memory into parts. |

### Quality & provenance

| Tool | Arguments | What it does |
|---|---|---|
| `memory_quality` | `memory_id` | Quality findings + review priority. |
| `memory_neighbors` | `memory_id` | Nearby memories for side-by-side review. |
| `memory_provenance` | `memory_id` | Chain memory → evidence → percept → artifact. |

### Judgment governance

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

### Privacy

| Tool | Arguments | What it does |
|---|---|---|
| `privacy_evaluate` | `memory_ids?`, `client?`, `client_token?`, `persona="individual"`, `purpose="memory_retrieval"`, `audience="self"` | Evaluate whether content may be disclosed. |
| `privacy_explain` | `decision_id` | Explain a prior privacy decision. |
| `privacy_validate_output` | `text`, `client?`, `client_token?` | Check model output for policy violations. |

### Connectors & meta

| Tool | Arguments | What it does |
|---|---|---|
| `connector_list` | `client?`, `client_token?` | Configured connectors. |
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


## Per-client setup

`twin setup mcp <claude-code|claude-desktop|cursor>` writes/merges the entry for you; `twin doctor` verifies store, models, policies and MCP configs. GUIs do **not** inherit your shell env — put `TWIN_*` in the client `env` block.

### Claude Code

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

### Claude Desktop

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

### Cursor

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

Enable the server in Settings → MCP.

### Other stdio clients

Any MCP stdio-compatible client works with:

```json
{ "command": "twin", "args": ["mcp"] }
```

### How a client should use the tools

#### The session lifecycle (preferred for units of work)

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

#### One-shot context and exploration

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

### Troubleshooting

| symptom | likely cause |
|---|---|
| server does not show up in the client | non-absolute path / `twin` outside the app's PATH |
| `Unsupported TWIN_DB_URL` | missing `env` in the client config |
| empty packs | nothing confirmed yet — run `twin review` or pass `include_candidates=true` |
| weak semantic search | Ollama is down (fell back to the hash embedder) — bring Ollama up and run `twin reindex` |
| Postgres connection error | `docker compose up -d` is not running |

---

## CLI

Terminal / scripting surface. Global flag: `--home` → Twin home (default `~/.twin` or `$TWIN_HOME`).

### Setup & doctors

| Command | What it does |
|---|---|
| `twin init` | Create home, copy defaults, guided LLM/embed setup. |
| `twin init --skip-setup` | Home defaults only (CI / non-interactive). |
| `twin doctor` | Check store, policies, LLM reachability, MCP client configs. |
| `twin setup ollama` | Pull configured Ollama models. |
| `twin setup postgres` | Verify / prepare Postgres + pgvector. |
| `twin setup mcp <client>` | Write/merge MCP server entry (`cursor`, `claude-code`, `claude-desktop`). |

### Ingest → extract → review

| Command | What it does |
|---|---|
| `twin ingest <paths…>` | Run sensors over files/dirs (docs, transcripts, exports). |
| `twin extract` | Interpret pending percepts into memory candidates. |
| `twin extract -A` / `--auto-approve` | Extract and immediately confirm new candidates (skip queue). |
| `twin interpret status\|deferred\|signals` | Cognitive interpretation diagnostics (deferred queue, heuristic signals). |
| `twin review` | Interactive priority review queue. |
| `twin review --analyze` | Run quality analyzer on candidates first. |
| `twin review --priority high` | Filter queue by priority. |
| `twin review --conflicts` | Focus conflicted items. |
| `twin review-batch create\|resume` | Batch review sessions. |
| `twin serve` | Review Workbench UI + local HTTP API (default `http://127.0.0.1:8765`). |

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

### Workspace, runtime, evals

| Command | What it does |
|---|---|
| `twin workspace tick …` | Parallel-memory observation/interpret tick. |
| `twin consolidate daily\|weekly [--apply]` | Consolidation cycle (dry-run by default). |
| `twin runtime start\|status\|enqueue\|…` | Durable cognitive runtime / job queue. |
| `twin eval extraction\|retrieval\|golden\|…` | Benchmarks and completion matrices. |
| `twin source …` | Show source-trust calibration. |
| `twin connector …` | Connector setup, sync, health, contract matrices (see `twin connector -h`). |
| `twin export` | Export portable dump of the cognitive store. |

---

## Local API

`twin serve` mounts a minimal Review Workbench, a JSON API and interactive docs (OpenAPI/Swagger via FastAPI when the `api` extra is installed).

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

Quickstart narrative: [README.md](../README.md). Install/config: [SETUP.md](SETUP.md).
