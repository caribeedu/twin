---
author: Edu
date: 2026-06-20
---

# RFC: Webhooks architecture for the Atlas project

## Context

The Atlas project needs to notify external systems when orders change state.
Today this is done by polling, which puts unnecessary load on the database.

## Decision

We decided to use an outbox pattern with a `webhook_outbox` table in Postgres
and a dedicated worker that publishes the events. We chose not to use Kafka at
this point: the current volume (~2k events/day) does not justify the
operational complexity.

Rejected alternatives:

- Kafka: high operational overhead for the current volume.
- Trigger + pg_notify: fragile when the consumer reconnects.

## Consequences

- The webhooks worker is responsible for retry with exponential backoff.
- TODO: Edu needs to review the outbox table schema by the end of the month.
- Constraint: we must not deliver payloads containing card data — PCI
  compliance forbids it.
