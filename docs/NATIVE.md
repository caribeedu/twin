# Native

This document explains host-lifecycle binding — Claude Code hooks today;
app-server-style surfaces later.

> Prefer **native** when the host can embed Twin in its session lifecycle.

Shared surface map: [INTERFACES.md](INTERFACES.md). Universal tools:
[MCP.md](MCP.md). CLI commands: [CLI.md — Native](CLI.md#native).
Identity (model-independent continuity): [IDENTITY.md](IDENTITY.md).

Native integration binds the **host application** to Twin’s cognitive sessions without a parallel memory store. Today the shipped proof is **Claude Code hooks**. Deeper host embedding (for example app-server style surfaces) should follow the same rules: one core, fail-open, no silent Memory/Judgment confirmation.

This is **not** a connector. Connectors ingest external systems (repos, Slack, …). Native binds the IDE/agent session you are already in. Both can create Percepts, but through different paths.

## What native can do

| Power | What happens |
|---|---|
| Bind a host session | `session_start` / `pack_request` creates or resumes a `CognitiveSession` and a `HostSessionBinding` |
| Emit a context pack | On **SessionStart** (and explicit `pack_request`), and on the first **UserPromptSubmit** that **search-votes** a previously `unclassified` domain, Twin builds a firewall-filtered pack and prints it on stdout for the host to inject. Hook paths never wait on the local LLM for domain |
| Observe work | User prompts, tool request/completion, and related events are recorded as **session artifacts** (notes on the cognitive session) |
| Form new percepts | On **SessionEnd**, Twin closes the binding immediately and enqueues a background `session_complete` job (`twin-runtime`) that folds **user prompts, assistant replies and deliberate observations** into a **`session_summary` Percept** and extracts candidates. Claude's **Stop** is only end-of-turn and must not close the Twin binding. Native never auto-confirms Memory or Judgment |
| Fail open | With `--fail-open`, Twin failures return `ok=false` + `error_id` and exit 0 so the host is not blocked; diagnostics go to stderr/logs |

Session lifecycle, packs and consolidation in [ARCHITECTURE.md](ARCHITECTURE.md) (sessions / observer) and cognition host binding in-tree (`twin/cognition/host_session.py`). Threat notes in [ARCHITECTURE.md](ARCHITECTURE.md#threat-model).

## How Claude Code hooks work

1. `twin native install` writes a snippet under Twin home **and** merges Twin's `hooks` into `~/.claude/settings.json` (user-global). Prior Twin handlers are replaced; other hooks/settings are kept. Use `--no-merge` for snippet-only, or `--settings <path>` to target another file. A `.twin-bak` backup is written when an existing settings file is patched. `--profile` picks the **observation profile** (see below). `twin native uninstall` removes only Twin-owned handlers (third-party hooks stay); `--restore-backup` restores the most recent `.twin-bak`. Full flag table in [CLI.md → Native](CLI.md#native).
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

## CLI & MCP status

**CLI commands** (`twin native install` / `uninstall` / `bindings` / `event`): [CLI.md → Native](CLI.md#native).

**MCP status tools** (`native_bindings` / `native_session_status`): [MCP.md](MCP.md).

**With Claude Code, prefer native for session start/observe/end.** Keep [MCP](MCP.md) enabled for tools that surface does not cover (search, review, judgment, one-shot packs mid-task, connector ops).

---

Quickstart narrative in [README.md](../README.md). Install/config in [SETUP.md](SETUP.md). Ops in [OPERATIONS.md](OPERATIONS.md).
