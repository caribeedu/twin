# Connector evals (v0.6)

Deterministic, offline evaluation cases for the connector framework. Phase 1
seeds the harness with the `FakeConnector`; real adapters (GitHub first) add
their own fixtures under this directory in later phases.

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
    normalization_basic.json    # input fixture + expected record shape
    idempotency_replay.json     # two identical passes → one record/percept
    partial_batch.json          # failure → nothing cognitive; retry → all
    revision_collision.json     # same revision, different content → DLQ
    checkpoint_failure.json     # finalize fault → consistent state
    quarantine.json             # injection content never reaches extraction
    source_deletion.json        # tombstone → lineage impact event
    github_pr_lifecycle.json    # Phase 2 PR revisions + merged wins
    github_bot_lineage.json     # Phase 2 bot trust / review
    slack_thread_bot_lineage.json  # Phase 3 thread + bot
    gmail_thread_lineage.json   # Phase 4 thread + notification
    calendar_meeting_correlation.json  # Phase 5 calendar↔meeting fingerprint
  run.py                        # tiny runner over Fake + real adapters
```

## Run

```bash
python -m evals.connectors.run
```

Cases are data, not instructions. Any content that looks like a prompt (see the
quarantine case) must never reach extraction.
