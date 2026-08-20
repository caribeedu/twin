# Command Center

Operator TUI for Twin process supervision — launched by bare `twin` on a TTY.

Non-TTY (`echo | twin`, CI, pipes): prints concise help and exits; never
enters the TUI.

Cognition browse, review, jobs, and inject live in the
[Web Command Center](WEB_CENTER.md) (`twin serve`) and scripted CLI — not
in this TUI.

## Single screen

One layout — no bottom bar, no screen switching:

| Region | Role |
|---|---|
| **Health** | Doctor summary + checks in one section (LLM / extractor / embedder / home + warnings) |
| **Services** | Start/stop supervised **web** (`twin serve`) and `twin runtime`; logs — controls inside the Services box |
| **MCP** (right rail) | Per-provider install status (Cursor / Claude Code / Claude Desktop) + preferred tools |

`q` quits (prompt: **Yes — stop** supervised children · **Leave running** · **Cancel**).

## Notes

- On launch, auto-starts supervised `twin serve` and `twin runtime` when they
  are not already running (port listen / existing worker). Existing processes
  are left alone (attached for status).
- Does not embed Cognize LLM work in the TUI process.
- See [CLI.md](CLI.md), [WEB_CENTER.md](WEB_CENTER.md), [ARCHITECTURE.md](ARCHITECTURE.md).
