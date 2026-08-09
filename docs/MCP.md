# MCP

This document explains the universal tool surface — packs, search,
sessions, review, judgment and connector ops over stdio.

> **MCP everywhere.** Use it when the host has no native surface, and
> alongside [native](NATIVE.md) for mid-conversation tools.

Surface map: [INTERFACES.md](INTERFACES.md). Host lifecycle:
[NATIVE.md](NATIVE.md). Governed context and privacy-before-reasoning:
[GLOSSARY.md](GLOSSARY.md) ·
[IDENTITY.md](IDENTITY.md#design-principles).

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

## How agents should use it

1. Prefer `inject_context_pack` or `session_start` at the beginning of a technical task.
2. Always pass a truthful `target_domain`.
3. Treat `blocked` as authoritative — do not ask the model to “ignore” the firewall.
4. Do not treat `candidate` memories as established fact.
5. Cite memory ids / evidence when using specific claims.
6. Mutating tools require `confirm=true` (and stronger flags for constitutional judgment changes).

## Retrieve

| Tool | Arguments | What it does |
|---|---|---|
| `memory_search` | `query`, `domain="technical"`, `type?`, `limit=10` | Hybrid search (vector + FTS + graph boosts) filtered by domain. |
| `memory_get` | `memory_id` | Single memory with evidence links. |
| `memory_related` | `entity` | Graph neighborhood around an entity name/id. |
| `memory_project_context` | `project_name` | Memories scoped to a project. |
| `memory_recent_decisions` | `project_name?`, `limit=10` | Recent `decision` memories. |
| `memory_user_preferences` | `context=""` | Stable preference memories for the given context string. |
| `memory_judgment_profile` | — | Active judgment items (DB) plus YAML bootstrap view. |

## Context packs & observer

| Tool | Arguments | What it does |
|---|---|---|
| `narrative_list` | `vault?`, `domain?` | Committed Narratives + EpistemicState status |
| `narrative_show` | `narrative_id` | One Narrative + EpistemicState |
| `stance_list` | — | Active Stances |
| `stance_proposals` | `status=pending` | Pending Stance drafts (human approve) |
| `inject_context_pack` | same shape as legacy pack | **Preferred**: EpistemicState, open reflections, derived confidence/independence, applicable stance. |
| `memory_safe_context_pack` | `query`, `target_domain="technical`, … | **Legacy** alias — response includes `deprecated`; prefer `inject_context_pack`. |
| `get_context_pack` | same shape | Lower-level pack builder (prefer `inject_context_pack`). |
| `memory_observe` | `current_text`, `target_domain?` | Parallel “what might be relevant?” suggestion for the current text/task. |

## Sessions

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

## Review & curation (mutating — need `confirm`)

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

## Quality & provenance

| Tool | Arguments | What it does |
|---|---|---|
| `memory_quality` | `memory_id` | Quality findings + review priority. |
| `memory_neighbors` | `memory_id` | Nearby memories for side-by-side review. |
| `memory_provenance` | `memory_id` | Chain memory, evidence, percept, artifact. |

## Judgment governance

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

## Privacy

| Tool | Arguments | What it does |
|---|---|---|
| `privacy_evaluate` | `memory_ids?`, `persona="individual"`, `purpose="memory_retrieval"`, `audience="self"` | Evaluate whether content may be disclosed (MCP process identity). |
| `privacy_explain` | `decision_id` | Explain a prior privacy decision. |
| `privacy_validate_output` | `text` | Check model output for policy violations. |

## Connectors & meta

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

Enable the server in Settings, then MCP.

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

#### Troubleshooting

| symptom | likely cause |
|---|---|
| server does not show up in the client | non-absolute path / `twin` outside the app's PATH |
| `Unsupported TWIN_DB_URL` | missing `env` in the client config |
| empty packs | nothing confirmed yet — run `twin review` or pass `include_candidates=true` |
| weak semantic search | Ollama is down (fell back to the hash embedder) — bring Ollama up and run `twin reindex` |
| Postgres connection error | `docker compose up -d` is not running |

---

---

Quickstart narrative in [README.md](../README.md). Install/config in [SETUP.md](SETUP.md). Ops in [OPERATIONS.md](OPERATIONS.md).
