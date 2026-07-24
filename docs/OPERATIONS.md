[← README](../README.md) · [FOUNDATIONS](FOUNDATIONS.md) · [PRODUCT](PRODUCT.md) · [ROADMAP](ROADMAP.md) · [CHANGELOG](CHANGELOG.md) · [ARCHITECTURE](ARCHITECTURE.md) · [INTERFACES](INTERFACES.md) · [SETUP](SETUP.md) · [OPERATIONS](OPERATIONS.md)

# Operations

**Source of truth for:** day-2 operation — cognitive runtime, health, connectors, backup, release gates and incidents.

Install and providers live in [SETUP.md](SETUP.md). Quickstart: [README](../README.md#quickstart).

## Start cognitive runtime

```bash
twin-runtime   # or: python -m twin.runtime
```

Workers claim durable jobs (`interpret_percept`, `workspace_tick`, `attention_evaluate`, `consolidate_*`, `integrity_check`, `connector_reconcile`, …).

## Health

```bash
twin doctor
curl -s localhost:PORT/api/runtime/health
curl -s localhost:PORT/api/health/cognition
twin connector due
```

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
twin runtime dead-letters
twin runtime retry-dead-letter <id>
# connector DLQ:
twin connector dead-letters <connector_id>
twin connector retry-dead-letter <id>
```

Permanent handler failures land in DLQ. `model_unavailable` must stay pending/retry — never DLQ.

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
twin eval v1-completion
twin connector production-ready
pytest -q
```

`v1-completion` fails closed on required criteria that are untested, partial, or evidence-free.

## Incident: injection suspected

1. Quarantine / reject affected candidates.
2. Confirm packs exclude injection (`blocked` reasons, not content).
3. Rotate any secrets that appeared in source text.
4. Re-run `GET /api/health/cognition` / integrity job.

---

Install: [SETUP.md](SETUP.md). Interfaces: [INTERFACES.md](INTERFACES.md). Overview: [README](../README.md).
