# Connector evals

Deterministic, offline evaluation cases for the connector framework. The harness
seeds with `FakeConnector`; real adapters add fixtures under `cases/`.

## What these check

- **normalization**: a raw fixture maps to the expected `ConnectorRecord`
  envelope (external ids, revision, thread key, ownership, confidentiality).
- **idempotency**: replaying the same fixture page yields no new record or
  percept, and the checkpoint advances only after a committed batch.
- **partial_batch**: one failing item makes the whole stream invisible —
  no records, no percepts, checkpoint unchanged; the retry lands everything
  together.
- **revision_collision**: the same external revision returning different
  content dead-letters and never overwrites the stored evidence.
- **checkpoint_failure**: a fault-injected finalize leaves no committed
  batch and no advanced checkpoint — never one without the other.
- **quarantine**: prompt-injection content is quarantined and produces no
  percept, while the clean batch still commits.
- **source_deletion**: a provider tombstone resolves prior revisions and
  their percepts into a `ConnectorDeletionEvent` (pending for the deletion
  planner) without creating or removing percepts by itself.

## Layout

```text
evals/connectors/
  README.md
  cases/
    normalization_basic.json
    idempotency_replay.json
    partial_batch.json
    revision_collision.json
    checkpoint_failure.json
    quarantine.json
    source_deletion.json
    github_pr_lifecycle.json
    github_bot_lineage.json
    slack_thread_bot_lineage.json
    gmail_thread_lineage.json
    calendar_meeting_correlation.json
    folder_document_revisions.json
    cross_source_work_episode.json
    ops_health_metrics.json
  run.py
```

## Run

```bash
python -m evals.connectors.run
```
