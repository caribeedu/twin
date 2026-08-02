# REST / local API

This document explains the local HTTP API and review workbench
(`twin serve`).

`twin serve` mounts a minimal review workbench, a JSON API and
interactive docs (OpenAPI/Swagger via FastAPI when the `api` extra is
installed). Base: `http://127.0.0.1:8765` (unless configured otherwise).

Surface map: [INTERFACES.md](INTERFACES.md). Equivalent CLI:
[CLI.md](CLI.md). Architecture of review / packs:
[ARCHITECTURE.md](ARCHITECTURE.md).

## Ingest & extract

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/ingest` | Ingest artifacts / paths into percepts. |
| `POST` | `/api/extract` | Run extraction on pending percepts. |
| `GET` | `/api/percepts` | List/inspect percepts. |
| `GET` | `/api/artifacts/{id}` | Fetch an artifact record. |

## Memories & review

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/memories` | List / filter memories. |
| `POST` | `/api/memories/{id}/review` | Submit a review decision. |
| `POST` | `/api/memories/{id}/promote` | Propose promotion into judgment. |
| `POST` | `/api/memories/{id}/supersede/{old_id}` | Supersede relation. |
| `POST` | `/api/memories/{id}/contradict/{other_id}` | Contradiction relation. |
| `GET` | `/api/memories/{id}/neighbors` | Neighborhood for review. |
| `GET` | `/api/memories/{id}/quality` | Quality report. |
| `GET` | `/api/memories/{id}/provenance` | Provenance chain. |
| `POST` | `/api/memories/{id}/split` | Split memory. |
| `POST` | `/api/memories/{id}/archive` | Archive memory. |
| `POST` | `/api/memories/merge` | Merge memories. |
| `GET` | `/api/review/queue` | Review queue. |
| `GET`/`POST` | `/api/review/batches` | Review batches. |

## Search, packs, observer

| Method | Path | What it does |
|---|---|---|
| `GET`/`POST` | `/api/search` | Hybrid search. |
| `POST` | `/api/context_pack` | Safe context pack (firewall applied). |
| `POST` | `/api/observer` | Memory observer over current text. |

## Judgment

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/judgment` | Judgment overview. |
| `GET` | `/api/judgment/items` | Judgment items. |
| `GET` | `/api/judgment/versions` | Version history. |
| `GET`/`POST` | `/api/judgment/proposals` | List / create proposals. |
| `POST` | `/api/judgment/proposals/generate` | Generate proposals from signals. |
| `POST` | `/api/judgment/proposals/{id}/preview` | Preview + token. |
| `POST` | `/api/judgment/proposals/{id}/approve` | Approve (token + confirm). |
| `POST` | `/api/judgment/proposals/{id}/reject` | Reject. |
| `POST` | `/api/judgment/import` | Import YAML bootstrap into store. |
| `POST` | `/api/judgment/applicable` | Applicable pack for a context. |
| `POST` | `/api/judgment/simulate` | Simulate application. |
| `GET` | `/api/judgment/conflicts` | Conflicts. |

## Evals, metrics, export

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/evals/extraction` | Run extraction eval. |
| `POST` | `/api/evals/retrieval` | Run retrieval eval. |
| `GET` | `/api/metrics` | Store / connector metrics. |
| `GET`/`POST` | `/api/export` | Export portable data. |

---

---

Quickstart narrative in [README.md](../README.md). Install/config in [SETUP.md](SETUP.md). Ops in [OPERATIONS.md](OPERATIONS.md).
