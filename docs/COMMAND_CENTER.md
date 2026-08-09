# Command Center

Operator TUI for Twin — Sense → Cognize → Inject — launched by bare `twin`
on a TTY.

Non-TTY (`echo | twin`, CI, pipes): prints concise help and exits; never
enters the TUI.

## Screens (MVP)

| Key | Screen | Role |
|---|---|---|
| Home | status | home path, doctor-ish counts, serve/runtime state, backlog, open Reflections |
| `s` | Services | start/stop supervised `twin serve` + `twin runtime`; shows serve URL |
| `c` | Connectors | list Sense connector instances (revoke stays CLI-confirmed) |
| `j` | Jobs | runtime queue depth + enqueue cognize/consolidate |
| `g` | Cognize | LLM halt reason + open reflection count |
| `r` | Review | backlog + open Reflections + workbench URL |
| `n` | Narratives | search/list committed Narratives |
| `t` | Stance | active stances + pending proposals |
| `m` | MCP | client env + setup pointers |
| `/` | Palette | fuzzy over **v2 verbs** (legacy aliases labeled) |

## Exit

`q` prompts: **Yes — stop** supervised children · **Leave running** · **Cancel**.

## Notes

- Does not embed Cognize LLM work in the TUI process — triggers jobs / CLI.
- Primary labels are v2-only (no “Memory” screen title).
- See [CLI.md](CLI.md), [ARCHITECTURE.md](ARCHITECTURE.md).
