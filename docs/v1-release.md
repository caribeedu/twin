# Twin v1.0.0 — Personal Cognitive OS release

## What “done” means

Twin v1.0 is a **local-first, auditable, interoperable cognitive substrate** that:

- preserves evidence-grounded memory across tools and sessions;
- enforces persona and domain boundaries;
- recovers from operational failure (leases, DLQ, backup/restore);
- never auto-confirms Memory or Judgment;
- measurably reduces re-explanation via packs, sessions, and attention.

It is **not** a complete autonomous mind.

## Release artifacts

| Artifact | Location |
|---|---|
| Package version | `pyproject.toml` → `1.0.0` |
| Library version | `twin/__init__.py` → `__version__` |
| Threat model | [threat-model.md](threat-model.md) |
| Operator runbook | [runbook.md](runbook.md) |
| Completion gate | `twin eval v1-completion` |
| Connector readiness | `twin connector production-ready` |
| Golden scenario | `twin eval golden` / `evals/v1/cases/golden_work_loop.json` |

## Compatibility notes

- SQLite remains the zero-config store; Postgres paths stay supported where previously implemented.
- Connector §88 matrix may still show non-ready rows for mail/calendar/folder — only GitHub + Slack are attested production-ready in v1.0.
- Encrypted/incremental backups and full soak harness are deferred follow-ons (documented residual).

## Gate commands

```bash
twin eval v1-completion
twin connector production-ready
twin eval golden
pytest -q
```

All required cells in the v1 completion matrix must be `pass` with evidence pointers.
