# Command Center

Operator TUI for Twin — Sense → Cognize → Inject — launched by bare `twin`
on a TTY.

Non-TTY (`echo | twin`, CI, pipes): prints concise help and exits; never
enters the TUI.

## Screens (MVP)

| Key | Screen | Role |
|---|---|---|
| Home | status | doctor summary, serve/runtime state, backlog, open Reflections |
| `s` | Services | start/stop supervised `twin serve` + `twin runtime`; shows serve URL |
| `c` | Connectors | list + **test / pause / resume** (revoke stays CLI-confirmed) |
| `j` | Jobs | queue depth; enqueue `cognize_batch` / `consolidate_daily` / `backfill_partition`; backfill progress |
| `g` | Cognize | halt reason + open reflections; **Run cognize** via shared handler |
| `r` | Review | backlog + open Reflections + Fade recommendations + workbench URL |
| `n` | Narratives | list with epistemic status / grain |
| `t` | Stance | list + approve pending proposal (preview token) |
| `m` | MCP | client env + narrative/stance tool names |
| `/` | Palette | fuzzy over **v2 verbs** (legacy aliases labeled) |

Screens call `twin.interfaces.center.actions` — same store/CLI functions, no duplicated logic.

## Exit

`q` prompts: **Yes — stop** supervised children · **Leave running** · **Cancel**.

## Notes

- Does not embed Cognize LLM work in the TUI process — triggers jobs / CLI.
- Primary labels are v2-only (no “Memory” screen title).
- See [CLI.md](CLI.md), [ARCHITECTURE.md](ARCHITECTURE.md).
