# Setup

This document explains how you **install** Twin and complete the
**first-run wizard** — packages, LLM/embedding providers, configuration
and tests.

How to operate Twin after install (demo scenario, connectors, Cognize,
native, backup): [OPERATIONS.md](OPERATIONS.md). Surfaces:
[INTERFACES.md](INTERFACES.md). Why Twin exists:
[README](../README.md). Local vs cloud reasoning:
[README — Runtime Philosophy](../README.md#runtime-philosophy).

## Installation

PyPI project name is **`twin-cognition`**. The import and CLI stay
**`twin`** (`import twin`, commands `twin` / `twin-runtime`).

```bash
pip install "twin-cognition[api,mcp,postgres,crypto]"
```

Extras: `api` (HTTP UI), `mcp` (MCP server), `postgres` (pgvector store),
`crypto` (at-rest encryption). Omit extras you do not need.

Optional: install [Ollama](https://ollama.com/download) if you want the
recommended local chat with embed path.

### Development from source

```bash
git clone https://github.com/caribeedu/twin.git
cd twin
pip install -e ".[dev]"        # api + mcp + postgres + crypto + tests
# or granular:
pip install -e ".[api,mcp,postgres,crypto]"
```

## First-run wizard (`twin init`)

`twin init` is required before anything else. Until it runs there is no
home directory and no store.

```bash
twin init                 # interactive wizard (TTY)
twin init --skip-setup    # CI / scripts: create home defaults only
```

On a TTY the wizard is a **guided Rich UI** (panels, key chooser, yes/no
prompts). It:

1. Creates `$TWIN_HOME` (default `~/.twin`).
2. Copies default `policies.yaml`, `judgment.yaml` and source calibration.
3. Asks which **chat LLM** to use for Cognize / observer / episode
   cognition, then configures **embeddings**.
4. Writes `~/.twin/env` (loaded by every later Twin process).

### Provider menu

| Key | Choice | Notes |
|---|---|---|
| `1` | **Ollama** (recommended) | Local open models. Prompts for URL, lists local tags, picks chat + embed models. |
| `2` | **OpenAI-compatible** | Base URL, API key, chat model, embed model. Presets via env: `groq`, `openrouter`, `lmstudio`, `vllm`, … |
| `3` | **Anthropic (Claude)** | `ANTHROPIC_API_KEY`. No embeddings API — wizard asks a separate embed backend (Ollama / OpenAI-compatible / Gemini / hash). |
| `4` | **Google Gemini** | `GEMINI_API_KEY` / `GOOGLE_API_KEY` for chat + embed. |

Non-interactive (`--skip-setup` or non-TTY) only ensures the home and
reports status — it never blocks on prompts.

When the wizard finishes it prints a **home ready** panel (db, policies,
judgment, embedder) and a short **next steps** legend (`ingest` /
`cognize` / `review` / `doctor` / `setup mcp`). Full operating loops live
in [OPERATIONS.md](OPERATIONS.md).

### Re-run and helpers

```bash
twin init                 # change provider / models again
twin setup ollama         # pull / verify configured Ollama models
twin setup postgres       # prepare primary PostgreSQL + pgvector
twin setup mcp <client>   # wire MCP: cursor | claude-code | claude-desktop
twin doctor               # verify store, LLM, MCP clients, connectors
twin reindex              # regenerate embeddings after changing embed model
```

## Configuration

Settings from the wizard land in `~/.twin/env`. You can also export them
in the shell. Useful knobs:

| variable | default | effect |
|---|---|---|
| `TWIN_HOME` | `~/.twin` | config directory |
| `TWIN_DB_URL` | `sqlite:///~/.twin/twin.db` | `postgresql://…` selects Postgres + pgvector |
| `TWIN_LLM_PROVIDER` | `ollama` | `ollama`, `anthropic`/`claude`, `gemini`/`google`, `openai`/`openai_compatible`, or presets (`groq`, `openrouter`, `lmstudio`, …) |
| `TWIN_LLM_BASE_URL` / `TWIN_LLM_MODEL` / `TWIN_LLM_API_KEY` | (provider defaults) | chat endpoint for Cognize, domain resolve, episode stages |
| `TWIN_OLLAMA_URL` | `http://127.0.0.1:11434` | local Ollama |
| `TWIN_OLLAMA_MODEL` | `qwen3.6:latest` | local chat model |
| `TWIN_OLLAMA_EMBED_MODEL` | `nomic-embed-text-v2-moe` | local embed model |
| `TWIN_EXTRACTOR` | `auto` | `auto` / `ollama` / `echo` / `heuristic` — `heuristic` blocks semantic episode stages |
| `TWIN_EMBEDDER` | `auto` | `auto` / `ollama` / `openai_compatible` / `gemini` / `hash` |
| `TWIN_EMBED_BASE_URL` / `TWIN_EMBED_MODEL` / `TWIN_EMBED_API_KEY` | (provider defaults) | embedding endpoint |
| `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` / … | — | provider-native keys (also honored) |
| `TWIN_ENCRYPTION_KEY` | — | when set, encrypts raw content and evidence at rest |

Embeddings are regenerable indexes, not canonical memory — see
[ARCHITECTURE.md](ARCHITECTURE.md). After changing the embed model: `twin reindex`.

## Verify

```bash
twin doctor
```

Expect a healthy store, reachable chat provider (or a clear warn), and
policies present. Fix anything `fail` before ingesting real sources.

## Tests

```bash
python -m pytest
```

Suites live under `tests/`. Prefer that over maintaining a feature
checklist here.

---

Destination in [README.md](../README.md). Operate in [OPERATIONS.md](OPERATIONS.md). Interfaces in [INTERFACES.md](INTERFACES.md).
