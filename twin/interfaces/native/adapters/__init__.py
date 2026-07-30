"""Adapter frontier — host-specific declarations live here, not in the generic service."""

from .registry import capabilities_for_host

__all__ = ["capabilities_for_host"]
