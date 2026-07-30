[← README](../README.md) · [FOUNDATIONS](FOUNDATIONS.md) · [PRODUCT](PRODUCT.md) · [ROADMAP](ROADMAP.md) · [CHANGELOG](CHANGELOG.md) · [ARCHITECTURE](ARCHITECTURE.md) · [INTERFACES](INTERFACES.md) · [SETUP](SETUP.md) · [OPERATIONS](OPERATIONS.md)

# Operations

**Source of truth for:** day-2 operation — cognitive runtime, health, connectors, backup, release gates and incidents.

Install and providers live in [SETUP.md](SETUP.md). How to use in [README](../README.md#how-to-use).

## Start cognitive runtime

Required for Claude Code native hooks: deferred domain resolve and SessionEnd consolidation run as background jobs.

```bash
twin runtime start          # live processing panel on TTY; or: twin-runtime
twin runtime start --no-live
twin runtime status         # queue depth + recent jobs
twin runtime status --json
```

Workers claim durable jobs, including:

| Kind | Typical producer |
|---|---|
| `session_domain_resolve` | Native UserPromptSubmit when search cannot name a domain |
| `session_complete` | Native SessionEnd (binding already closed) |
| `interpret_percept` | Manual / extract pipelines |
| `workspace_tick` / `attention_evaluate` | Workspace / session deltas |
| `consolidate_daily` / `consolidate_weekly` | Scheduler (`twin runtime schedule` or start loop) |
| `integrity_check` | Scheduler |
| `connector_reconcile` | Recovery / manual enqueue |
| `backfill_partition` | Scheduler / `twin connector backfill --run` (historical; not continuous sync) |
| `reembed_memory` | Manual enqueue |

Full CLI table and payload examples in [INTERFACES.md](INTERFACES.md#runtime).

```bash
# inspect / recover one job
twin runtime job <job_id>
twin runtime retry <job_id>
twin runtime cancel <job_id>
```

## Health

```bash
twin doctor
twin runtime status
curl -s localhost:PORT/api/runtime/health
curl -s localhost:PORT/api/health/cognition
twin connector due
```

`twin doctor` reports runtime queue health from the store (no pidfile, so it never claims a worker is "up"):

- `runtime:queue` — warns with `N jobs pending — run \`twin runtime start\`` when work is backlogged (native SessionEnd consolidation + domain resolve run here).
- `runtime:failed` — jobs retrying with backoff.
- `runtime:dead_letter` — fails; inspect and requeue with `twin runtime retry <job_id>`.

## Connector recovery

```bash
twin connector sync-due
# or enqueue via runtime:
twin runtime enqueue connector_reconcile
twin connector production-ready   # attest ≥2 real adapters
```

Paused / unauthorized instances stay out of syncable sets until credentials are fixed and resumed.

## Dead letters

```bash
twin runtime status                 # includes dead-letter count
twin runtime retry <job_id>         # requeue failed / dead-lettered runtime job
# connector DLQ:
twin connector dead-letters <connector_id>
twin connector replay <id>
```

Permanent handler failures land in DLQ. `model_unavailable` on model-gated kinds (`interpret_percept`, `workspace_tick`, `session_domain_resolve`, `session_complete`, …) must stay pending/retry — never DLQ.

## Backup / restore

```bash
twin backup create ./backup-dir
twin backup validate ./backup-dir
twin backup restore ./backup-dir ./restored.db
```

Validate before restore. Restored DB is isolated until you point `$TWIN_HOME` / config at it.

## Memory formation (human control)

```bash
twin memory candidates
# confirm / reject only with evidence present
twin review
```

**Default:** humans confirm Memory; Judgment always stays human-gated. Do not automate confirmation of Judgment. Opt-in `twin extract -A` (auto-confirm new *memory* candidates) is for trusted demos or tightly scoped pipelines only — not the recommended day-one path. See [INTERFACES.md](INTERFACES.md).

## Release gate

```bash
twin eval golden
twin connector production-ready
pytest -q
```

`twin eval golden` exercises the cognitive work-loop. `production-ready` reports whether real adapters (not Fake) close the shared contract. Behavior lives in ordinary pytest suites under `tests/` — not in version or phase checklists.

## Incident: injection suspected

1. Quarantine / reject affected candidates.
2. Confirm packs exclude injection (`blocked` reasons, not content).
3. Rotate any secrets that appeared in source text.
4. Re-run `GET /api/health/cognition` / integrity job.

---

Install in [SETUP.md](SETUP.md). Interfaces in [INTERFACES.md](INTERFACES.md). Overview in [README](../README.md).
