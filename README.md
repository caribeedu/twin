<p align="center">
  <img src="assets/banner.png" alt="twin — Personal Cognitive OS" width="100%">
</p>

<p align="center">
  <strong>Personal Cognitive OS</strong> — local-first memory, judgment and context<br/>
  that any LLM can consult safely via MCP, CLI or API.
</p>

<p align="center">
  <a href="#how-to-use-twin"><img src="https://img.shields.io/badge/quickstart-how_to_use-7c3aed?style=for-the-badge" alt="How to use"></a>
  <a href="docs/SETUP.md"><img src="https://img.shields.io/badge/python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"></a>
  <a href="docs/CONNECTION.md"><img src="https://img.shields.io/badge/MCP-first-111827?style=for-the-badge" alt="MCP"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-22c55e?style=for-the-badge" alt="MIT"></a>
</p>

<p align="center">
  <a href="#why-twin">Why</a> ·
  <a href="#before--after">Before / After</a> ·
  <a href="#how-to-use-twin">How to use</a> ·
  <a href="#what-twin-is">What it is</a> ·
  <a href="#what-twin-is-not">What it is not</a> ·
  <a href="#docs">Docs</a> ·
  <a href="#faq">FAQ</a>
</p>

---

## Why Twin?

Modern LLMs are powerful — and still forget who you are every new chat.

You re-explain projects, decisions, rejected alternatives, tone preferences and hard domain boundaries. Product “memory” and RAG help a little; they still retrieve **text**, not **cognition**.

Twin’s bet:

> Not building an AI that remembers you — building a personal cognitive infrastructure that any AI can safely consult.

Local store. Evidence-backed memories. Domain firewall. Evolving judgment. Context packs over MCP so Cursor, Claude, Codex and friends stop starting from zero.

---

## The problem

Even with long windows and product memory, users still repeat who they are, how they want answers, what was decided, which constraints hold and which domains must never mix.

For people who already know RAG, MCP and agents, the hard problem is not “stuff files into context”. It is:

> How do I create a persistent, safe, linkable, temporal representation of my mind/context so different LLMs need less explanation and more understanding?

Integration is not only low latency. What is missing is **operational understanding**: what a memory means, when it holds, which domain may use it and how it should affect a decision.

Twin’s concrete answer: store evidence-grounded memory locally, confirm what is trusted, let any LLM pull a safe pack instead of asking you to re-explain.

<p align="center">
  <img src="assets/vision.png" alt="One evolving mind across every interface — Twin as the persistent cognitive substrate connecting ChatGPT, Claude, Cursor, Codex and local models" width="100%">
</p>

---

## Vision

Long-term, Twin aims to work as a **personal exocortex**: continuity across tools, sessions, models and contexts.

It should preserve important facts, decisions, rejected alternatives, tasks, preferences, judgment patterns, beliefs that change over time, relationships, evidence, hard domain boundaries, privacy and human control.

The aesthetic inspiration can be sci-fi and human–machine interfaces; the implementation must stay sober, local-first, auditable and incremental.

### What Twin is

A **local-first** layer of personal memory, judgment, privacy and context — queryable by any LLM/tool via **MCP**, a local HTTP API and a CLI.

> Not a chatbot. A substrate other tools consult.

It preserves facts, decisions, rejected alternatives, preferences, domain boundaries, evidence and human control — then ships **safe context packs** into the tools you already use.

Deeper product shape and roadmap: [docs/PRODUCT.md](docs/PRODUCT.md). Conceptual roots: [docs/FOUNDATIONS.md](docs/FOUNDATIONS.md).

### What Twin is not

Twin must not be understood as a chatbot, note-taking app, generic RAG, autonomous agent, vector-DB-of-markdown, Jarvis clone, or a UI meant to replace ChatGPT / Claude / Cursor.

**Non-goals:** not replacing those apps; not fine-tuning “you”; not archiving your entire life. Twin stays the substrate other tools consult.

**Why not RAG?** RAG retrieves documents; Twin retrieves cognition.

```text
# typical RAG                         # Twin
query → vectors → chunks → LLM        query → project → domain → persona
                                      → firewall → graph → judgment
                                      → observer → context pack → LLM
```

Vectors are indexes. The graph (memories, evidence, validity, domains, status) is truth. Wipe embeddings, `twin reindex`, keep the substrate.

### Final definition

Twin is a personal, local-first, interoperable and temporal layer of memory, judgment, privacy and context — so different LLMs can share a consistent representation of you without a re-brief every session.

> I don't want to just use an AI. I want to feel integrated with the machine, as if part of my cognition could exist outside my brain, with safety, continuity and control.

The MVP starts small: reliable technical memory via MCP. The destination is bigger: a personal, portable, private and evolving extended brain.

