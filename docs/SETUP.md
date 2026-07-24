[← README](../README.md) · [FOUNDATIONS](FOUNDATIONS.md) · [PRODUCT](PRODUCT.md) · [ARCHITECTURE](ARCHITECTURE.md) · [CONNECTION](CONNECTION.md) · [SETUP](SETUP.md) · [OPERATIONS](OPERATIONS.md)

# Setup

**Source of truth for:** how you install Twin — packages, model providers, configuration and tests.

For the shortest path to a first result, start at the [README quickstart](../README.md#quickstart). Interfaces: [CONNECTION.md](CONNECTION.md). Day-2 ops (runtime, backup, incidents): [OPERATIONS.md](OPERATIONS.md).

## Installation

```bash
pip install -e ".[dev]"        # everything (api + mcp + postgres + crypto + tests)
# or granular:
pip install -e ".[api,mcp,postgres,crypto]"

twin init                      # creates ~/.twin (policies.yaml, judgment.yaml)
```

## Model providers

`twin init` is the first required Twin command. Until it runs, there is no home directory and no store for memories. The wizard asks which **LLM provider** to use for cognitive interpretation (extract / deep observer) and which **embedding** backend to use:

1. **Ollama (recommended)** — local open models; nothing leaves the machine. Install from [ollama.com/download](https://ollama.com/download), then set URL + chat model + embed model (defaults are fine to start).
2. **OpenAI-compatible (optional)** — base URL, API key (if needed), chat model, and embedding model. Covers OpenAI, Azure OpenAI, Groq, Together, Fireworks, OpenRouter, DeepSeek, Mistral, xAI, LM Studio, vLLM, and similar gateways. You can also set `TWIN_LLM_PROVIDER=groq|openrouter|…` for preset base URLs.
3. **Anthropic (Claude)** — Messages API via `ANTHROPIC_API_KEY`. Anthropic has no embeddings API; the wizard asks for a separate embed backend (Ollama / OpenAI-compatible / Gemini / hash).
4. **Google Gemini** — `generateContent` + `embedContent` via `GEMINI_API_KEY` / `GOOGLE_API_KEY`.

Settings are written to `~/.twin/env` and picked up on the next Twin process (CLI, API, MCP). Skip the interactive wizard with `twin init --skip-setup` when scripting CI.

Useful env knobs (full table in [Configuration](#configuration)):

| variable | role |
|---|---|
| `TWIN_LLM_PROVIDER` | `ollama` (default), `anthropic`, `gemini`, `openai`, `openai_compatible`, `groq`, `openrouter`, … |
| `TWIN_LLM_BASE_URL` / `TWIN_LLM_MODEL` / `TWIN_LLM_API_KEY` | chat endpoint for extract + deep observer |
| `TWIN_EMBEDDER` | `auto` / `ollama` / `openai_compatible` / `gemini` / `hash` |
| `TWIN_EMBED_BASE_URL` / `TWIN_EMBED_MODEL` / `TWIN_EMBED_API_KEY` | embedding endpoint |
| `TWIN_OLLAMA_*` | still valid aliases when provider is Ollama |
| `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` / … | provider-native key env vars (also honored) |

After changing the embedding model, regenerate vectors with `twin reindex`.

When you outgrow SQLite, run `twin setup postgres` to move to the primary PostgreSQL + pgvector backend. To pull or retarget models: re-run `twin init`, or `twin setup ollama` for the local path.

## Configuration

| variable | default | effect |
|---|---|---|
| `TWIN_HOME` | `~/.twin` | config directory (policies/judgment) |
| `TWIN_DB_URL` | `sqlite:///~/.twin/twin.db` | `postgresql://…` selects the primary backend (pgvector) |
| `TWIN_LLM_PROVIDER` | `ollama` | `ollama` (encouraged), `anthropic`/`claude`, `gemini`/`google`, `openai`/`openai_compatible`, or presets `groq` / `together` / `fireworks` / `openrouter` / `deepseek` / `mistral` / `xai` / `azure_openai` / `lmstudio` / `vllm` |
| `TWIN_LLM_BASE_URL` | (provider default) | chat API base; Ollama defaults to `TWIN_OLLAMA_URL` |
| `TWIN_LLM_MODEL` | (falls back to provider default / `TWIN_OLLAMA_MODEL`) | chat model for extract + deep observer |
| `TWIN_LLM_API_KEY` | — | API key for cloud chat (also reads `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`/`GOOGLE_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY`, … per provider) |
| `TWIN_OLLAMA_URL` | `http://127.0.0.1:11434` | local Ollama server |
| `TWIN_OLLAMA_MODEL` | `qwen3.6:latest` | local chat / extraction model |
| `TWIN_OLLAMA_EMBED_MODEL` | `nomic-embed-text-v2-moe` | local embedding model |
| `TWIN_EXTRACTOR` | `auto` | `auto` / `ollama` / `echo` / `heuristic` |
| `TWIN_EMBEDDER` | `auto` | `auto` / `ollama` / `openai_compatible` / `gemini` / `hash` |
| `TWIN_EMBED_BASE_URL` | (provider default) | embeddings API base |
| `TWIN_EMBED_MODEL` | (falls back to `TWIN_OLLAMA_EMBED_MODEL`) | embedding model id |
| `TWIN_EMBED_API_KEY` | — | API key for cloud embeddings |
| `TWIN_ENCRYPTION_KEY` | — | when set, encrypts raw content and evidence at rest |

Local open models via Ollama are the recommended default (`twin init` steers you there first). Anthropic, Gemini, OpenAI, and other OpenAI-compatible gateways are opt-in. Anthropic chat needs a separate embedding backend. Embeddings are not the source of truth: they are regenerable (`twin reindex`) and never mix across different models.

## Tests

```bash
python -m pytest
```

Expected coverage:

- PII;
- ingestion;
- extraction;
- dedupe;
- firewall;
- search;
- context pack;
- observer;
- API;
- MCP.

---

Quickstart: [README.md](../README.md#quickstart). Day-2 ops: [OPERATIONS.md](OPERATIONS.md). Interfaces: [CONNECTION.md](CONNECTION.md).
