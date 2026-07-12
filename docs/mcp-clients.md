# Integrating `twin` with MCP clients

`twin` exposes memory over MCP via stdio: the client starts the `twin mcp`
process and talks to it locally. Nothing leaves the machine.

Prerequisite: `pip install -e ".[mcp]"` (or `.[dev]`) in a Python the client
can reach, and `twin init` already executed. If you use Postgres/Ollama, make
sure `docker compose up -d` is running before opening the client.

The quickest path is `twin setup mcp <claude-code|claude-desktop|cursor>`,
which writes/merges the entry into the client's config for you, and
`twin doctor`, which verifies the whole installation (store, models,
policies, MCP configs). The sections below show the manual equivalent.

> General tip: environment variables (`TWIN_DB_URL`, `TWIN_OLLAMA_URL`, …)
> must go in the client configuration's `env` block — GUIs like Claude
> Desktop do not inherit your shell environment.

## Claude Code

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

## Claude Desktop

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

## Cursor

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

## Other stdio clients

Any MCP stdio-compatible client works with:

```json
{ "command": "twin", "args": ["mcp"] }
```

## How a client should use the tools

### The session lifecycle (preferred for units of work)

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

### One-shot context and exploration

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

## Troubleshooting

| symptom | likely cause |
|---|---|
| server does not show up in the client | non-absolute path / `twin` outside the app's PATH |
| `Unsupported TWIN_DB_URL` | missing `env` in the client config |
| empty packs | nothing confirmed yet — run `twin review` or pass `include_candidates=true` |
| weak semantic search | Ollama is down (fell back to the hash embedder) — bring Ollama up and run `twin reindex` |
| Postgres connection error | `docker compose up -d` is not running |
