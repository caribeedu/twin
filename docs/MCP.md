# MCP

This document explains the universal tool surface — packs, search,
sessions, review, Stance and connector ops over stdio.

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
4. Prefer `narrative_*` / `stance_*` tools for durable substrate; use `claim_*` for store claim rows.
5. Cite Narrative / Evidence ids when using specific claims.
6. Mutating tools require `confirm=true` (and stronger flags for constitutional Stance changes).

## Prefer (v2 substrate)

| Tool | Arguments | What it does |
|---|---|---|
| `narrative_list` | `vault?`, `domain?` | Committed Narratives + EpistemicState status |
| `narrative_show` | `narrative_id` | One Narrative + EpistemicState |
| `stance_list` | — | Active Stances |
| `stance_proposals` | `status=pending` | Pending Stance drafts (human approve) |
| `stance_applicable` | `domain`, `task_profile`, … | Stance items applicable to this context |
| `stance_simulate` | `query`, `domain`, … | Simulate Stance influence without writing |
| `stance_profile` | — | Active Stance items + YAML bootstrap |
| `stance_proposal_preview` / `_approve` / `_reject` | … | Human-gated Stance mutations |
| `stance_conflicts` / `stance_version` | … | Conflicts and version metadata |
| `inject_context_pack` | `query`, `target_domain="technical"`, … | EpistemicState, open reflections, derived confidence/independence, applicable Stance |

## Retrieve (store claims)

| Tool | Arguments | What it does |
|---|---|---|
| `claim_search` | `query`, `domain="technical"`, `type?`, `limit=10` | Hybrid search (vector + FTS + graph boosts) filtered by domain. |
| `claim_get` | `claim_id` | Single store claim with evidence links. |
| `claim_related` | `entity` | Graph neighborhood around an entity name/id. |
| `claim_project_context` | `project_name` | Claims scoped to a project. |
| `claim_recent_decisions` | `project_name?`, `limit=10` | Recent `decision` claims. |
| `claim_user_preferences` | `context=""` | Stable preference claims for the given context string. |
| `claim_quality` | `claim_id` | Quality analysis (duplicates, conflicts, review priority). |
| `claim_neighbors` | `claim_id` | Semantically/entity-related neighbor claims. |
| `claim_provenance` | `claim_id` | Lineage: claim → evidence → percept → artifact. |
| `claim_confirm` / `claim_reject` / `claim_archive` | `claim_id`, `confirm=false` | Curation mutations (require `confirm=true`). |
| `claim_merge` / `claim_split` | … | Merge/split claims (require `confirm=true`). |

## Context packs

| Tool | Arguments | What it does |
|---|---|---|
| `inject_context_pack` | `query`, `target_domain="technical"`, … | Same as Prefer table — primary Inject tool. |

## Sessions

| Tool | Arguments | What it does |
|---|---|---|
| `session_start` | `query`, `cwd?`, `domain?`, `project?`, `task_profile?`, `max_tokens=1200` | Opens a cognitive session and returns an initial safe pack. Host identity from env. |
| `session_observe` | `session_id`, `kind`, `ref?`, `note?`, `percept_id?` | Records an observation on the session (artifact, note, …). |
| `append_session_delta` | `session_id`, `text`, `sequence?`, `external_session_id=""`, `client="mcp"` | Appends a delta of conversation/work text for later interpretation. |
| `get_active_session` | `session_id` | Session snapshot. |
| `get_attention` | `session_id`, `evaluate=false` | Attention / focus hints for the session. |
| `session_complete` | `session_id`, `summary=""`, `abandoned=false`, `summary_origin="assistant"`, `user_confirmed=false` | Closes the session; may enqueue extraction candidates. |
| `session_feedback` | `session_id`, `verdict`, `claim_id?`, `note=""`, `scope?` | Feedback on session usefulness / a claim in context. |
| `provide_feedback` | `emission_id=""`, `session_id=""`, `verdict="useful"`, `claim_id?`, `note=""` | Feedback on a specific emission (pack/suggestion). |

## Review & curation (mutating — need `confirm`)

| Tool | Arguments | What it does |
|---|---|---|
| `review_queue` | `limit=20`, `conflicts_only=false` | Priority-ordered candidates waiting for human review. |
| `review_batch_get` | `batch_id` | Load a review batch. |
| `review_suggest_action` | `claim_id` | Suggest confirm/reject/merge/… **without** mutating. |
| `claim_confirm` | `claim_id`, `confirm=false` | Confirm a candidate claim. |
| `claim_reject` | `claim_id`, `confirm=false` | Reject a candidate claim. |
| `claim_archive` | `claim_id`, `confirm=false` | Archive a claim. |
| `claim_merge` | `claim_ids`, `confirm=false`, titles/summaries/scope flags… | Merge claims. |
| `claim_split` | `claim_id`, `parts`, `confirm=false` | Split a claim. |

## Quality & provenance

| Tool | Arguments | What it does |
|---|---|---|
| `claim_quality` | `claim_id` | Quality findings + review priority. |
| `claim_neighbors` | `claim_id` | Nearby claims for side-by-side review. |
| `claim_provenance` | `claim_id` | Chain claim, evidence, percept, artifact. |

## Stance governance

| Tool | Arguments | What it does |
|---|---|---|
| `stance_applicable` | `domain="technical"`, `task_profile="general"`, `project?`, `query=""` | Stance items applicable to this context. |
| `stance_simulate` | `query`, `domain="technical"`, `task_profile="architecture"`, `project?` | Simulate which Stance would fire without writing. |
| `stance_proposals` | `status="pending"` | List Stance change proposals. |
| `stance_proposal_preview` | `proposal_id` | Preview + token required for approve. |
| `stance_proposal_approve` | `proposal_id`, `preview_token`, `confirm=false`, `confirm_constitutional=false` | Human-gated approve. |
| `stance_proposal_reject` | `proposal_id`, `confirm=false`, `reason=""` | Reject a proposal. |
| `stance_conflicts` | `status="open"` | Open Stance conflicts. |
| `stance_version` | — | Current Stance store version metadata. |
| `stance_profile` | — | Active Stance items + YAML bootstrap. |

## Privacy

| Tool | Arguments | What it does |
|---|---|---|
| `privacy_evaluate` | `claim_ids?`, `persona="individual"`, `purpose="memory_retrieval"`, `audience="self"` | Evaluate whether content may be disclosed (MCP process identity). |
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
   `pack` or `memory`. A `claim_id` must be one this session supplied or
   created. This feeds twin's product metrics — especially "did the user
   have to re-explain something twin should already have known?".

#### One-shot context and exploration

1. **`inject_context_pack`** returns a governed pack without opening a
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
5. Cite the `claim_id` when using specific content — every memory has
   traceable verbatim evidence.

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
