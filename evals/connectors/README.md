# Connector evals (v0.6)

Deterministic, offline evaluation cases for the connector framework. Phase 1
seeds the harness with the `FakeConnector`; real adapters (GitHub first) add
their own fixtures under this directory in later phases.

## What these check

- **normalization**: a raw fixture maps to the expected `ConnectorRecord`
  envelope (external ids, revision, thread key, ownership, confidentiality).
- **idempotency**: replaying the same fixture page yields no new record or
  percept, and the checkpoint advances only after a committed batch.

## Layout

```text
evals/connectors/
  README.md
  cases/
    normalization_basic.json   # input fixture + expected record shape
    idempotency_replay.json     # two identical passes → one record/percept
  run.py                        # tiny runner over the FakeConnector
```

## Run

```bash
python -m evals.connectors.run
```

Cases are data, not instructions. Any content that looks like a prompt (see the
quarantine case) must never reach extraction.
