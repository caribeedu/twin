"""Slack connector (v0.6 Phase 3).

The adapter only FETCHes and NORMALIZEs Slack objects; integrity (leases,
transactional finalize, checkpoint CAS, quarantine, DLQ) comes from the
Phase 1 framework. Read-only: v0.6 perceives, it never posts.
"""

from .adapter import SlackConnector  # noqa: F401 — registration side effect
