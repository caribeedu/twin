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
| Claims & review | `/api/claims`, `/api/review` | Preferred dual-read claim surface |
| Narratives & reflections | `/api/narratives`, `/api/narratives/{id}`, `/api/narratives/commit`, `/api/narratives/commit-preview`, `/api/reflections`, `/api/reflections/{id}` | List, EpistemicState, human commit with preview fingerprint |
| Cognize entities | `/api/situations`, `/api/interpretations`, `/api/relations`, `/api/evidence`, `/api/traces`, `/api/stances`, `/api/percepts/{id}` | Web Command Center list+show ([WEB_CENTER.md](WEB_CENTER.md)) |
| Center summary | `/api/center/summary`, `/api/cognize/status\|plan\|run`, `/api/runtime/jobs` | Overview; Cognize plan/estimate/enqueue; job list |
| Search & packs | `/api/search`, `/api/context_pack`, `/api/observer` | Hybrid retrieval and firewall-filtered packs |
| Sessions & runtime | `/api/sessions`, `/api/attention`, `/api/runtime`, `/api/health` | Cognitive sessions, attention, worker health |
| Connectors | `/api/connectors`, `/api/webhooks` | Connector ops and inbound webhooks |
| Judgment / Stance | `/api/judgment`, `/api/stances`, `/api/stances/proposals/{id}/preview\|approve` | Items, proposals; Stance approve requires preview token |
| Sovereignty | `/api/export`, `/api/backup`, `/api/restore` | Export / backup / restore |
| Evals & metrics | `/api/evals`, `/api/metrics` | Harnesses and operational metrics |

### Cognize entity reads (Web Center)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/percepts`, `/api/percepts/{id}` | Sense observations |
| GET | `/api/situations`, `/api/situations/{id}` | Working clusters (+ `percept_ids`) |
| GET | `/api/reflections`, `/api/reflections/{id}` | `status=open` default; `all` for full list |
| GET | `/api/interpretations`, `/api/interpretations/{id}` | `status=competing` default |
| GET | `/api/relations`, `/api/relations/{id}` | Filter `type`, `from_id`, `to_id` |
| GET | `/api/evidence`, `/api/evidence/{id}` | Anchors; filter by target |
| GET | `/api/traces`, `/api/traces/{id}` | Accessibility ledger |
| GET | `/api/narratives/{id}` | Embeds epistemic, `derived_confidence`, relations, evidence, open_reflections |
| POST | `/api/narratives/commit` | **Requires** `preview_token` from commit-preview |
| GET/POST | `/api/stances/proposals…` | List; preview; approve with token |

Review resolve actions (merge, contradict, supersede, dismiss, …) go
through claim/finding endpoints (`/api/claims/…`) on the workbench — see
OpenAPI and the UI under `twin serve` ([WEB_CENTER.md](WEB_CENTER.md)).

---

Install/config in [SETUP.md](SETUP.md). Ops in [OPERATIONS.md](OPERATIONS.md).
