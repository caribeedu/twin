"""GitHub connector.

The adapter only knows how to FETCH and NORMALIZE GitHub objects; every
integrity guarantee (staged idempotency, fenced leases, transactional
finalize, checkpoint CAS, quarantine, DLQ, capabilities) comes from the
 framework. Read-only by design: the perceives, it never acts.
"""

from .adapter import GithubConnector  # noqa: F401 — registration side effect