---

## How to use Twin

Python 3.10+, a clone of this repo, and an MCP client (Cursor / Claude Code / Claude Desktop). SQLite is enough for day one — no Postgres required.

```bash
git clone https://github.com/caribeedu/twin.git
cd twin
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[mcp]"     # add ,dev or ,api later if you want tests/API

twin init                   # creates ~/.twin + guided model setup
twin doctor                 # optional: store, policies, LLM, MCP configs
```

`twin init` is required before anything else — until it runs there is no home and no store. The wizard configures chat + embeddings (Ollama recommended; Anthropic, Gemini and OpenAI-compatible are opt-in). Details: [docs/SETUP.md](docs/SETUP.md).

### Put knowledge in (and confirm it)

Twin does not invent durable facts for you. Ingest evidence, extract candidates, **confirm** what should be trusted. Context packs default to confirmed memories only.

```bash
twin ingest ./examples/docs   # or your own notes/docs
twin extract                  # needs a reachable chat model, or TWIN_EXTRACTOR=echo
# twin extract -A             # optional: auto-confirm new candidates
twin review                   # accept the solid decision; reject noise
```

Check without an LLM:

```bash
twin search "webhook outbox" --domain technical
twin pack "retry strategy for Atlas webhooks" --domain technical
```

### Connect an LLM client over MCP

```bash
twin setup mcp cursor          # or: claude-code | claude-desktop
```

Restart / reload MCP. Twin should appear as a local server running `twin mcp`. Full interfaces + per-client setup: [docs/CONNECTION.md](docs/CONNECTION.md).

### First visible result

Open a **new** chat. Do **not** paste the RFC. Ask something only Twin’s memory can answer:

> For Atlas webhooks, what delivery approach did we already decide on, and what did we reject?

A well-wired client calls `memory_safe_context_pack` or `session_start` with `target_domain=technical`, receives your confirmed decision, and answers with the outbox/Postgres choice (Kafka rejected) — even though you never typed that in the chat.

```text
documents / sessions
  → ingest + extract
  → you confirm what is trusted
  → MCP context pack
  → LLM answers with less re-explanation
```

If the model still asks you to explain from scratch: memory must be `confirmed`, MCP tools enabled, and the client must request a pack with the right domain.

**Next:** keep ingesting your docs or complete MCP sessions (`session_start` → work → `session_complete`); `twin setup postgres` when you outgrow SQLite; daily ops via CLI or `twin serve` — see [docs/SETUP.md](docs/SETUP.md#operator-runbook).

---

## Before / After

<p align="center">
  <img src="assets/before-and-after.png" alt="Before vs After: LLMs without Twin are isolated and restart every chat; with Twin they share one cognitive core — memory, judgment, privacy, graph, context and evidence" width="100%">
</p>

That loop is the product promise in miniature.

---

## Docs

| Doc | What it covers |
|---|---|
| **[docs/SETUP.md](docs/SETUP.md)** | Install, providers, config, tests, operator runbook |
| **[docs/CONNECTION.md](docs/CONNECTION.md)** | MCP / CLI / API tables + per-client setup |
| **[docs/PRODUCT.md](docs/PRODUCT.md)** | Layers, domains, MVP, roadmap, v1.0 release |
| **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Brain analogies, principles, pipeline, threat model |
| **[docs/FOUNDATIONS.md](docs/FOUNDATIONS.md)** | Extended mind, 4E, academic inspirations |

---

## FAQ

**Do I need the cloud?**  
No. Default path is local Ollama + SQLite. Cloud providers are opt-in.

**Is Twin another RAG app?**  
No. Retrieval is one step; firewall, evidence, temporality and judgment are the product.

**Which LLM providers work?**  
Ollama (recommended), Anthropic, Gemini, OpenAI and any OpenAI-compatible gateway (Groq, OpenRouter, LM Studio, vLLM, …). See [docs/SETUP.md](docs/SETUP.md).

**Where does my data live?**  
Under `~/.twin` (or `$TWIN_HOME`). Export with `twin export`. Backup = copy the folder.

**Can I leave later?**  
Yes — exportability is a first-class architecture principle ([docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)).

**Does Anthropic do embeddings?**  
No. Pair Claude chat with Ollama / OpenAI-compatible / Gemini / hash embeddings.

---

## Contributing

Issues and PRs welcome. Prefer small, reviewable changes that preserve local-first defaults, firewall-before-LLM and evidence-backed memory.

```bash
pip install -e ".[dev]"
python -m pytest
```

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (principles) and [docs/PRODUCT.md](docs/PRODUCT.md) before large design swings.

---

## License

[MIT](LICENSE) © 2026 Edu Caribé
