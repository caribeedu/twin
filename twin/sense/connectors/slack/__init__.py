"""Slack connector.

The adapter only FETCHes and NORMALIZEs Slack objects; integrity (leases,
transactional finalize, checkpoint CAS, quarantine, DLQ) comes from the
 framework. Read-only: perceives, it never posts.
"""

from .adapter import SlackConnector  # noqa: F401 — registration side effect
