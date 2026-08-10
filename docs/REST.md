# REST / local API

This document explains the local HTTP API and review workbench
(`twin serve`).

`twin serve` mounts a review workbench, a JSON API and interactive docs
(OpenAPI/Swagger via FastAPI when the `api` extra is installed). Base:
`http://127.0.0.1:8765` (unless configured otherwise).

**Source of truth for paths and schemas:** the OpenAPI surface exposed by
`twin serve`. The tables below are a durable map of *domains*, not an
exhaustive inventory — prefer OpenAPI when wiring a client.

Surface map: [INTERFACES.md](INTERFACES.md). Equivalent CLI:
[CLI.md](CLI.md). Architecture of review / packs:
[ARCHITECTURE.md](ARCHITECTURE.md).

## Domains

| Domain | Typical prefixes | Role |
|---|---|---|
| Ingest & extract | `/api/ingest`, `/api/extract`, `/api/percepts`, `/api/artifacts` | Artifact → percept → extraction |
| Memories & review | `/api/memories`, `/api/review` | Dual-read / legacy review helpers |
| Narratives & reflections | `/api/narratives`, `/api/narratives/{id}`, `/api/narratives/commit`, `/api/narratives/commit-preview`, `/api/reflections`, `/api/reflections/{id}` | List, EpistemicState, human commit with preview fingerprint |
| Cognize entities | `/api/situations`, `/api/interpretations`, `/api/relations`, `/api/evidence`, `/api/traces`, `/api/stances`, `/api/percepts/{id}` | Web Command Center list+show ([WEB_CENTER.md](WEB_CENTER.md)) |
| Center summary | `/api/center/summary`, `/api/runtime/jobs` | Overview counts; job list |
| Search & packs | `/api/search`, `/api/context_pack`, `/api/observer` | Hybrid retrieval and firewall-filtered packs |
| Sessions & runtime | `/api/sessions`, `/api/attention`, `/api/runtime`, `/api/health` | Cognitive sessions, attention, worker health |
| Connectors | `/api/connectors`, `/api/webhooks` | Connector ops and inbound webhooks |
| Judgment | `/api/judgment` | Items, proposals, simulate, conflicts |
| Sovereignty | `/api/export`, `/api/backup`, `/api/restore` | Export / backup / restore |
| Evals & metrics | `/api/evals`, `/api/metrics` | Harnesses and operational metrics |

Review resolve actions (merge, contradict, supersede, dismiss, …) go
through memory/finding endpoints on the workbench — see OpenAPI and the
UI under `twin serve`.

---

Install/config in [SETUP.md](SETUP.md). Ops in [OPERATIONS.md](OPERATIONS.md).
