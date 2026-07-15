"""GitHub connector (v0.6 Phase 2).

The adapter only knows how to FETCH and NORMALIZE GitHub objects; every
integrity guarantee (staged idempotency, fenced leases, transactional
finalize, checkpoint CAS, quarantine, DLQ, capabilities) comes from the
Phase 1 framework. Read-only by design: the v0.6 perceives, it never acts.
"""

from .adapter import GithubConnector  # noqa: F401 — registration side effect
