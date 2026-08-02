# Interfaces

This document explains how tools talk to Twin — Native, MCP, CLI, local
API and connectors. Shared concepts and surface map live here; command
and tool detail live in the per-surface docs.

> **Native where possible. MCP everywhere. One cognitive core.**

Twin is infrastructure, not a chat app. LLM-powered **clients** pull
governed context from one local core. Prefer **native** when the host can
embed Twin in its session lifecycle; use **MCP** as the universal tool
surface everywhere else. **CLI** and the local **API** are the same core
with different transport. **Connectors** ingest external sources — they
are not client sessions.

## Surfaces

| Surface | Doc | Role | Prefer when |
|---|---|---|---|
| **Native** | [NATIVE.md](NATIVE.md) | Host lifecycle binds to Twin sessions; packs on session start; observations; summary percept on session end | The host offers a native surface (reference: Claude Code hooks; same contract for later hosts) |
| **MCP** | [MCP.md](MCP.md) | Universal tools: packs, search, sessions, review, judgment, connector ops | Every MCP client; also alongside native for mid-task tools |
| **CLI** | [CLI.md](CLI.md) | Ingest, review, connector ops, scripting | Humans and automation outside an IDE |
| **Local API / REST** | [REST.md](REST.md) | HTTP + review workbench | Browsers and local integrations |

---

## Shared concepts

Most retrieve / pack calls share these ideas:

| Concept | Meaning |
|---|---|
| `target_domain` / `--domain` | Domain the *consumer* is working in (`technical`, `work`, …). Firewall uses this to block cross-domain leaks **before** content reaches the LLM. |
| `query` | Natural-language task or question that drives hybrid search + packing. |
| Memory `status` | `candidate` (unreviewed) vs `confirmed` (trusted). Packs **exclude candidates by default**. |
| `include_candidates` | Explicit opt-in to pack unreviewed items (usually for human review flows, not agents). |
| `max_tokens` | Soft budget for pack size. |
| `confirm=true` / `--confirm` | Required on mutating MCP tools and some CLI paths — dry-run / preview otherwise. |
| Judgment | Separate from memory: principles and trade-offs that shape how tools should decide. |

---

## Clients

Clients are LLM-powered tools that **consume** Twin (packs, search, sessions). They are not [Connectors](#connectors).

| Preference | Surface |
|---|---|
| **1. Native** | When the host can embed Twin in its session lifecycle — see [NATIVE.md](NATIVE.md) |
| **2. MCP** | Universal tools for every MCP client; also complements native — see [MCP.md](MCP.md) |

Terminal and HTTP surfaces: [CLI.md](CLI.md) · [REST.md](REST.md).

---

## Connectors

Connectors are **source adapters**, not LLM clients. They pull GitHub, Slack, mail, calendars, meetings and folders into Twin. Client sessions are documented under [Native](NATIVE.md) and [MCP](MCP.md).

Connectors are how Twin **obtains** ongoing evidence from professional systems. Each adapter fetches and normalizes into the same Artifact-to-Percept path as `twin ingest`. They do **not** confirm Memory or Judgment — you still run `twin extract` and `twin review`.

Ownership (`--source-owner`) and vault labels keep employer and personal data separable. End-to-end operating loops (sync, backfill, DLQ, backup) in [OPERATIONS.md](OPERATIONS.md).

### What each connector extracts

Every connector uses an **allowlist** (repos, channels, labels, folders, calendars, or disk roots) — never “ingest the whole workspace by default.” Attachments are metadata-oriented unless noted. After any sync: `twin extract` then `twin review`.

| Connector | Identifier | Pulls into Twin | Does not pull | Notes |
|---|---|---|---|---|
| **GitHub** | `github` | Issues + issue comments; PRs + reviews + review comments; default-branch commits; releases; CI check **summaries** | Diffs / patches; attachment or blob bytes; non-default-branch commits (except as PR heads); provider deletions | Explicit repo list. Polling is authoritative; optional webhook only marks sync due. Bot-like posts flagged as derived. |
| **Slack** | `slack` | Channel history: messages and thread replies (text, edits, deletion tombstones). File **names / mime / size / permalink** as refs | File **bytes**. Whole-workspace scrape | Channel allow-list. DMs and private channels off unless you opt in. High leakage risk — set ownership/vault honestly. |
| **Gmail** | `gmail` | Messages under chosen labels: subject, From/To/Cc, authored body (quotes/signatures split), snippet, label membership | Attachment **bodies** (metadata refs only by default). Spam/promotions unless you include those labels | OAuth read-only. HTML kept as an untrusted stub, not safe UI HTML. |
| **Outlook** | `outlook` | Same mail cognitive model as Gmail, via Microsoft Graph folders you choose | Attachment bodies (same metadata rule). Write scopes | Folder discovery before sync. Delta sync; removals become tombstones. |
| **Google Calendar** | `calendar` | Events on chosen calendars: title, when, status, location, organizer, attendees, description (capped) | Attachments. In **free/busy** mode: no title, attendees, or description — busy windows only | Correlate later with meeting transcripts when ids / links match. Match vault to personal vs work. |
| **Fireflies** | `fireflies` | Meeting **manifest**, speaker-labeled **transcript chunks**, optional provider **summary** | Audio / video bytes; signed media URLs (flags only that media existed) | Chunks never split mid-utterance. Summary marked derived. Still extract + human review; PII policies apply. |
| **Local folder** | `folder` | Watched roots: text docs (default `md` / `txt` / `rst`, …) as manifest + revision **chunks**; deletes as tombstones | Binary file bodies; absolute paths in the cognitive payload | Content-hash skips unchanged files. Oversized / unsupported files stay metadata-only. No auth — path access is the trust boundary. |

Connectors reference in [CLI.md → Connectors](CLI.md#connectors). MCP tools in [MCP.md → Connectors and meta](MCP.md#connectors--meta). HTTP webhooks in [REST.md](REST.md).

---

Quickstart narrative in [README.md](../README.md). Install/config in [SETUP.md](SETUP.md). Ops in [OPERATIONS.md](OPERATIONS.md).
