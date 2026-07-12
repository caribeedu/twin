"""Judgment System — the prefrontal layer.

Decides what may flow where (Domain Firewall), what must never leave the
machine unmasked (PII filter) and how the user decides (evolving judgment
model: versioned, scoped, proposal-driven).
"""

from .application import applicable_pack, render_applicable
from .firewall import Firewall, Verdict
from .pii import detect, mask
from .profile import load_profile, promote_memory, render_profile
from .proposals import (
    approve_proposal,
    defer_proposal,
    preview_proposal,
    propose_from_memory,
    propose_from_pattern,
    reject_proposal,
)
from .simulate import counterfactual, simulate
from .yaml_io import apply_yaml_import, export_judgment_yaml, preview_yaml_import

__all__ = [
    "Firewall", "Verdict", "detect", "mask",
    "load_profile", "render_profile", "promote_memory",
    "preview_yaml_import", "apply_yaml_import", "export_judgment_yaml",
    "propose_from_memory", "propose_from_pattern",
    "preview_proposal", "approve_proposal", "reject_proposal", "defer_proposal",
    "applicable_pack", "render_applicable",
    "simulate", "counterfactual",
]
