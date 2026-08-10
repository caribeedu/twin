# Operations

This document explains **how to operate Twin** end-to-end — from a fresh
install through the [README demonstration](../README.md#demonstration)
to day-to-day sync, native sessions, review and recovery.

**Invariants while you operate:**

- Connectors and Cognize produce **candidates**. Humans confirm Narratives.
- Stance is always human-gated (`twin stance approve`).
- Episode semantic stages **defer** when the chat model is down — they
  never invent an arc from lexical rules.

---

## 0. Prerequisites

Install Twin, run the first-run wizard and verify with `twin doctor` in
[SETUP.md](SETUP.md). Return here when the home is ready.

---

## 1. Reproduce the demonstration

Match the behavior in [README — Demonstration](../README.md#demonstration)
— a fresh Claude chat that narrates a launch-blocker arc from Slack +
GitHub **without** re-briefing, because Twin already formed understanding.

Source systems in that demo: **Slack** + **GitHub** on
[`caribeedu/dogwalker`](https://github.com/caribeedu/dogwalker). The host
reasoning model in the video is Claude; Twin’s own Cognize model
is whatever you chose in `twin init` (cloud frontier helps quality —
[README — Runtime Philosophy](../README.md#runtime-philosophy)).

Keep a runtime worker up for backfill and native SessionEnd work. Wire the
client you will use (Claude Code is the reference native host; MCP works
everywhere). Lifecycle detail in [NATIVE.md](NATIVE.md); MCP map in
[MCP.md](MCP.md).

```bash
# terminal A — leave running
twin runtime start                    # live panel on TTY; --no-live to disable

# terminal B
twin setup mcp claude-code            # or: cursor | claude-desktop
twin native install                   # Claude Code hooks
# optional: twin native install --profile standard
```

### 1.1 Register GitHub

```bash
# Plan only — never ingests
twin connector setup github --source-owner opensource

# Register (PAT with repo read on the allowlisted repos)
twin connector add github \
  --source-owner opensource \
  --secret "$GITHUB_TOKEN" \
  --config '{"repositories":["caribeedu/dogwalker"]}'

twin connector list
twin connector auth <github_connector_id>
twin connector github repositories <github_connector_id>
twin connector github repositories <github_connector_id> --select <repo-name>
```

`--source-owner` picks vault/ownership semantics — see
[INTERFACES.md — Connectors](INTERFACES.md#connectors). Use `employer` /
`personal` when the data is not opensource.

### 1.2 Register Slack

You need a bot token that can read the **allowlisted** channels where the
Feature A thread lives (never whole-workspace scrape).

```bash
twin connector setup slack --source-owner personal   # or employer

twin connector add slack \
  --source-owner personal \
  --secret "$SLACK_BOT_TOKEN" \
  --config '{"channels":["C_YOUR_CHANNEL_ID"]}'

twin connector auth <slack_connector_id>
twin connector slack channels <slack_connector_id>
twin connector slack channels <slack_connector_id> --select <channel-id>
```

Channel allow-list details and DM/private flags: [CLI.md — Slack](CLI.md#slack).

### 1.3 Ingest history

Continuous sync pulls recent windows. For a demo that needs the full arc,
prefer **backfill** (requires `twin runtime start`):

```bash
twin connector backfill --preview <github_connector_id>
twin connector backfill --create <github_connector_id>
twin connector backfill --run

twin connector backfill --preview <slack_connector_id>
twin connector backfill --create <slack_connector_id>
twin connector backfill --run
```

Or, for a lighter pass:

```bash
twin connector sync <github_connector_id>
twin connector sync <slack_connector_id>
```

`preview` / `create` never start ingest by themselves. Scheduler helpers: `twin connector due` /
`twin connector sync-due` ([CLI.md](CLI.md#connectors)).

### 1.4 Form understanding

```bash
# Cognize pending percepts (candidates only; never auto-commits Narrative)
twin cognize run

# Optional: review candidates before further Cognize work
twin review
# or UI: twin serve   → http://127.0.0.1:8765

# Re-run Cognize after review / more evidence
twin cognize run
```

What Cognize runs in [ARCHITECTURE — CLI stages](ARCHITECTURE.md#brain-analogies-and-cli-stages).
Stage-by-stage alternative in [§ Cognize and episodes](#4-cognize-and-episodes).

```bash
# Confirm trajectory / remaining candidates
twin review
# or UI: twin serve   → http://127.0.0.1:8765

# Inspect what Cognize built
twin episode list
twin episode show <episode_id>
```

Prefer `twin review` and `twin narrative commit` over auto-confirm paths —
Stance stays human-gated either way.

### 1.5 Ask in a fresh conversation

With MCP + native hooks installed:

1. Start a **new** Claude Code session (no project memory, no manual brief).
2. Ensure `twin runtime start` is still running (SessionEnd consolidation).
3. Ask something like: *“What happened with Feature A / the Dogwalker launch blocker?”*

Twin injects a governed pack on session start / first domain vote — see
[NATIVE.md](NATIVE.md). You can also pull a pack yourself:

```bash
twin pack "Dogwalker Feature A launch blocker" --domain technical
twin search "Feature A launch" --domain technical
```

Expect a **synthesized narrative**, not a dump of
unrelated Slack/GitHub hits. That is the point of the demonstration.

---

## 2. Local files only (no Slack/GitHub)

Use when you want Twin without professional connectors — docs, transcripts,
meeting JSON under `examples/`:

```bash
twin ingest examples/docs examples/transcripts examples/meetings
twin cognize run
twin review
twin pack "What was decided about webhooks?" --domain technical
```

Sensors turn files into percepts; Cognize still creates candidates only.
Same human gates as above.

---

## 3. Day-to-day after the first full pass

Once the demo (or any corpus) is loaded:

```bash
# terminal A
twin runtime start

# terminal B — after new activity in sources
twin connector sync-due                 # or: twin connector sync <id>
twin cognize run
twin review
```

Re-run `twin cognize run` as a **correctness oracle** after
schema/logic changes or when you suspect drift — not on every sync.
Details: [CLI.md — Correlation](CLI.md#correlation--episode-cognition).

Scheduled consolidation (also needs runtime):

```bash
twin consolidate daily                  # dry-run by default
twin consolidate daily --apply
twin consolidate weekly --apply         # + Stance drafts from patterns
```

---

## 4. Cognize and episodes

Happy path is `twin cognize run` (already used above). Stage-by-stage:

```bash
twin cognize run                        # Sense→Cognize; builds arcs when evidence allows
twin episode list                       # consolidate=ready ⇒ ≥2 phases
twin episode reflect <episode_id>       # trajectory MemoryCandidates
twin episode reflect <episode_id> --dry-run
twin review
twin stance propose-episode <episode_id>   # after trajectory memories confirmed
twin stance preview <proposal_id>
# twin stance approve …                 # human only
```

| Signal | Meaning |
|---|---|
| Stage **deferred** | Chat model unreachable — start/fix provider, re-run. Prior phases/edges kept. |
| `extractor=heuristic` | Semantic episode stages blocked on purpose. |
| Atomic review ≠ trajectory review | Cognize candidates and reflect candidates are separate queues. |

---

## 5. Native session loop (Claude Code)

```bash
twin runtime start                      # required for domain resolve + SessionEnd
twin native install --profile standard
# work in Claude as usual…
twin native bindings                    # inspect open bindings
```

| Host event | Twin effect |
|---|---|
| SessionStart | Bind session; may inject pack if domain known |
| UserPromptSubmit | Observe; search-vote domain; may inject pack |
| PostToolUse / Stop | Observe (Stop ≠ end of Twin session) |
| SessionEnd | Close binding; enqueue `session_complete` → summary percept → Cognize candidates |

Fail-open and deadlines: [NATIVE.md](NATIVE.md). Prefer native for
lifecycle; keep MCP for mid-task tools (search, review, connectors).

---

## 6. Review workbench and packs

```bash
twin review                             # interactive CLI queue
twin serve                              # UI + API at http://127.0.0.1:8765
twin pack "<question>" --domain technical
twin search "<query>" --domain technical
twin observe "draft text…"              # Memory Observer suggestion
```

Packs apply the domain firewall **before** content reaches the LLM —
[ARCHITECTURE.md](ARCHITECTURE.md) · [INTERFACES.md](INTERFACES.md).

---

## 7. Health, runtime jobs, connectors recovery

```bash
twin doctor
twin runtime status                     # pending / failed / dead-letter
twin runtime job <job_id>
twin runtime retry <job_id>
twin runtime cancel <job_id>

twin connector due
twin connector sync-due
twin connector dead-letters <connector_id>
twin connector replay <dead_letter_id>
twin connector production-ready
```

`twin doctor` reads queue depth from the store (it does not claim a worker
PID is up). Job kinds and payloads: [CLI.md — Runtime](CLI.md#runtime).

`model_unavailable` on model-gated jobs must stay retryable — never treat
as a permanent dead letter.

---

## 8. Backup, export, incidents

```bash
twin backup create ./backup-dir
twin backup validate ./backup-dir
twin backup restore ./backup-dir ./restored.db
twin export                             # portable JSON dump
```

Validate before restore. Point `$TWIN_HOME` / `TWIN_DB_URL` at a restored
DB only after you intend to switch.

**Suspected prompt injection in sources:**

1. Reject / quarantine affected candidates (`twin review`).
2. Confirm packs show blocks, not leaked content (`twin pack` / UI).
3. Rotate any secrets that appeared in source text.
4. Re-check integrity (`twin serve` → cognition health, or runtime
   `integrity_check`).

---

## 9. Release smoke (maintainers)

```bash
twin eval golden
twin connector production-ready
pytest -q
```

---

Install in [SETUP.md](SETUP.md). Interfaces in [INTERFACES.md](INTERFACES.md). Overview in [README](../README.md).

Prefer `twin cognize run`, `twin narrative …`, `twin stance …`, `twin inject pack`.
On a TTY, bare `twin` opens the [Command Center](COMMAND_CENTER.md).
Web visibility of every Cognize entity: [WEB_CENTER.md](WEB_CENTER.md)
(`twin serve` → `/`).

